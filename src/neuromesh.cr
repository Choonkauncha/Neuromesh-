require "option_parser"
require "./neuromesh/event"
require "./neuromesh/capabilities"
require "./neuromesh/arbitration"
require "./neuromesh/gateway"
require "./neuromesh/scheduler"

module NeuroMesh
  # `neuromesh --arbitrate packet.json` prints {"claim_id": "status", ...}.
  # Input: {"claims": [{"claim_id": "C1"}...], "evidence": [EvidenceRecord...]}
  def self.arbitrate_file(path : String)
    data = JSON.parse(File.read(path))
    evidence = Array(EvidenceRecord).from_json(data["evidence"].to_json)
    result = {} of String => String
    data["claims"].as_a.each do |claim|
      id = claim["claim_id"].as_s
      result[id] = Arbitration.status(id, evidence)
    end
    puts result.to_json
  end

  def self.smoke(objective : String, log_path : String)
    Dir.mkdir_p(File.dirname(log_path))
    gateway = Gateway.new(objective, log_path)
    runtime = gateway.handle_for(Role::Runtime)
    planner = gateway.handle_for(Role::Planner)
    explorer = gateway.handle_for(Role::Explorer)
    verifier = gateway.handle_for(Role::Verifier)
    executive = gateway.handle_for(Role::Executive)

    runtime.submit(EventType::ObjectiveCreated, nil, {objective: "Exercise capability gateway", mode: "local-smoke"})
    planner.submit(EventType::TaskRequested, "task-1", {goal: "gateway smoke test"})

    scheduler = Scheduler.new(runtime, Budget.new(10_000_i64, 5))
    scheduler.enqueue(ScheduledTask.new("task-1", Role::Explorer, PriorityTier::Normal, Time.utc, 500))
    scheduler.dispatch # reserves budget and logs BudgetReserved before work starts

    runtime.submit(EventType::TaskStarted, "task-1", {region: "explorer"})
    explorer.submit(EventType::ClaimProposed, "task-1",
      {claim_id: "claim-1", statement: "Gateway records authorized proposals", status: "proposed"})
    evidence = [EvidenceRecord.new("ev-1", SourceType::ExecutedCodeOrTest, EvidenceGrade::A,
      IndependenceGroup::IndependentOrigin, supports_claim_ids: ["claim-1"],
      applicability_checked: true, verification_method: "deterministic_gateway_path")]
    explorer.submit(EventType::EvidenceAdded, "task-1", evidence.first)
    verifier.submit(EventType::VerificationRecorded, "task-1",
      {claim_id: "claim-1", result: "smoke_test_passed", method: "deterministic_gateway_path"})
    executive.commit_claim("claim-1", "supported", evidence, "task-1")

    {% for attempt in [{"Explorer", "commit_claim(\"claim-1\", \"supported\", evidence, \"task-1\")"},
                       {"Explorer", "submit(EventType::StateCommitted, \"task-1\", {claim_id: \"claim-1\"})"}] %}
    begin
      explorer.{{ attempt[1].id }}
      STDERR.puts "UNEXPECTED: forged commit was allowed"
      exit 1
    rescue error : CapabilityDenied
      STDERR.puts "Expected denial: #{error.message}"
    end
    {% end %}

    runtime.submit(EventType::TaskCompleted, "task-1",
      {result: "gateway_smoke_complete", note: "No model inference or factual research was performed"})
    puts "Gateway smoke complete. Event log: #{log_path}"
  end
end

objective = "neuromesh-gateway-smoke"
log_path = "logs/gateway-smoke.jsonl"
arbitrate = nil.as(String?)
OptionParser.parse do |parser|
  parser.banner = "Usage: neuromesh [--objective ID] [--log PATH] [--arbitrate FILE]"
  parser.on("--objective ID", "Objective identifier") { |value| objective = value }
  parser.on("--log PATH", "JSONL event log path") { |value| log_path = value }
  parser.on("--arbitrate FILE", "Compute claim statuses for an evidence packet") { |value| arbitrate = value }
  parser.on("-h", "--help", "Show help") { puts parser; exit }
end

if file = arbitrate
  NeuroMesh.arbitrate_file(file)
else
  NeuroMesh.smoke(objective, log_path)
end
