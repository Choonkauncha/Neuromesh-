require "./spec_helper"

private def task(id, tier, at, tokens = 100)
  ScheduledTask.new(id, Role::Explorer, tier, at, tokens)
end

describe ScheduledTask do
  it "ages one tier per interval and stops at Critical" do
    t0 = Time.utc(2026, 1, 1)
    t = task("a", PriorityTier::Low, t0)
    t.effective_tier(t0).should eq PriorityTier::Low
    t.effective_tier(t0 + 31.seconds).should eq PriorityTier::Normal
    t.effective_tier(t0 + 10.minutes).should eq PriorityTier::Critical
  end

  it "does not raise or demote when the clock steps backwards" do
    t0 = Time.utc(2026, 1, 1)
    t = task("a", PriorityTier::Low, t0)
    t.effective_tier(t0 - 5.minutes).should eq PriorityTier::Low
  end
end

describe Scheduler do
  it "dispatches by tier, then age, then id, and logs budget reservation first" do
    with_log do |path|
      g = Gateway.new("obj", path)
      s = Scheduler.new(g.handle_for(Role::Runtime), Budget.new(1000_i64, 10))
      t0 = Time.utc(2026, 1, 1)
      s.enqueue(task("b", PriorityTier::Normal, t0))
      s.enqueue(task("a", PriorityTier::Normal, t0))
      s.enqueue(task("crit", PriorityTier::Critical, t0 + 1.second))
      order = [] of String
      3.times { order << s.dispatch(t0 + 2.seconds).not_nil!.task_id }
      order.should eq ["crit", "a", "b"]
      types = read_events(path).map { |e| e["event_type"].as_s }
      types.count("budget_reserved").should eq 3
    end
  end

  it "lets aging beat a fresher higher tier" do
    with_log do |path|
      s = Scheduler.new(Gateway.new("o", path).handle_for(Role::Runtime), Budget.new(1000_i64, 10))
      t0 = Time.utc(2026, 1, 1)
      s.enqueue(task("old-low", PriorityTier::Low, t0))
      s.enqueue(task("new-high", PriorityTier::High, t0 + 100.seconds))
      s.dispatch(t0 + 100.seconds).not_nil!.task_id.should eq "old-low"
    end
  end

  it "logs BudgetExhausted, raises, and keeps the task queued" do
    with_log do |path|
      s = Scheduler.new(Gateway.new("o", path).handle_for(Role::Runtime), Budget.new(150_i64, 10))
      t0 = Time.utc(2026, 1, 1)
      s.enqueue(task("a", PriorityTier::Normal, t0, 100))
      s.enqueue(task("b", PriorityTier::Normal, t0 + 1.second, 100))
      s.dispatch(t0 + 2.seconds)
      expect_raises(BudgetExhausted) { s.dispatch(t0 + 3.seconds) }
      s.size.should eq 1
      read_events(path).last["event_type"].as_s.should eq "budget_exhausted"
    end
  end

  it "releases unused reservation so later work fits" do
    b = Budget.new(100_i64, 2)
    b.reserve!(100_i64)
    expect_raises(BudgetExhausted) { b.reserve!(1_i64) }
    b.release!(60_i64, 1)
    b.reserve!(60_i64)
    b.remaining_tokens.should eq 0_i64
  end
end
