"""Shared budget ledger: the one budget schema both runtimes speak.

The Crystal runtime (src/neuromesh/budget_ledger.cr) implements the same
schema. Two implementations, one format: a ledger file written by either
side is valid input to the other. See docs/budget-ledger.md.

Shared semantics:
- reserve: tokens/calls set aside BEFORE work is dispatched (an estimate).
- actual: tokens/calls really consumed, recorded AFTER a call returns.
- release: unused reservation returned (estimated 4000, used 1500 -> release 2500).
- stop: the run ended because a cap fired (token_cap / wall_clock_cap / call_cap).
"""
import json, time
from pathlib import Path

SCHEMA_VERSION = 1
KINDS = ("reserve", "actual", "release", "stop")


class LedgerError(ValueError):
    pass


def _iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class BudgetLedger:
    def __init__(self, run_id, task_id, condition, model, token_limit, call_limit, wall_cap_seconds):
        self.schema_version = SCHEMA_VERSION
        self.run_id = run_id
        self.task_id = task_id
        self.condition = condition
        self.model = model
        self.token_limit = int(token_limit)
        # None means uncapped (the harness has no call limit; Crystal does).
        self.call_limit = None if call_limit is None else int(call_limit)
        self.wall_cap_seconds = int(wall_cap_seconds)
        self.entries = []

    def _event(self, kind, tokens, calls, reason, estimated=False, at=None):
        if kind not in KINDS:
            raise LedgerError(f"unknown ledger entry kind: {kind!r}")
        if int(tokens) < 0 or int(calls) < 0:
            raise LedgerError("ledger amounts must be non-negative")
        self.entries.append({"kind": kind, "tokens": int(tokens), "calls": int(calls),
                             "reason": reason, "at": at or _iso_now(), "estimated": bool(estimated)})

    def reserve(self, tokens, calls=1, reason="dispatch"):
        self._event("reserve", tokens, calls, reason)

    def record_actual(self, tokens, calls=1, reason="provider_call", estimated=False):
        self._event("actual", tokens, calls, reason, estimated=estimated)

    def release(self, tokens, calls=0, reason="unused_reservation"):
        self._event("release", tokens, calls, reason)

    def stop(self, reason):
        self._event("stop", 0, 0, reason)

    @property
    def reserved_tokens(self):
        return (sum(e["tokens"] for e in self.entries if e["kind"] == "reserve") -
                sum(e["tokens"] for e in self.entries if e["kind"] == "release"))

    @property
    def used_tokens(self):
        return sum(e["tokens"] for e in self.entries if e["kind"] == "actual")

    @property
    def used_calls(self):
        return sum(e["calls"] for e in self.entries if e["kind"] == "actual")

    @property
    def remaining_tokens(self):
        return self.token_limit - self.reserved_tokens

    @property
    def usage_estimated(self):
        return any(e["estimated"] for e in self.entries if e["kind"] == "actual")

    def to_dict(self):
        return {"schema_version": self.schema_version, "run_id": self.run_id,
                "task_id": self.task_id, "condition": self.condition, "model": self.model,
                "token_limit": self.token_limit, "call_limit": self.call_limit,
                "wall_cap_seconds": self.wall_cap_seconds, "entries": list(self.entries),
                "totals": {"reserved_tokens": self.reserved_tokens, "used_tokens": self.used_tokens,
                           "used_calls": self.used_calls, "remaining_tokens": self.remaining_tokens,
                           "usage_estimated": self.usage_estimated}}

    def write(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def validate(cls, d):
        if not isinstance(d, dict):
            raise LedgerError("ledger must be a JSON object")
        if d.get("schema_version") != SCHEMA_VERSION:
            raise LedgerError(f"unsupported ledger schema_version: {d.get('schema_version')!r}")
        for key in ("run_id", "task_id", "condition", "model", "token_limit", "wall_cap_seconds"):
            if key not in d:
                raise LedgerError(f"ledger missing {key!r}")
        if not isinstance(d.get("entries"), list):
            raise LedgerError("ledger entries must be a list")
        for i, e in enumerate(d["entries"]):
            if e.get("kind") not in KINDS:
                raise LedgerError(f"entries[{i}] unknown kind {e.get('kind')!r}")
            if int(e.get("tokens", -1)) < 0 or int(e.get("calls", -1)) < 0:
                raise LedgerError(f"entries[{i}] negative amounts")
        return d

    @classmethod
    def read(cls, path):
        d = cls.validate(json.loads(Path(path).read_text()))
        led = cls(d["run_id"], d["task_id"], d["condition"], d["model"],
                  d["token_limit"], d.get("call_limit"), d["wall_cap_seconds"])
        led.entries = d["entries"]
        return led

    @classmethod
    def from_harness_log(cls, log, run_id):
        """Build a ledger from a harness run_one log dict.

        Per-call actuals come from the stage call logs where usage was
        reported; any remainder versus the harness budget total is one
        estimated actual entry, so estimated usage stays flagged, never
        silently converted to exact.
        """
        budget = log.get("budget") or {}
        led = cls(run_id, log["task_id"], log["condition"], log.get("model", "?"),
                  budget.get("token_cap", 0), None, budget.get("wall_cap", 0))
        reported, reported_calls = 0, 0
        for stage in log.get("stages", []):
            for call in stage.get("calls", []):
                used = (call.get("usage") or {}).get("total_tokens")
                if used is not None:
                    led.record_actual(int(used), 1, "provider_call")
                    reported += int(used)
                    reported_calls += 1
        total = int(budget.get("tokens_used", 0))
        if total > reported:
            residual_calls = max(0, int(budget.get("calls", 0)) - reported_calls)
            led.record_actual(total - reported, residual_calls, "unattributed_usage", estimated=True)
        if log.get("status") in ("token_cap", "wall_clock_cap", "call_cap"):
            led.stop(log["status"])
        return led
