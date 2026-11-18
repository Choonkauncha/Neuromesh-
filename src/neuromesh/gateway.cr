require "json"
require "uuid"
require "./event"
require "./capabilities"
require "./arbitration"

module NeuroMesh
  class CapabilityDenied < Exception
  end

  class CommitRejected < Exception
  end

  # Capability required to produce each event type. StateCommitted is absent on
  # purpose: it can only be produced through Gateway#commit_claim, which runs
  # evidence arbitration first.
  EVENT_CAPABILITY = {
    EventType::TaskRequested        => Capability::RequestTask,
    EventType::EvidenceAdded        => Capability::AddEvidence,
    EventType::ClaimProposed        => Capability::ProposeClaim,
    EventType::ClaimChallenged      => Capability::ChallengeClaim,
    EventType::VerificationRecorded => Capability::RecordVerification,
    EventType::ToolInvoked          => Capability::InvokeReadOnlyTool,
    EventType::ToolResultRecorded   => Capability::InvokeReadOnlyTool,
    EventType::ObjectiveCreated     => Capability::EmitSystemEvent,
    EventType::TaskScheduled        => Capability::EmitSystemEvent,
    EventType::TaskStarted          => Capability::EmitSystemEvent,
    EventType::TaskCompleted        => Capability::EmitSystemEvent,
    EventType::TaskFailed           => Capability::EmitSystemEvent,
    EventType::BudgetReserved       => Capability::EmitSystemEvent,
    EventType::BudgetExhausted      => Capability::EmitSystemEvent,
  }

  class EventLog
    getter last_version : Int64 = 0_i64

    # Opening an existing log resumes its workspace version so versions stay
    # monotonic across restarts.
    def initialize(@path : String)
      if File.exists?(@path)
        File.each_line(@path) do |line|
          next if line.blank?
          @last_version = JSON.parse(line)["workspace_version"].as_i64
        end
      else
        File.open(@path, "a") { }
      end
    end

    def append(event : CognitiveEvent)
      File.open(@path, "a") { |file| file.puts(event.to_json) }
    end
  end

  # The only object components should be given. It is bound to one role, so a
  # component cannot choose its own actor or role. In-process this is structural
  # discipline, not a security boundary: real isolation needs a process boundary.
  class RoleHandle
    getter role : Role

    def initialize(@gateway : Gateway, @role : Role)
    end

    def authorize!(capability : Capability, task_id : String? = nil)
      @gateway.authorize!(@role, capability, task_id)
    end

    def submit(type : EventType, task_id : String?, payload, causation_id : String? = nil)
      @gateway.submit(@role, type, task_id, payload, causation_id)
    end

    def commit_claim(claim_id : String, requested_status : String,
                     evidence : Array(EvidenceRecord), task_id : String? = nil)
      @gateway.commit_claim(@role, claim_id, requested_status, evidence, task_id)
    end
  end

  class Gateway
    getter version : Int64

    def initialize(@objective_id : String, log_path : String)
      @log = EventLog.new(log_path)
      @version = @log.last_version
    end

    def handle_for(role : Role) : RoleHandle
      RoleHandle.new(self, role)
    end

    protected def authorize!(role : Role, capability : Capability, task_id : String? = nil)
      return true if CapabilityPolicy.allowed?(role, capability)
      deny!(role, capability.to_s, task_id)
    end

    protected def submit(role : Role, type : EventType, task_id : String?, payload,
                         causation_id : String? = nil) : CognitiveEvent
      deny!(role, "#{type} (use commit_claim)", task_id) if type.state_committed?
      capability = EVENT_CAPABILITY[type]? || deny!(role, type.to_s, task_id)
      authorize!(role, capability, task_id)
      append(type, actor_for(role), task_id, payload.to_json, causation_id)
    end

    protected def commit_claim(role : Role, claim_id : String, requested : String,
                               evidence : Array(EvidenceRecord), task_id : String?) : CognitiveEvent
      authorize!(role, Capability::CommitWorkspace, task_id)
      computed = Arbitration.status(claim_id, evidence)
      ids = evidence.map(&.evidence_id)
      unless Arbitration.commit_allowed?(requested, computed)
        append(EventType::CommitRejected, actor_for(role), task_id,
          {claim_id: claim_id, requested: requested, computed: computed, evidence_ids: ids}.to_json)
        raise CommitRejected.new("cannot commit #{claim_id} as #{requested}; evidence supports only #{computed}")
      end
      append(EventType::StateCommitted, actor_for(role), task_id,
        {claim_id: claim_id, status: requested, computed_status: computed, evidence_ids: ids}.to_json)
    end

    private def deny!(role : Role, what : String, task_id : String?) : NoReturn
      append(EventType::CapabilityDenied, actor_for(role), task_id,
        {role: role.to_s, attempted: what}.to_json)
      raise CapabilityDenied.new("#{role} cannot perform #{what}")
    end

    private def append(type : EventType, actor : Actor, task_id : String?,
                       payload_json : String, causation_id : String? = nil) : CognitiveEvent
      @version += 1
      event = CognitiveEvent.new(
        UUID.random.to_s, type, actor, @objective_id, task_id,
        Time.utc.to_rfc3339, @objective_id, causation_id, @version,
        JSON.parse(payload_json))
      @log.append(event)
      event
    end

    private def actor_for(role : Role) : Actor
      case role
      when .planner?        then Actor::Planner
      when .explorer?       then Actor::Explorer
      when .verifier?       then Actor::Verifier
      when .executive?      then Actor::Executive
      when .action_service? then Actor::Tool
      else                       Actor::Runtime
      end
    end
  end
end
