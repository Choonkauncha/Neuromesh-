require "./spec_helper"

describe BudgetLedger do
  it "round-trips through JSON with the shared schema" do
    path = File.tempname("neuromesh-ledger", ".json")
    begin
      ledger = BudgetLedger.new("run-1", "research-conflicting-sources-01",
        "single_agent_tool_loop", "gemini-2.5-flash", 200_000_i64, 100, 900)
      ledger.reserve!(4000_i64, 1, "dispatch")
      ledger.record_actual!(1500_i64, 1, "provider_call")
      ledger.release!(2500_i64, 0, "unused_reservation")
      ledger.used_tokens.should eq 1500_i64
      ledger.reserved_tokens.should eq 1500_i64
      ledger.remaining_tokens.should eq 198_500_i64
      ledger.usage_estimated?.should be_false
      ledger.write(path)
      back = BudgetLedger.read(path)
      back.schema_version.should eq 1
      back.run_id.should eq "run-1"
      back.used_tokens.should eq 1500_i64
      back.entries.size.should eq 3
      back.entries.map(&.kind).should eq ["reserve", "actual", "release"]
    ensure
      File.delete?(path)
    end
  end

  it "rejects unknown entry kinds and negative amounts" do
    expect_raises(ArgumentError) { BudgetLedgerEntry.new("bogus", 1_i64, 1, "x", Time.utc.to_rfc3339) }
    expect_raises(ArgumentError) { BudgetLedgerEntry.new("actual", -1_i64, 1, "x", Time.utc.to_rfc3339) }
  end

  it "records a stop when a cap fires" do
    ledger = BudgetLedger.new("run-2", "t", "c", "m", 100_i64, 1, 60)
    ledger.stop!("token_cap")
    ledger.entries.last.kind.should eq "stop"
    ledger.entries.last.reason.should eq "token_cap"
  end

  it "flags estimated actuals" do
    ledger = BudgetLedger.new("run-3", "t", "c", "m", 100_i64, nil, 60)
    ledger.record_actual!(500_i64, 2, "unattributed_usage", estimated: true)
    ledger.usage_estimated?.should be_true
    ledger.used_tokens.should eq 500_i64
  end
end
