require "./spec_helper"

describe Gateway do
  it "logs authorized submissions with the actor derived from the handle's role" do
    with_log do |path|
      g = Gateway.new("obj", path)
      g.handle_for(Role::Explorer).submit(EventType::ClaimProposed, "t1", {claim_id: "c1"})
      e = read_events(path).last
      e["event_type"].as_s.should eq "claim_proposed"
      e["actor"].as_s.should eq "explorer"
    end
  end

  it "denies and logs an unauthorized capability" do
    with_log do |path|
      g = Gateway.new("obj", path)
      expect_raises(CapabilityDenied) do
        g.handle_for(Role::Verifier).submit(EventType::EvidenceAdded, "t1", {x: 1})
      end
      e = read_events(path).last
      e["event_type"].as_s.should eq "capability_denied"
      e["actor"].as_s.should eq "verifier"
    end
  end

  it "does not let non-runtime roles emit system events" do
    with_log do |path|
      g = Gateway.new("obj", path)
      {Role::Explorer, Role::Planner, Role::Verifier, Role::Executive, Role::ActionService}.each do |role|
        expect_raises(CapabilityDenied) { g.handle_for(role).submit(EventType::TaskCompleted, "t1", {x: 1}) }
      end
    end
  end

  it "does not allow StateCommitted through submit, even for the Executive" do
    with_log do |path|
      g = Gateway.new("obj", path)
      expect_raises(CapabilityDenied) do
        g.handle_for(Role::Executive).submit(EventType::StateCommitted, "t1", {claim_id: "c1"})
      end
      read_events(path).none? { |e| e["event_type"] == "state_committed" }.should be_true
    end
  end

  it "denies commit_claim for every non-Executive role" do
    with_log do |path|
      g = Gateway.new("obj", path)
      evidence = [ev("e1", EvidenceGrade::A, supports: ["c1"])]
      {Role::Explorer, Role::Verifier, Role::Planner, Role::Runtime, Role::ActionService}.each do |role|
        expect_raises(CapabilityDenied) { g.handle_for(role).commit_claim("c1", "supported", evidence, "t1") }
      end
    end
  end

  it "commits a claim only as high as the evidence allows" do
    with_log do |path|
      g = Gateway.new("obj", path)
      exec = g.handle_for(Role::Executive)
      expect_raises(CommitRejected) { exec.commit_claim("c1", "supported", [] of EvidenceRecord, "t1") }
      read_events(path).last["event_type"].as_s.should eq "commit_rejected"
      read_events(path).none? { |e| e["event_type"] == "state_committed" }.should be_true

      strong = [ev("e1", EvidenceGrade::A, supports: ["c1"])]
      exec.commit_claim("c1", "supported", strong, "t1")
      last = read_events(path).last
      last["event_type"].as_s.should eq "state_committed"
      last["payload"]["computed_status"].as_s.should eq "supported"
    end
  end

  it "keeps versions strictly monotonic, including across reopen" do
    with_log do |path|
      g = Gateway.new("obj", path)
      3.times { g.handle_for(Role::Runtime).submit(EventType::TaskStarted, "t", {n: 1}) }
      g2 = Gateway.new("obj", path)
      g2.handle_for(Role::Runtime).submit(EventType::TaskStarted, "t", {n: 2})
      versions = read_events(path).map { |e| e["workspace_version"].as_i64 }
      versions.should eq [1_i64, 2_i64, 3_i64, 4_i64]
    end
  end

  it "writes one valid JSON object per line with required audit fields" do
    with_log do |path|
      g = Gateway.new("obj", path)
      g.handle_for(Role::Runtime).submit(EventType::ObjectiveCreated, nil, {a: "b"})
      read_events(path).each do |e|
        %w(event_id event_type actor objective_id occurred_at correlation_id workspace_version payload).each do |k|
          e.as_h.has_key?(k).should be_true
        end
      end
    end
  end
end
