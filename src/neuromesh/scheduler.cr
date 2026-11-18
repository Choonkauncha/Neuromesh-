module NeuroMesh
  enum PriorityTier
    Critical
    High
    Normal
    Low
  end

  class BudgetExhausted < Exception
  end

  struct ScheduledTask
    getter task_id : String
    getter region : Role
    getter tier : PriorityTier
    getter enqueued_at : Time
    getter estimated_tokens : Int32

    def initialize(@task_id, @region, @tier, @enqueued_at = Time.utc,
                   @estimated_tokens = 0)
    end

    # Aging promotes one tier per interval up to Critical. A clock that steps
    # backwards never demotes below the base tier.
    def effective_tier(now : Time, aging_interval : Time::Span = 30.seconds) : PriorityTier
      age_steps = ((now - @enqueued_at).total_seconds / aging_interval.total_seconds).floor.to_i
      age_steps = 0 if age_steps < 0
      PriorityTier.from_value({0, @tier.value - age_steps}.max)
    end
  end

  class Budget
    getter token_limit : Int64
    getter call_limit : Int32
    getter reserved_tokens : Int64
    getter reserved_calls : Int32

    def initialize(@token_limit : Int64, @call_limit : Int32)
      @reserved_tokens = 0_i64
      @reserved_calls = 0
    end

    def remaining_tokens : Int64
      @token_limit - @reserved_tokens
    end

    def reserve!(tokens : Int64, calls : Int32 = 1)
      raise ArgumentError.new("invalid reservation") if tokens < 0 || calls < 0
      raise BudgetExhausted.new("token budget exhausted") if @reserved_tokens + tokens > @token_limit
      raise BudgetExhausted.new("call budget exhausted") if @reserved_calls + calls > @call_limit
      @reserved_tokens += tokens
      @reserved_calls += calls
    end

    # Return unused reservation (e.g. estimated 4000 tokens, used 1500).
    def release!(tokens : Int64, calls : Int32 = 0)
      raise ArgumentError.new("invalid release") if tokens < 0 || calls < 0
      @reserved_tokens = {0_i64, @reserved_tokens - tokens}.max
      @reserved_calls = {0, @reserved_calls - calls}.max
    end
  end

  # Deterministic dispatcher: lowest effective tier first, then oldest, then
  # task_id. Budget is reserved and logged BEFORE a task is handed out.
  class Scheduler
    def initialize(@handle : RoleHandle, @budget : Budget,
                   @aging_interval : Time::Span = 30.seconds)
      @queue = [] of ScheduledTask
    end

    getter budget : Budget

    def size : Int32
      @queue.size
    end

    def enqueue(task : ScheduledTask)
      @queue << task
      @handle.submit(EventType::TaskScheduled, task.task_id,
        {region: task.region.to_s, tier: task.tier.to_s, estimated_tokens: task.estimated_tokens})
    end

    def dispatch(now : Time = Time.utc) : ScheduledTask?
      return nil if @queue.empty?
      task = @queue.min_by { |t| {t.effective_tier(now, @aging_interval).value, t.enqueued_at, t.task_id} }
      @handle.authorize!(Capability::ReserveBudget, task.task_id)
      begin
        @budget.reserve!(task.estimated_tokens.to_i64, 1)
      rescue ex : BudgetExhausted
        @handle.submit(EventType::BudgetExhausted, task.task_id,
          {reason: ex.message, remaining_tokens: @budget.remaining_tokens})
        raise ex
      end
      @queue.delete(task)
      @handle.submit(EventType::BudgetReserved, task.task_id,
        {tokens: task.estimated_tokens, remaining_tokens: @budget.remaining_tokens})
      task
    end
  end
end
