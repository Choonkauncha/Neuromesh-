#!/usr/bin/env python3
"""Run live baselines: every task x condition x repetition, each in its own
directory, with a full provider transcript and a shared-schema budget ledger.

Fixes two gaps found in the Nov 18 re-evaluation:
- repeat runs used to overwrite each other's log file (same filename, no run
  id). Every repetition now gets its own directory, and the run id is unique.
- the harness keeps only the last 2000 chars of each stage's output, so a
  raw-log review was impossible. RecordingProvider saves every request and
  response in full to transcript.jsonl in the repetition directory.

Usage (needs a live provider key):
    export NEUROMESH_API_KEY=...   # Gemini by default; see providers.py
    python3 eval/run_baselines.py --reps 3
    python3 eval/run_baselines.py --reps 1 --task research-conflicting-sources-01

Outputs under eval/runs/<run-id>/:
    manifest.json                  run-level index (model, caps, statuses)
    <task>__<condition>__rep<N>/
        <task>__<condition>.json   harness run log (as before)
        transcript.jsonl           every provider request/response, full JSON
        budget-ledger.json         shared-schema budget ledger (docs/budget-ledger.md)
        scores.json                deterministic checks from score_auto.py

Note: the provider takes no temperature/seed parameter, so repetitions differ
by sampling. That variance is the point of running reps — read the transcripts
before trusting any score.
"""
import argparse, copy, datetime, json, pathlib, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import harness, score_auto
from budget_ledger import BudgetLedger
from providers import OpenAICompatible

ROOT = pathlib.Path(__file__).resolve().parents[1]


def utc_run_id():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def unique_run_dir(out, run_id):
    base = pathlib.Path(out) / run_id
    if not base.exists():
        return base
    n = 2
    while True:
        cand = pathlib.Path(out) / f"{run_id}-{n}"
        if not cand.exists():
            return cand
        n += 1


def rep_dir(run_dir, task_id, condition, rep):
    return pathlib.Path(run_dir) / f"{task_id}__{condition}__rep{rep}"


class RecordingProvider:
    """Wraps a provider; appends every request and response (full JSON) to a
    JSONL transcript. Failures are recorded too, then re-raised."""

    def __init__(self, inner, transcript_path):
        self.inner = inner
        self.path = pathlib.Path(transcript_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.model = getattr(inner, "model", "?")
        self.n = 0

    def chat(self, messages, tools=None, max_tokens=1800):
        entry = {"call": self.n, "ts": time.time(),
                 "request": {"messages": copy.deepcopy(messages),
                             "tools": copy.deepcopy(tools),
                             "max_tokens": max_tokens}}
        try:
            resp = self.inner.chat(messages, tools=tools, max_tokens=max_tokens)
        except Exception as ex:
            entry["error"] = {"type": type(ex).__name__, "message": str(ex),
                              "attempts": getattr(ex, "attempts", None)}
            self._append(entry)
            self.n += 1
            raise
        entry["response"] = {"message": copy.deepcopy(resp.get("message")),
                             "usage": resp.get("usage", {}),
                             "latency_seconds": resp.get("latency_seconds"),
                             "attempts": resp.get("attempts", [])}
        self._append(entry)
        self.n += 1
        return resp

    def _append(self, entry):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def run_all(provider, tasks, conditions, reps, out, max_total_tokens, wall_clock_seconds, binary):
    run_id = utc_run_id()
    run_dir = unique_run_dir(out, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": run_id, "started_at": time.time(),
                "model": getattr(provider, "model", "?"),
                "reps": reps, "max_total_tokens": max_total_tokens,
                "wall_clock_seconds": wall_clock_seconds, "runs": []}
    for task in tasks:
        for condition in conditions:
            for rep in range(1, reps + 1):
                rdir = rep_dir(run_dir, task["id"], condition, rep)
                rec = RecordingProvider(provider, rdir / "transcript.jsonl")
                path, log = harness.run_one(task, condition, rec, rdir,
                                            max_total_tokens, wall_clock_seconds, binary=binary)
                BudgetLedger.from_harness_log(log, run_id).write(rdir / "budget-ledger.json")
                try:
                    scores = score_auto.score_log(path)
                except Exception as ex:
                    scores = {"error": f"{type(ex).__name__}: {ex}"}
                (rdir / "scores.json").write_text(json.dumps(scores, indent=2))
                manifest["runs"].append({"task_id": task["id"], "condition": condition, "rep": rep,
                                        "dir": str(rdir), "status": log["status"],
                                        "budget": log.get("budget")})
                print(f"{task['id']} {condition} rep{rep}: {log['status']} -> {rdir}", flush=True)
    manifest["finished_at"] = time.time()
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return run_dir, manifest


def main():
    ap = argparse.ArgumentParser(description="Run live baselines with full transcripts.")
    ap.add_argument("--reps", type=int, default=3, help="repetitions per task x condition (default 3)")
    ap.add_argument("--task", default="all", help="task id, or 'all'")
    ap.add_argument("--condition", choices=["both"] + harness.CONDITIONS, default="both")
    ap.add_argument("--out", default=str(ROOT / "eval" / "runs"))
    ap.add_argument("--max-total-tokens", type=int, default=200_000)
    ap.add_argument("--wall-clock-seconds", type=int, default=900)
    ap.add_argument("--binary", default=str(ROOT / "bin" / "neuromesh"),
                    help="Crystal binary for arbitration; if missing, arbitrated statuses are null")
    args = ap.parse_args()
    try:
        provider = OpenAICompatible()
    except RuntimeError as ex:
        print(f"cannot run live baselines: {ex}", file=sys.stderr)
        print("Set NEUROMESH_API_KEY (and optionally NEUROMESH_MODEL / NEUROMESH_BASE_URL).", file=sys.stderr)
        return 2
    data = json.loads((ROOT / "spec" / "eval-set.json").read_text())
    tasks = [t for t in data["tasks"] if args.task in ("all", t["id"])]
    if not tasks:
        print(f"no such task: {args.task}", file=sys.stderr)
        return 2
    conditions = harness.CONDITIONS if args.condition == "both" else [args.condition]
    run_dir, _ = run_all(provider, tasks, conditions, args.reps, args.out,
                         args.max_total_tokens, args.wall_clock_seconds, pathlib.Path(args.binary))
    print(f"done: {run_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
