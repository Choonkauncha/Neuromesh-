require "./spec_helper"

describe Arbitration do
  it "is proposed with no evidence and provisional with only weak support" do
    Arbitration.status("c", [] of EvidenceRecord).should eq "proposed"
    Arbitration.status("c", [ev("e", EvidenceGrade::D, supports: ["c"])]).should eq "provisional"
  end

  it "does not let agreeing derived items or item counts create support" do
    root = ev("root", EvidenceGrade::C, supports: ["c"], publisher: "A")
    copies = (1..5).map do |i|
      ev("copy#{i}", EvidenceGrade::C, IndependenceGroup::SameQuotedSource,
        supports: ["c"], derived: ["root"])
    end
    Arbitration.status("c", [root] + copies).should eq "provisional"
  end

  it "supports on one applicable A/B item but not when applicability is unchecked" do
    Arbitration.status("c", [ev("e", EvidenceGrade::B, supports: ["c"])]).should eq "supported"
    Arbitration.status("c", [ev("e", EvidenceGrade::A, supports: ["c"], applicable: false)]).should eq "provisional"
  end

  it "needs two independent origins of C evidence; same publisher counts once" do
    a = ev("a", EvidenceGrade::C, supports: ["c"], publisher: "Pub")
    b = ev("b", EvidenceGrade::C, supports: ["c"], publisher: "pub ")
    d = ev("d", EvidenceGrade::C, supports: ["c"], publisher: "Other")
    Arbitration.status("c", [a, b]).should eq "provisional"
    Arbitration.status("c", [a, d]).should eq "supported"
  end

  it "keeps a claim disputed under conflicting A/B evidence" do
    sup = ev("s", EvidenceGrade::A, supports: ["c"])
    con = ev("k", EvidenceGrade::B, contradicts: ["c"])
    Arbitration.status("c", [sup, con]).should eq "disputed"
  end

  it "rejects when strong contradiction meets only weak or derived support" do
    con = ev("k", EvidenceGrade::A, contradicts: ["c"])
    weak = ev("w", EvidenceGrade::D, supports: ["c"])
    derived = ev("x", EvidenceGrade::C, IndependenceGroup::SameQuotedSource, supports: ["c"], derived: ["k"])
    Arbitration.status("c", [con, weak, derived]).should eq "rejected"
  end

  it "excludes superseded evidence only while its superseder is live" do
    old = ev("old", EvidenceGrade::B, supports: ["c"], superseded_by: "errata")
    errata = ev("errata", EvidenceGrade::A, contradicts: ["c"])
    Arbitration.status("c", [old, errata]).should eq "rejected"
    Arbitration.status("c", [ev("old", EvidenceGrade::B, supports: ["c"], superseded_by: "ghost")]).should eq "supported"
    dead = ev("errata", EvidenceGrade::A, contradicts: ["c"], superseded_by: "newer")
    newer = ev("newer", EvidenceGrade::A, supports: ["c"])
    Arbitration.status("c", [old, dead, newer]).should eq "supported"
    Arbitration.status("c", [ev("self", EvidenceGrade::B, supports: ["c"], superseded_by: "self")]).should eq "supported"
  end

  it "ignores unassessed evidence" do
    Arbitration.status("c", [ev("e", EvidenceGrade::Unassessed, supports: ["c"])]).should eq "proposed"
  end

  it "only allows commits at or below the computed ladder" do
    Arbitration.commit_allowed?("supported", "supported").should be_true
    Arbitration.commit_allowed?("provisional", "supported").should be_true
    Arbitration.commit_allowed?("supported", "provisional").should be_false
    Arbitration.commit_allowed?("supported", "disputed").should be_false
    Arbitration.commit_allowed?("bogus", "supported").should be_false
  end
end
