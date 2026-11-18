# NEUROMESH v0.1 -> v0.2 development report

## Verification of the v0.1 claims
v0.1 reported that Crystal was not installed and nothing was compiled. This pass installed Crystal 1.14.0 and compiled, ran and specced everything. v0.1 itself compiled and its smoke test ran (12 events, one logged denial). Its weaknesses were in what the README claimed, not in compilation.

## Defects found in v0.1 and what was done

| # | v0.1 defect | Resolution | Evidence |
|---|---|---|---|
| 1 | "Runtime-enforced" gateway: `emit` was public with a caller-supplied actor; anything could emit `StateCommitted` | Role-bound handles, protected gateway methods, per-event capability map, commit only via `commit_claim` | Old entrypoint no longer compiles; external call to `submit` is a compile error; 8 gateway specs |
| 2 | `authorize!` logged success as `ToolInvoked` (misleading audit trail) | Only denials are logged by authorization; the event itself is the audit record | spec + smoke log |
| 3 | Scheduler and Budget were unused; invariant "reserve budget before dispatch" unimplemented | `Scheduler#dispatch` reserves and logs `BudgetReserved` first; `BudgetExhausted` logged and raised; `release!` added | 6 scheduler specs |
| 4 | `effective_tier` raised on a backwards clock (`from_value(4)`) | floor + clamp | spec (mutant confirmed it errors without the guard) |
| 5 | Event versions reset to 0 on restart | log resumes last version | spec |
| 6 | Evidence policy was prose only | `Arbitration` implements it; `superseded_by` added after designing the stateful task exposed that withdrawn sources would keep a claim disputed forever | 9 arbitration specs |
| 7 | Verifier received the explorer's whole output | Typed packet: unknown keys rejected, verbatim-quote check against a pristine snapshot, canonical re-serialisation | 5 harness tests incl. canary |
| 8 | Eval prompts had no inputs, so tasks were not runnable | Frozen inputs for all three tasks; gold outside tool reach | gold fix validated: hidden tests fail 7/12 on original, pass 12/12 on gold fix |
| 9 | `single_agent_tool_loop` had no tools or loop | Shared `ToolBox` + function-calling loop for all conditions; verifier gets read-only subset | sandbox tests |
| 10 | No caps, no failure logging; a failed call crashed the run | Token, wall-clock caps; retries and failures recorded in the run log | 5 tests |
| 11 | `test/` was empty | 23 Crystal specs + 20 Python tests | mutation results below |

## Bugs the new tests caught in this pass's own code
- `write_file` allowed `repo/../logs/x` (path traversal after prefix check).
- Evidence quotes were validated against the *mutated* workspace, so quoting pre-fix code failed after a fix.
- One test expectation was wrong (`rejected` vs `disputed`); the code was right.

## Mutation testing
Crystal: 7 mutants, 6 killed, 1 equivalent (explicit `StateCommitted` check is redundant with the capability map; kept as defense in depth). Python: 6 mutants; 2 initially survived (per-record unknown-key check untested; repair bound untested); tests added, key-check mutant now killed; the repair-loop mutant is equivalent but the bound is now asserted.

## Not verified
- Crystal 1.12 (declared minimum), macOS, or any non-Linux-x86_64 platform.
- Any live model run, real provider function-calling behavior, or real token usage fields.
- Whether the tasks discriminate between real model configurations (only scripted models used).
- Mesh condition, tool adapters for it, concurrency under load.
- Calibration of subjective rubric dimensions; `score_auto.py` deliberately does not score them.
- The gateway as a security boundary (it is not one in-process).

## Design decisions to review
- `disputed` vs `rejected` rules (see policy). A strong contradiction with any original non-D support is `disputed`.
- Equal-tools fairness: Explorer/single agent may `write_file` in the scratch workspace; Verifier is read-only. This asymmetry is intentional and mirrors the capability table.
- Tasks give the model the claims to evaluate (research task) so scoring is tractable. Open-ended claim discovery is not measured.

## Suggested next steps
1. Run both baselines live on 3+ seeds and read the raw logs before trusting any score.
2. Have a second evaluator author independent gold for the research task; compare with the by-construction gold.
3. Unify budget accounting across Crystal and the harness.
4. Only then design the concurrent mesh, with a process boundary around the gateway.
