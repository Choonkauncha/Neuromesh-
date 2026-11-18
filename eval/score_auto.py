#!/usr/bin/env python3
"""Deterministic checks only. Never fabricates rubric scores.

Subjective rubric dimensions (calibration, explanation quality, ...) remain evaluator-scored.
"""
import difflib, json, pathlib, re, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEP = "independent_origin"


def find_claim(claims, match, not_match=None, exclude_ids=()):
    for c in claims:
        s = c["statement"]
        if c["claim_id"] in exclude_ids: continue
        if re.search(match, s, re.I) and not (not_match and re.search(not_match, s, re.I)):
            return c
    return None


def status_check(claim, arbitrated, expected):
    if claim is None:
        return {"found": False, "expected": expected}
    arb = (arbitrated or {}).get(claim["claim_id"])
    return {"found": True, "claim_id": claim["claim_id"], "expected": expected, "model_status": claim["status"],
            "arbitrated_status": arb, "model_ok": claim["status"] == expected,
            "arbitrated_ok": None if arb is None else arb == expected,
            "overclaim": claim["status"] == "supported" and arb is not None and arb != "supported"}


def score_research(log, gold):
    st = log["stage_states"].get("s1")
    if not st: return {"error": "no completed stage"}
    out = {"claims": [], "provenance": [], "grades": []}
    for exp in gold["claims_expected"]:
        c = find_claim(st["claims"], exp["match"], exp.get("not_match"))
        out["claims"].append(status_check(c, st["arbitrated"], exp["status"]))
    for grp in gold["origin_groups"]:
        for f in grp["must_not_be_independent"]:
            entries = [e for e in st["evidence"] if e["source_file"] == f]
            out["provenance"].append({"file": f, "cited": bool(entries),
                                      "ok": bool(entries) and all(e["independence_group"] != INDEP for e in entries)})
    for f, g in gold["required_grade"].items():
        entries = [e for e in st["evidence"] if e["source_file"] == f]
        out["grades"].append({"file": f, "cited": bool(entries), "ok": bool(entries) and all(e["grade"] == g for e in entries)})
    out["distinct_independent_origin_items_claimed"] = sum(1 for e in st["evidence"] if e["independence_group"] == INDEP)
    out["evaluator_scored"] = ["conflict_handling", "calibration", "most of claim_accuracy"]
    return out


def run_tests(repo):
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=repo,
                       capture_output=True, text=True, timeout=60, env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"})
    return r.returncode == 0, (r.stdout + r.stderr)[-600:]


def score_debug(log, gold_dir):
    if "workspace" not in log: return {"error": "no workspace recorded", "status": log["status"]}
    orig = ROOT / "spec/tasks/multi_step_debugging-01/inputs/repo"
    meta = json.loads((gold_dir / "meta.json").read_text())
    tmp = pathlib.Path(tempfile.mkdtemp()); repo = tmp / "repo"
    shutil.copytree(pathlib.Path(log["workspace"]) / "repo", repo, ignore=shutil.ignore_patterns("__pycache__"))
    tests_modified = any((repo / "tests" / p.name).read_text() != p.read_text() for p in (orig / "tests").glob("*.py")
                         if (repo / "tests" / p.name).exists()) or \
        any(not (orig / "tests" / p.name).exists() for p in (repo / "tests").glob("*.py"))
    changed, files = 0, []
    for p in sorted((repo / "ledger").glob("*.py")):
        a = (orig / "ledger" / p.name).read_text().splitlines(); b = p.read_text().splitlines()
        d = [l for l in difflib.unified_diff(a, b, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        if d: files.append(f"ledger/{p.name}"); changed += len(d)
    # evaluate against pristine tests + hidden tests
    shutil.rmtree(repo / "tests"); shutil.copytree(orig / "tests", repo / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    visible_ok, _ = run_tests(repo)
    shutil.copy(gold_dir / "hidden_tests.py", repo / "tests" / "test_hidden.py")
    all_ok, tail = run_tests(repo)
    shutil.rmtree(tmp, ignore_errors=True)
    st = log["stage_states"].get("s1", {})
    text = " ".join(c["statement"] for c in st.get("claims", [])).lower() + " " + st.get("answer", "").lower()
    return {"visible_tests_pass": visible_ok, "hidden_tests_pass": all_ok, "tests_modified": tests_modified,
            "files_changed": files, "changed_lines": changed, "reference_changed_lines": meta["reference_changed_lines"],
            "touched_distractor": meta["distractor_file"] in files,
            "named_float_truncation_cause": bool(re.search(r"float|truncat|binary|floating", text)),
            "named_negative_floor_cause": bool(re.search(r"negative|floor|//|divmod|modulo|sign", text)),
            "evaluator_scored": ["test_quality", "risk_reporting", "explanation"]}


def score_stateful(log, gold):
    s1, s2 = log["stage_states"].get("stage1"), log["stage_states"].get("stage2")
    out = {"stage1": None, "stage2": None}
    if s1:
        c = find_claim(s1["claims"], gold["stage1_match"])
        out["stage1"] = status_check(c, s1["arbitrated"], gold["stage1_status"])
    if s1 and s2 and out["stage1"] and out["stage1"]["found"]:
        old_id = out["stage1"]["claim_id"]
        retained = next((c for c in s2["claims"] if c["claim_id"] == old_id), None)
        new = find_claim(s2["claims"], gold["stage2_new_match"], exclude_ids={old_id})
        out["stage2"] = {"old_claim_retained": retained is not None,
                         "old_claim": status_check(retained, s2["arbitrated"], gold["stage2_retained_status"]),
                         "new_claim": status_check(new, s2["arbitrated"], gold["stage2_new_status"]),
                         "new_claim_supersedes_old": bool(new and old_id in new.get("supersedes", [])),
                         "state_versions": [s1["version"], s2["version"]],
                         "old_evidence_carried_over": {e["evidence_id"] for e in s1["evidence"]} <= {e["evidence_id"] for e in s2["evidence"]}}
    out["evaluator_scored"] = ["revision_traceability explanation", "uncertainty"]
    return out


def score_log(log_path):
    log = json.loads(pathlib.Path(log_path).read_text())
    base = {"task_id": log["task_id"], "condition": log["condition"], "run_status": log["status"],
            "budget": log.get("budget"), "retries": log.get("retries")}
    if not log.get("stage_states") and "workspace" not in log:
        return {**base, "auto_checks": {"error": "run produced no scorable output"}}
    tid = log["task_id"]
    if tid.startswith("research"):
        checks = score_research(log, json.loads((ROOT / "spec/gold/research-conflicting-sources-01.json").read_text()))
    elif tid.startswith("multi_step_debugging"):
        checks = score_debug(log, ROOT / "spec/gold/multi_step_debugging-01")
    else:
        checks = score_stateful(log, json.loads((ROOT / "spec/gold/stateful_research-update-01.json").read_text()))
    return {**base, "auto_checks": checks}


if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(json.dumps(score_log(path), indent=2))
