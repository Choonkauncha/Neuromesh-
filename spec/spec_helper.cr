require "spec"
require "../src/neuromesh/event"
require "../src/neuromesh/capabilities"
require "../src/neuromesh/arbitration"
require "../src/neuromesh/gateway"
require "../src/neuromesh/scheduler"

include NeuroMesh

def with_log(&)
  path = File.tempname("neuromesh", ".jsonl")
  begin
    yield path
  ensure
    File.delete?(path)
  end
end

def read_events(path : String) : Array(JSON::Any)
  File.read_lines(path).reject(&.blank?).map { |l| JSON.parse(l) }
end

def ev(id, grade, group = IndependenceGroup::IndependentOrigin, supports = [] of String,
       contradicts = [] of String, publisher : String? = nil, derived = [] of String,
       applicable = true, superseded_by : String? = nil)
  EvidenceRecord.new(id, SourceType::PrimaryDocument, grade, group,
    publisher: publisher, derived_from: derived, supports_claim_ids: supports,
    contradicts_claim_ids: contradicts, applicability_checked: applicable,
    superseded_by: superseded_by)
end
