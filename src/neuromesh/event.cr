require "json"

module NeuroMesh
  enum EventType
    ObjectiveCreated
    TaskRequested
    TaskScheduled
    TaskStarted
    EvidenceAdded
    ClaimProposed
    ClaimChallenged
    VerificationRecorded
    StateCommitted
    CommitRejected
    CapabilityDenied
    ToolInvoked
    ToolResultRecorded
    BudgetReserved
    BudgetExhausted
    TaskCompleted
    TaskFailed
  end

  enum SourceType
    PrimaryDocument
    OfficialDocumentation
    ExecutedCodeOrTest
    DirectToolObservation
    PeerReviewedPublication
    ReputableSecondarySource
    CommunityOrForum
    ModelGenerated
    UserProvided
    Unknown
  end

  # Ordinal grades, not probabilities. Unknown is deliberately not ordered as
  # a weak source: it means provenance has not been established.
  enum EvidenceGrade
    A
    B
    C
    D
    Unassessed
  end

  enum IndependenceGroup
    IndependentOrigin
    SamePublisher
    SameUnderlyingDataset
    SameQuotedSource
    DerivedFromOtherEvidence
    Unknown
  end

  enum Actor
    Runtime
    Executive
    Planner
    Explorer
    Verifier
    Tool
    User
  end

  struct EvidenceRecord
    include JSON::Serializable
    getter evidence_id : String
    getter source_type : SourceType
    getter grade : EvidenceGrade
    getter independence_group : IndependenceGroup
    getter provenance_uri : String?
    getter publisher : String?
    getter retrieved_at : String = ""
    getter derived_from : Array(String) = [] of String
    getter supports_claim_ids : Array(String) = [] of String
    getter contradicts_claim_ids : Array(String) = [] of String
    getter excerpt_hash : String?
    getter verification_method : String?
    # True only when a reviewer has checked that the evidence applies to the
    # exact claim (version, configuration, scope). Required for A/B to count.
    getter applicability_checked : Bool = false
    # evidence_id of newer evidence that withdraws or corrects this item. Kept for
    # provenance, excluded from arbitration while the superseder is itself live.
    getter superseded_by : String?

    def initialize(@evidence_id, @source_type, @grade, @independence_group,
                   @provenance_uri = nil, @publisher = nil,
                   @retrieved_at = Time.utc.to_rfc3339,
                   @derived_from = [] of String,
                   @supports_claim_ids = [] of String,
                   @contradicts_claim_ids = [] of String,
                   @excerpt_hash = nil, @verification_method = nil,
                   @applicability_checked = false, @superseded_by = nil)
    end
  end

  struct ClaimRecord
    include JSON::Serializable
    getter claim_id : String
    getter statement : String
    getter status : String # proposed | provisional | supported | disputed | rejected
    getter evidence_ids : Array(String)
    getter created_by : Actor
    getter created_at : String
    getter revision : Int64

    def initialize(@claim_id, @statement, @status, @evidence_ids,
                   @created_by, @created_at, @revision = 1_i64)
    end
  end

  struct CognitiveEvent
    include JSON::Serializable
    getter event_id : String
    getter event_type : EventType
    getter actor : Actor
    getter objective_id : String
    getter task_id : String?
    getter occurred_at : String
    getter correlation_id : String
    getter causation_id : String?
    getter workspace_version : Int64
    getter payload : JSON::Any

    def initialize(@event_id, @event_type, @actor, @objective_id,
                   @task_id, @occurred_at, @correlation_id, @causation_id,
                   @workspace_version, @payload)
    end
  end
end
