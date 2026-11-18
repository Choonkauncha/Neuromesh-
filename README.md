# NEUROMESH v0.2 — contracts and evaluation-first scaffold

Contracts, enforcement and baselines first; the concurrent mesh is deliberately not built yet.
See `docs/DEV-REPORT.md` for what changed from v0.1, what was verified, and what was not.

## Layout

- `src/neuromesh/` — Crystal runtime: event/evidence types, capability policy, **gateway** (the only path to the event log), **arbitration** (deterministic claim status), **scheduler** (tiers, aging, budget reserve-before-dispatch).
- `spec/*_spec.cr` — 23 Crystal specs. `spec/evidence-policy.md`, `spec/eval-set.json` — policy and frozen task definitions.
- `spec/tasks/<id>/inputs/` — frozen task inputs (what the models see). `spec/gold/` — evaluator-only gold, unreachable by model tools.
- `eval/` — Python harness (`harness.py`), typed evidence packet (`packet.py`), toolbox, providers, deterministic scorer (`score_auto.py`), 20 tests (`test_eval.py`).

## Build and test

Requires Crystal >= 1.12 (tested on 1.14.0, Linux x86_64) and Python 3.10+. No Python dependencies.

```sh
make test      # shards build, crystal spec, python unittest
make smoke     # gateway smoke path, writes logs/gateway-smoke.jsonl
```

## Run baselines (needs an API key; not yet run live)

```sh
export NEUROMESH_API_KEY=...   # optional: NEUROMESH_MODEL, NEUROMESH_BASE_URL (OpenAI-compatible, function calling)
python3 eval/harness.py --condition single_agent_tool_loop --max-total-tokens 200000 --wall-clock-seconds 900
python3 eval/harness.py --condition sequential_planner_explorer_verifier
python3 eval/score_auto.py eval/runs/*.json
```

Both conditions share the same toolbox, output schema, caps, and one recorded repair attempt. `score_auto.py` reports deterministic checks only; subjective rubric dimensions are evaluator-scored.

## Enforcement model

1. Components receive a `RoleHandle` bound to one role; they cannot choose their actor or role. `Gateway#submit/authorize!/commit_claim` are `protected`; calling them from outside the `NeuroMesh` namespace is a compile error.
2. Every event type maps to a required capability. `StateCommitted` is only reachable through `commit_claim`, which runs arbitration first.
3. Denials are logged as `capability_denied` with the attempted action.
4. Budget is reserved and logged before a task is handed out; exhaustion is logged and raised.
5. The Verifier receives only a schema-validated claim/evidence packet. Unknown keys are rejected, so a reasoning narrative cannot ride along; every excerpt must be a verbatim quote of the pristine source.

## Limits

- The gateway is in-process discipline, **not a security boundary**. A hostile component in the same process can still bypass it. Real isolation needs a process boundary.
- Arbitration trusts model-assigned labels (grade, independence, applicability).
- No live model run has been performed. The harness is verified only with scripted models. Provider quirks (function-calling format, usage reporting) are untested.
- Three tasks (7, 9 and 4 input files) are small; difficulty relative to real models is unknown. Gold is correct by construction, but evaluator calibration is still required.
- The mesh condition does not exist. Crystal budget accounting and the harness token cap are separate implementations.
