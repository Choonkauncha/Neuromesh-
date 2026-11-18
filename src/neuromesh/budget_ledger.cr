require "json"

module NeuroMesh
  # Shared budget ledger: the one budget schema both runtimes speak.
  # The Python harness (eval/budget_ledger.py) implements the same schema.
  # A ledger file written by either side is valid input to the other.
  # See docs/budget-ledger.md.
  #
  # Shared semantics:
  # - reserve: tokens/calls set aside BEFORE work is dispatched (an estimate).
  # - actual: tokens/calls really consumed, recorded AFTER a call returns.
  # - release: unused reservation returned (estimated 4000, used 1500 -> release 2500).
  # - stop: the run ended because a cap fired (token_cap / wall_clock_cap / call_cap).
  #
  # The ledger records; it does not enforce. Enforcement stays in Budget
  # (scheduler.cr), which raises BudgetExhausted. The mesh runtime, when it
  # exists, reads harness ledgers through BudgetLedger.read.
  struct BudgetLedgerEntry
    include JSON::Serializable

    getter kind : String
    getter tokens : Int64
    getter calls : Int32
    getter reason : String
    getter at : String
    getter estimated : Bool = false

    def initialize(@kind, @tokens, @calls, @reason, @at, @estimated = false)
      unless {"reserve", "actual", "release", "stop"}.includes?(@kind)
        raise ArgumentError.new("unknown ledger entry kind: #{@kind}")
      end
      raise ArgumentError.new("negative ledger amounts") if @tokens < 0 || @calls < 0
    end
  end

  class BudgetLedger
    include JSON::Serializable

    getter schema_version : Int32 = 1
    getter run_id : String
    getter task_id : String
    getter condition : String
    getter model : String
    getter token_limit : Int64
    # Nil means uncapped (the harness has no call limit; Crystal budgets do).
    getter call_limit : Int32?
    getter wall_cap_seconds : Int32
    getter entries : Array(BudgetLedgerEntry) = [] of BudgetLedgerEntry

    def initialize(@run_id, @task_id, @condition, @model, @token_limit, @call_limit, @wall_cap_seconds)
    end

    def reserve!(tokens : Int64, calls : Int32 = 1, reason : String = "dispatch")
      push("reserve", tokens, calls, reason)
    end

    def record_actual!(tokens : Int64, calls : Int32 = 1, reason : String = "provider_call", estimated : Bool = false)
      push("actual", tokens, calls, reason, estimated)
    end

    def release!(tokens : Int64, calls : Int32 = 0, reason : String = "unused_reservation")
      push("release", tokens, calls, reason)
    end

    def stop!(reason : String)
      push("stop", 0_i64, 0, reason)
    end

    def reserved_tokens : Int64
      @entries.select { |e| e.kind == "reserve" }.sum(&.tokens) -
        @entries.select { |e| e.kind == "release" }.sum(&.tokens)
    end

    def used_tokens : Int64
      @entries.select { |e| e.kind == "actual" }.sum(&.tokens)
    end

    def used_calls : Int32
      @entries.select { |e| e.kind == "actual" }.sum(&.calls)
    end

    def remaining_tokens : Int64
      @token_limit - reserved_tokens
    end

    def usage_estimated? : Bool
      @entries.any? { |e| e.kind == "actual" && e.estimated }
    end

    def totals : Hash(String, Int64 | Int32 | Bool)
      {"reserved_tokens" => reserved_tokens, "used_tokens" => used_tokens,
       "used_calls" => used_calls, "remaining_tokens" => remaining_tokens,
       "usage_estimated" => usage_estimated?} of String => Int64 | Int32 | Bool
    end

    def write(path : String)
      File.write(path, to_json)
    end

    def self.read(path : String) : BudgetLedger
      ledger = from_json(File.read(path))
      ledger.validate!
      ledger
    end

    def validate!
      raise ArgumentError.new("unsupported ledger schema_version: #{@schema_version}") unless @schema_version == 1
      @entries.each do |e|
        unless {"reserve", "actual", "release", "stop"}.includes?(e.kind)
          raise ArgumentError.new("unknown ledger entry kind: #{e.kind}")
        end
      end
    end

    private def push(kind : String, tokens : Int64, calls : Int32, reason : String, estimated : Bool = false)
      @entries << BudgetLedgerEntry.new(kind, tokens, calls, reason, Time.utc.to_rfc3339, estimated)
    end
  end
end
