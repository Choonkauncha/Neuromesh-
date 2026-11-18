# Baseline runbook — first live runs

The goal of the first live runs is not a leaderboard. It is to find out
whether the harness survives contact with a real provider, whether the
tasks discriminate at all, and what the raw logs actually show. Read the
transcripts before trusting any score.

## Prerequisites

1. Build the Crystal binary (needed for arbitration; without it, arbitrated
   statuses are null and the scorer reports that instead of failing):
   ```sh
   make build        # shards build; needs Crystal >= 1.12
   ```
2. A provider key. Defaults are Gemini via an OpenAI-compatible endpoint:
   ```sh
   export NEUROMESH_API_KEY=...
   # optional: NEUROMESH_MODEL (default gemini-2.5-flash),
   #           NEUROMESH_BASE_URL (default generativelanguage.googleapis.com)
   ```

## Run

```sh
python3 eval/run_baselines.py --reps 3
python3 eval/run_baselines.py --reps 1 --task research-conflicting-sources-01
python3 eval/run_baselines.py --reps 1 --condition single_agent_tool_loop
```

Defaults: 200,000 max total tokens and 900 wall-clock seconds per run
(same caps as `harness.py`). Each task × condition × repetition lands in
its own directory under `eval/runs/<run-id>/` — repeat runs can no longer
overwrite each other's logs.

## Outputs (per repetition directory)

| file | contents |
|---|---|
| `<task>__<condition>.json` | harness run log (as before) |
| `transcript.jsonl` | every provider request/response in full — read this first |
| `budget-ledger.json` | shared-schema budget ledger (see `docs/budget-ledger.md`) |
| `scores.json` | deterministic checks from `score_auto.py` |
| `../manifest.json` | run-level index: model, caps, statuses |

## What to check, in order

1. **Did it complete?** `manifest.json` statuses. `provider_failed`,
   `token_cap`, `wall_clock_cap`, and `invalid_output` are findings, not
   noise — record them before re-running.
2. **Read the transcripts.** At least one full repetition per condition.
   Look for: provider quirks (function-calling format, usage reporting),
   whether the model actually used the tools, and whether the repair path
   fired.
3. **Scores second.** `scores.json` is deterministic checks only.
   Subjective rubric dimensions (calibration, explanation quality) are
   evaluator-scored and are not in this file.
4. **Budget ledger.** `usage_estimated: true` means the provider did not
   report usage and the harness estimated from characters — treat those
   token counts as approximate.

## Known limits

- The provider takes no temperature/seed parameter, so repetitions differ
  by sampling. That variance is the point of running reps; do not average
  it away.
- Three tasks (7, 9, and 4 input files) are small; difficulty relative to
  real models is unknown until these runs exist.
- Arbitration trusts model-assigned labels (grade, independence,
  applicability). Live runs show how big that problem is; see
  `docs/gold-reconciliation-2026-11-18.md` for what the second evaluator
  found in the research task's gold.
