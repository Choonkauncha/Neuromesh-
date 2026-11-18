require "set"
require "./event"

module NeuroMesh
  # Deterministic claim-status arbitration implementing spec/evidence-policy.md.
  # No numeric confidence is computed anywhere: grades are ordinal and only
  # gate which status a claim may hold.
  module Arbitration
    extend self

    STATUSES = %w(proposed provisional supported disputed rejected)
    RANK     = {"proposed" => 0, "provisional" => 1, "supported" => 2}

    # Evidence that stands on its own origin (not quoted/derived from other items).
    def original?(e : EvidenceRecord) : Bool
      e.independence_group.independent_origin? && e.derived_from.empty?
    end

    # Directly relevant A/B evidence whose applicability was checked.
    def strong?(e : EvidenceRecord) : Bool
      original?(e) && (e.grade.a? || e.grade.b?) && e.applicability_checked
    end

    # Independence is by origin, never by item count: one publisher is one origin.
    def independent_origin_count(items : Array(EvidenceRecord)) : Int32
      keys = Set(String).new
      items.each do |e|
        next unless original?(e)
        keys << (e.publisher.try(&.strip.downcase) || e.evidence_id)
      end
      keys.size
    end

    def superseded?(e : EvidenceRecord, all : Array(EvidenceRecord)) : Bool
      id = e.superseded_by
      return false if id.nil? || id == e.evidence_id
      all.any? { |o| o.evidence_id == id && o.superseded_by.nil? }
    end

    def status(claim_id : String, evidence : Array(EvidenceRecord)) : String
      evidence = evidence.reject { |e| superseded?(e, evidence) }
      support = evidence.select { |e| e.supports_claim_ids.includes?(claim_id) && !e.grade.unassessed? }
      contra = evidence.select { |e| e.contradicts_claim_ids.includes?(claim_id) && !e.grade.unassessed? }

      strong_support = support.any? { |e| strong?(e) }
      strong_contra = contra.any? { |e| strong?(e) }
      independent_c = independent_origin_count(
        support.select { |e| e.grade.c? && e.applicability_checked }) >= 2

      if strong_contra
        credible_original_support = support.any? { |e| original?(e) && !e.grade.d? }
        return credible_original_support ? "disputed" : "rejected"
      end
      return "supported" if strong_support || independent_c
      return "provisional" unless support.empty?
      "proposed"
    end

    # An Executive may commit the computed status or downgrade along the
    # proposed < provisional < supported ladder; it may never exceed it.
    def commit_allowed?(requested : String, computed : String) : Bool
      return false unless STATUSES.includes?(requested)
      return true if requested == computed
      RANK.has_key?(requested) && RANK.has_key?(computed) && RANK[requested] < RANK[computed]
    end
  end
end
