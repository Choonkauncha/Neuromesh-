module NeuroMesh
  enum Role
    Runtime
    Planner
    Explorer
    Verifier
    Executive
    ActionService
  end

  enum Capability
    ReadWorkspace
    ReadEvidence
    ProposeClaim
    AddEvidence
    RequestTask
    ChallengeClaim
    RecordVerification
    CommitWorkspace
    ReserveBudget
    InvokeReadOnlyTool
    InvokeExternalAction
    ApproveExternalAction
    ChangePolicy
    EmitSystemEvent
  end

  # Explicit allow-list. Unknown capabilities fail closed.
  module CapabilityPolicy
    extend self

    def allowed?(role : Role, capability : Capability) : Bool
      case role
      when .runtime?
        {Capability::ReadWorkspace, Capability::ReadEvidence,
         Capability::ReserveBudget, Capability::EmitSystemEvent}.includes?(capability)
      when .planner?
        {Capability::ReadWorkspace, Capability::ReadEvidence,
         Capability::RequestTask}.includes?(capability)
      when .explorer?
        {Capability::ReadWorkspace, Capability::ReadEvidence,
         Capability::ProposeClaim, Capability::AddEvidence,
         Capability::RequestTask, Capability::InvokeReadOnlyTool}.includes?(capability)
      when .verifier?
        {Capability::ReadEvidence, Capability::ChallengeClaim,
         Capability::RecordVerification, Capability::InvokeReadOnlyTool}.includes?(capability)
      when .executive?
        {Capability::ReadWorkspace, Capability::ReadEvidence,
         Capability::CommitWorkspace, Capability::ReserveBudget}.includes?(capability)
      when .action_service?
        {Capability::InvokeExternalAction}.includes?(capability)
      else
        false
      end
    end
  end
end
