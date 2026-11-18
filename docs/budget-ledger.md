# Budget ledger — one schema, two runtimes

Before Nov 18, 2026, budget accounting was two separate implementations that
never talked to each other: the Crystal `Budget` (reserve-before-dispatch,
estimates, call limit) and the harness `RunBudget` (actuals after the call,
token + wall-clock caps, no call limit). The README listed that split as a
limit. This ledger unifies the *schema*: one JSON format, implemented in
both runtimes, so a ledger file written by either side is valid input to the
other.

## Schema (version 1)

```json
{
  "schema_version": 1,
  "run_id": "20261118T183000Z",
  "task_id": "research-conflicting-sources-01",
  "condition": "single_agent_tool_loop",
  "model": "gemini-2.5-flash",
  "token_limit": 200000,
  "call_limit": null,
  "wall_cap_seconds": 900,
  "entries": [
    {"kind": "reserve", "tokens": 4000, "calls": 1, "reason": "dispatch",
     "at": "2026-11-18T18:30:00Z", "estimated": false},
    {"kind": "actual", "tokens": 1500, "calls": 1, "reason": "provider_call",
     "at": "2026-11-18T18:30:02Z", "estimated": false},
    {"kind": "release", "tokens": 2500, "calls": 0, "reason": "unused_reservation",
     "at": "2026-11-18T18:30:02Z", "estimated": false},
    {"kind": "stop", "tokens": 0, "calls": 0, "reason": "token_cap",
     "at": "2026-11-18T18:31:00Z", "estimated": false}
  ],
  "totals": {"reserved_tokens": 1500, "used_tokens": 1500, "used_calls": 1,
             "remaining_tokens": 198500, "usage_estimated": false}
}
```

Entry kinds (shared semantics):

| kind | meaning |
|---|---|
| `reserve` | tokens/calls set aside BEFORE work is dispatched (an estimate) |
| `actual` | tokens/calls really consumed, recorded AFTER a call returns |
| `release` | unused reservation returned (estimated 4000, used 1500 → release 2500) |
| `stop` | the run ended because a cap fired (`token_cap`, `wall_clock_cap`, `call_cap`) |

Rules:

- Amounts are non-negative integers. `call_limit: null` means uncapped.
- `estimated: true` on an `actual` entry means the token count was estimated
  (chars/4), not reported by the provider. Estimated usage stays flagged,
  never silently converted to exact.
- `reserved_tokens = sum(reserve) - sum(release)`.
  `remaining_tokens = token_limit - reserved_tokens`.
- `totals` is a derived convenience block, not source data: the Python
  writer includes it; the Crystal side computes the same values via
  `BudgetLedger#totals`. Either side can recompute it from `entries`.

## Implementations

- Python: `eval/budget_ledger.py` — `BudgetLedger` with `reserve`,
  `record_actual`, `release`, `stop`, `to_dict`/`write`, `read`/`validate`,
  and `from_harness_log` (builds a ledger from a `run_one` log dict).
  The baseline runner (`eval/run_baselines.py`) writes one
  `budget-ledger.json` per repetition.
- Crystal: `src/neuromesh/budget_ledger.cr` — `BudgetLedger` /
  `BudgetLedgerEntry` (`JSON::Serializable`), same fields and kinds,
  `reserve!` / `record_actual!` / `release!` / `stop!`, `write` / `read`
  (read validates the schema version and entry kinds).
  Spec: `spec/budget_ledger_spec.cr`.

## What "unified" means now — and what it does not

Unified now: the format, the event semantics, and the totals. A harness
ledger can be read by Crystal code and vice versa, and both sides are
tested (Python: `eval/test_eval.py`, `LedgerAndRunnerTests`; Crystal:
`spec/budget_ledger_spec.cr`).

Not unified yet: runtime enforcement. The ledger *records*; it does not
enforce. Enforcement still lives in `Budget` (Crystal, raises
`BudgetExhausted`) and `RunBudget` (harness, raises `BudgetStop`). The
Crystal scheduler does not yet read harness ledgers at runtime — that
integration belongs with the mesh, when one process's budget must be visible
to the other side. Until then, the ledger is the audit trail both sides
agree on, not a shared live counter.
