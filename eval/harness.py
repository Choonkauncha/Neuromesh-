#!/usr/bin/env python3
"""NEUROMESH evaluation runner: single-agent and sequential baselines.

Both conditions use the same ToolBox, the same output schema, the same caps, and
one structured-output repair attempt. The mesh condition is intentionally absent.
"""
import argparse, copy, json, pathlib, shutil, sys, tempfile, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import packet as pk
from providers import OpenAICompatible, ProviderError
from toolbox import ToolBox

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONDITIONS = ["single_agent_tool_loop", "sequential_planner_explorer_verifier"]

POLICY = """Evidence rules. grade: a = direct, reproducible evidence for the exact claim (executed test output, primary record);
b = strong traceable source with one important limitation; c = credible but indirect (reputable secondary); d = weak/anecdotal/unverified;
unassessed = not reviewed. Grades are ordinal labels, never probabilities. independence_group: use independent_origin ONLY if the item stands on its own
origin. A source that quotes or summarises another uses same_quoted_source or derived_from_other_evidence AND lists the parent in derived_from;
two items built on the same dataset use same_underlying_dataset. Item count is not corroboration. applicability_checked is true ONLY if you verified
the evidence applies to the exact claim scope (version, configuration). If a later source withdraws or corrects an earlier one, keep the old record and set its superseded_by to the newer record's evidence_id. Every excerpt must be a verbatim quote (8-400 chars) from the cited
source_file (or from your own run_tests output with source_file 'tool:run_tests'). Never invent sources or quotes."""

EVIDENCE_SHAPE = '{"evidence_id":"e1","source_file":"<path>","source_type":"<one of primary_document|official_documentation|executed_code_or_test|direct_tool_observation|peer_reviewed_publication|reputable_secondary_source|community_or_forum|model_generated|user_provided|unknown>","grade":"a|b|c|d|unassessed","publisher":"<optional>","independence_group":"independent_origin|same_publisher|same_underlying_dataset|same_quoted_source|derived_from_other_evidence|unknown","derived_from":["<evidence_id>"],"supports":["<claim_id>"],"contradicts":["<claim_id>"],"excerpt":"<verbatim>","applicability_checked":true,"superseded_by":"<optional evidence_id of newer evidence that withdraws or corrects this one>"}'
CLAIM_SHAPE = '{"claim_id":"C1","statement":"<=400 chars","status":"proposed|provisional|supported|disputed|rejected","supersedes":["<claim_id>"]}'


class BudgetStop(Exception):
    pass


class RunBudget:
    def __init__(self, max_tokens, wall_seconds, clock=time.time):
        self.max_tokens, self.wall_seconds, self.clock = max_tokens, wall_seconds, clock
        self.start, self.tokens, self.calls, self.estimated = clock(), 0, 0, False

    def check(self):
        if self.tokens >= self.max_tokens: raise BudgetStop("token_cap")
        if self.clock() - self.start >= self.wall_seconds: raise BudgetStop("wall_clock_cap")

    def add(self, usage, messages, message):
        used = usage.get("total_tokens")
        if used is None:
            self.estimated = True
            used = (len(json.dumps(messages)) + len(json.dumps(message))) // 4
        self.tokens += int(used); self.calls += 1

    def report(self):
        return {"tokens_used": self.tokens, "token_cap": self.max_tokens, "calls": self.calls,
                "wall_seconds": round(self.clock() - self.start, 3), "wall_cap": self.wall_seconds,
                "usage_estimated": self.estimated}


def run_agent(provider, budget, slog, system, user, tools, toolbox, max_steps=12, max_tokens=1800):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for _ in range(max_steps):
        budget.check()
        try:
            resp = provider.chat(messages, tools=tools or None, max_tokens=max_tokens)
        except ProviderError as ex:
            slog["calls"].append({"error": str(ex), "attempts": ex.attempts})
            raise
        msg = resp["message"]
        budget.add(resp.get("usage", {}), messages, msg)
        call_log = {"usage": resp.get("usage", {}), "latency_seconds": resp["latency_seconds"],
                    "attempts": resp["attempts"], "tool_calls": []}
        slog["calls"].append(call_log)
        messages.append(msg)
        tcs = msg.get("tool_calls") or []
        if not tcs:
            return msg.get("content") or ""
        for tc in tcs:
            fn = tc["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = None
            result = toolbox.call(fn["name"], args) if args is not None else "ERROR: arguments were not valid JSON"
            call_log["tool_calls"].append({"name": fn["name"], "args": args})
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})
    slog["stopped"] = "max_steps"
    return ""


def structured(provider, budget, slog, system, user, tools, toolbox, validate, max_steps, max_tokens):
    """Run an agent expected to return one JSON object; allow exactly one recorded repair."""
    text = run_agent(provider, budget, slog, system, user, tools, toolbox, max_steps, max_tokens)
    for attempt in (0, 1):
        try:
            obj = pk.extract_json(text)
            errs = validate(obj)
        except ValueError as ex:
            obj, errs = None, [str(ex)]
        if not errs:
            slog["output"], slog["repair_attempted"] = text[-2000:], attempt == 1
            return obj, []
        if attempt == 0:
            slog["first_errors"] = errs[:20]
            repair = user + "\n\nYour previous output was invalid:\n- " + "\n- ".join(errs[:15]) + \
                "\nReturn ONE corrected JSON object only.\nPrevious output:\n" + text[-3000:]
            text = run_agent(provider, budget, slog, system, repair, tools, toolbox, max_steps, max_tokens)
    slog["output"], slog["repair_attempted"] = text[-2000:], True
    return None, errs


def state_context(state):
    if not state["claims"]: return ""
    return f"\n\nCURRENT CANONICAL STATE (version {state['version']}):\n" + json.dumps({"claims": state["claims"], "evidence": state["evidence"]})


def merge_evidence(old, new):
    by_id = {e["evidence_id"]: e for e in old}
    by_id.update({e["evidence_id"]: e for e in new})
    return list(by_id.values())


def run_condition(task, condition, provider, budget, toolbox, max_steps, max_tokens, binary, workdir, log):
    state = {"version": 0, "claims": [], "evidence": []}
    log["stage_states"] = {}
    for stage in task["stages"]:
        toolbox.visible_filter = set(stage["visible"]) if stage["visible"] else None
        visible, inputs = set(toolbox.visible_files()), toolbox.pristine
        extra = lambda: toolbox.tool_outputs
        ctx = state_context(state)
        prompt = stage["prompt"] + ctx
        slog_list = log["stages"]
        all_tools, ro_tools = toolbox.schemas(), toolbox.schemas(readonly=True)
        full_val = lambda o: (["missing string 'answer'"] if not isinstance(o.get("answer"), str) else []) + \
            pk.validate_packet({k: o.get(k) for k in ("claims", "evidence") if k in o} | ({} if "evidence" in o else {"evidence": []}),
                               inputs, visible, extra()) + \
            (["unknown top-level keys"] if set(o) - {"answer", "claims", "evidence"} else [])
        if condition == "single_agent_tool_loop":
            slog = {"name": f"{stage['id']}:single", "calls": []}; slog_list.append(slog)
            system = ("Solve the task using the tools. Preserve uncertainty and cite evidence.\n" + POLICY +
                      f"\nReply with ONE JSON object: {{\"answer\":\"<prose>\",\"claims\":[{CLAIM_SHAPE}],\"evidence\":[{EVIDENCE_SHAPE}]}}. "
                      "List ALL evidence records you rely on, including carried-over ones. No other keys.")
            obj, errs = structured(provider, budget, slog, system, prompt, all_tools, toolbox, full_val, max_steps, max_tokens)
            if obj is None: log["status"], log["invalid_output"] = "invalid_output", errs; return state
            final = {"answer": obj["answer"], "claims": obj["claims"], "evidence": obj.get("evidence", [])}
        else:
            splan = {"name": f"{stage['id']}:planner", "calls": []}; slog_list.append(splan)
            plan = run_agent(provider, budget, splan, "Decompose the task into an execution plan. Do not solve it.", prompt, [], toolbox, 1, max_tokens)
            splan["output"] = plan[-2000:]
            sexp = {"name": f"{stage['id']}:explorer", "calls": []}; slog_list.append(sexp)
            esys = ("Investigate the task using the plan and the tools. Distinguish facts, assumptions, unknowns.\n" + POLICY +
                    f"\nReply with ONE JSON object and no reasoning narrative: {{\"claims\":[{CLAIM_SHAPE}],\"evidence\":[{EVIDENCE_SHAPE}]}}. "
                    "List ALL evidence records you rely on, including carried-over ones. No other keys.")
            pkt, errs = structured(provider, budget, sexp, esys, prompt + "\nPLAN:\n" + plan, all_tools, toolbox,
                                   lambda o: pk.validate_packet(o, inputs, visible, extra()), max_steps, max_tokens)
            if pkt is None: log["status"], log["invalid_output"] = "invalid_output", errs; return state
            canon = pk.canonical(pkt)
            sver = {"name": f"{stage['id']}:verifier", "calls": [], "input_chars": 0}; slog_list.append(sver)
            vuser = "Task: " + stage["prompt"] + "\nClaim/evidence packet (typed; the explorer's reasoning is withheld):\n" + json.dumps(canon)
            sver["input_chars"] = len(vuser)
            vsys = ("Independently verify each claim using the packet and, where needed, the tools (re-read sources, re-run tests). Identify unsupported "
                    "claims, misgraded evidence, and shared-origin dependencies. Do not trust a claim because it is stated.\n"
                    "Reply with ONE JSON object: {\"verdicts\":[{\"claim_id\":\"C1\",\"verdict\":\"supported|unsupported|contradicted|undetermined\",\"reason\":\"<=300 chars\"}],\"notes\":\"<=600 chars\"}")
            vobj, _ = structured(provider, budget, sver, vsys, vuser, ro_tools, toolbox, lambda o: [] if isinstance(o.get("verdicts"), list) else ["missing verdicts list"], max_steps, max_tokens)
            vobj = vobj or {"verdicts": [], "parse_error": True}
            sfin = {"name": f"{stage['id']}:final", "calls": []}; slog_list.append(sfin)
            fsys = ("Produce the final answer. Incorporate verification findings and retain unresolved uncertainty. Do not rename claim_ids; update statuses only as the evidence supports.\n"
                    f"Reply with ONE JSON object: {{\"answer\":\"<prose>\",\"claims\":[{CLAIM_SHAPE}]}}. No other keys.")
            fuser = "Task: " + stage["prompt"] + "\nPacket:\n" + json.dumps(canon) + "\nVerification:\n" + json.dumps(vobj)
            def fval(o, canon=canon):
                errs = [] if isinstance(o.get("answer"), str) else ["missing string 'answer'"]
                errs += [f"unknown top-level keys" ] if set(o) - {"answer", "claims"} else []
                return errs + pk.validate_packet({"claims": o.get("claims"), "evidence": canon["evidence"]}, inputs, visible, extra())
            fobj, errs = structured(provider, budget, sfin, fsys, fuser, [], toolbox, fval, max_steps, max_tokens)
            if fobj is None: log["status"], log["invalid_output"] = "invalid_output", errs; return state
            final = {"answer": fobj["answer"], "claims": fobj["claims"], "evidence": canon["evidence"]}
        state = {"version": state["version"] + 1, "claims": final["claims"],
                 "evidence": merge_evidence(state["evidence"], final["evidence"])}
        arb = pk.arbitrate({"claims": state["claims"], "evidence": state["evidence"]}, binary, workdir)
        log["stage_states"][stage["id"]] = {"version": state["version"], "answer": final["answer"], "claims": state["claims"],
                                            "evidence": state["evidence"], "arbitrated": arb}
    return state


def run_one(task, condition, provider, outdir, max_total_tokens=200_000, wall_clock_seconds=900,
            binary=None, max_steps=12, max_tokens=1800, clock=time.time):
    outdir = pathlib.Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="neuromesh-run-"))
    inputs_dir = ROOT / task["input_dir"]
    toolbox = ToolBox(inputs_dir, work, allow_tests=task["tools"]["allow_tests"], allow_write=task["tools"]["allow_write"])
    budget = RunBudget(max_total_tokens, wall_clock_seconds, clock)
    log = {"task_id": task["id"], "condition": condition, "model": getattr(provider, "model", "?"),
           "started_at": time.time(), "status": "completed", "stages": []}
    try:
        run_condition(task, condition, provider, budget, toolbox, max_steps, max_tokens,
                      binary if binary is not None else ROOT / "bin" / "neuromesh", work, log)
    except BudgetStop as ex:
        log["status"] = ex.args[0]
    except ProviderError as ex:
        log["status"], log["failure"] = "provider_failed", {"error": str(ex), "attempts": ex.attempts}
    log["budget"] = budget.report()
    log["tool_calls"] = toolbox.calls
    log["retries"] = sum(max(0, len(c.get("attempts", [])) - 1) for s in log["stages"] for c in s["calls"])
    if task["tools"]["allow_write"]:
        dest = outdir / "workspaces" / f"{task['id']}__{condition}"
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(toolbox.root / "repo", dest / "repo", ignore=shutil.ignore_patterns("__pycache__"))
        log["workspace"] = str(dest)
    log["finished_at"] = time.time()
    path = outdir / f"{task['id']}__{condition}.json"
    path.write_text(json.dumps(log, indent=2))
    shutil.rmtree(work, ignore_errors=True)
    return path, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", choices=CONDITIONS, required=True)
    ap.add_argument("--task", default="all")
    ap.add_argument("--out", default=str(ROOT / "eval" / "runs"))
    ap.add_argument("--max-total-tokens", type=int, default=200_000)
    ap.add_argument("--wall-clock-seconds", type=int, default=900)
    ap.add_argument("--binary", default=str(ROOT / "bin" / "neuromesh"))
    args = ap.parse_args()
    data = json.loads((ROOT / "spec" / "eval-set.json").read_text())
    provider = OpenAICompatible()
    for task in data["tasks"]:
        if args.task in ("all", task["id"]):
            path, log = run_one(task, args.condition, provider, args.out, args.max_total_tokens, args.wall_clock_seconds, args.binary)
            print(path, log["status"])


if __name__ == "__main__":
    main()
