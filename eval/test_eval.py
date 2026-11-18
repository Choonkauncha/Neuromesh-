"""Harness tests driven by scripted models. No network, no API key."""
import json, pathlib, sys, tempfile, unittest, urllib.error
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import harness, packet as pk, score_auto
import run_baselines
from budget_ledger import BudgetLedger, LedgerError
from providers import MockProvider, OpenAICompatible, ProviderError
from run_baselines import RecordingProvider
from toolbox import ToolBox

ROOT = harness.ROOT
BINARY = ROOT / "bin" / "neuromesh"
TASKS = {t["id"]: t for t in json.loads((ROOT / "spec/eval-set.json").read_text())["tasks"]}
RES, DBG, STA = "research-conflicting-sources-01", "multi_step_debugging-01", "stateful_research-update-01"


def ev(eid, f, st, grade, grp, ex, sup=(), con=(), pub=None, der=(), app=True, sby=None):
    d = {"evidence_id": eid, "source_file": f, "source_type": st, "grade": grade, "independence_group": grp,
         "excerpt": ex, "supports": list(sup), "contradicts": list(con), "derived_from": list(der), "applicability_checked": app}
    if pub: d["publisher"] = pub
    if sby: d["superseded_by"] = sby
    return d


def research_packet(overclaim=False):
    ev_ = [
        ev("e1a", "s1_release_notes_3.2.0.txt", "official_documentation", "b", "independent_origin",
           "addresses the memory leaks reported in issue #418 under typical workloads", ["C1"], pub="Quillstream project"),
        ev("e1b", "s1_release_notes_3.2.0.txt", "official_documentation", "b", "independent_origin",
           "Pool teardown is not triggered when idle_timeout is set to 0", [], ["C2"], pub="Quillstream project"),
        ev("e2", "s5_harbor_labs_benchmark.txt", "executed_code_or_test", "a", "independent_origin",
           "3.2.0, default settings: 0.4 MB/h", ["C1"], pub="Harbor Labs"),
        ev("e2b", "s5_harbor_labs_benchmark.txt", "executed_code_or_test", "a", "independent_origin",
           "3.2.0, idle_timeout=0: 36.2 MB/h", [], ["C2"], pub="Harbor Labs"),
        ev("e3", "s2_issue_418_thread.txt", "community_or_forum", "c", "independent_origin",
           "Confirmed idle_timeout=0 skips teardown.", [], ["C2"], pub="Quillstream GitHub issue"),
        ev("e4", "s3_devnotes_blog.txt", "reputable_secondary_source", "c",
           "independent_origin" if overclaim else "same_quoted_source",
           "Quillstream 3.2 fixes the connection-pool leak.", ["C1", "C2"], pub="DevNotes",
           der=[] if overclaim else ["e1a"]),
        ev("e5", "s4_weekly_newsletter.txt", "reputable_secondary_source", "c",
           "independent_origin" if overclaim else "derived_from_other_evidence",
           "DevNotes reports that Quillstream 3.2 fixes the pool leak", ["C2"], pub="Backend Weekly",
           der=[] if overclaim else ["e4"]),
        ev("e6", "s6_forum_post.txt", "community_or_forum", "d" if not overclaim else "c", "independent_origin",
           "yeah 3.2 totally fixed it for me. no more leaks.", ["C2"], pub="forum"),
        ev("e7", "s7_harbor_conference_slide.txt", "reputable_secondary_source", "c",
           "independent_origin" if overclaim else "same_underlying_dataset",
           "3.1.4: 38 MB/h -> 3.2.0: 0.4 MB/h", ["C1"], pub="Harbor Labs slides", der=[] if overclaim else ["e2"]),
    ]
    c2_status = "supported" if overclaim else "rejected"
    claims = [{"claim_id": "C1", "statement": "Quillstream 3.2.0 fixes the pool leak under default configuration", "status": "supported"},
              {"claim_id": "C2", "statement": "Quillstream 3.2.0 fixes the leak in every configuration including idle_timeout=0", "status": c2_status}]
    return {"claims": claims, "evidence": ev_}


def msg(text=None, tool=None):
    if tool:
        return {"role": "assistant", "content": None, "tool_calls": [{"id": "t1", "type": "function",
                "function": {"name": tool[0], "arguments": json.dumps(tool[1])}}]}
    return {"role": "assistant", "content": text}


def role_of(messages):
    s = messages[0]["content"]
    for key, name in [("Decompose", "planner"), ("Investigate the task", "explorer"), ("Independently verify", "verifier"),
                      ("Produce the final answer", "final"), ("Solve the task", "single")]:
        if key in s: return name


def last_is_tool(messages): return messages[-1]["role"] == "tool"


def scripted(pkt, canary="SECRET_NARRATIVE_CANARY", explorer_extra=None):
    def fn(messages, tools, n):
        r = role_of(messages)
        if r == "planner": return msg("1. read sources 2. grade 3. report")
        if r in ("explorer", "single"):
            if not last_is_tool(messages) and "invalid" not in messages[1]["content"]:
                return msg(tool=("list_files", {}))
            body = dict(pkt)
            if explorer_extra: body.update(explorer_extra)
            if r == "single": body = {"answer": "see claims", **pkt}
            return msg(f"{canary}: I reasoned privately about X.\n```json\n{json.dumps(body)}\n```")
        if r == "verifier": return msg(json.dumps({"verdicts": [{"claim_id": "C1", "verdict": "supported", "reason": "ok"}]}))
        if r == "final":
            return msg(json.dumps({"answer": "C1 holds by default config; C2 is contradicted.", "claims": pkt["claims"]}))
    return MockProvider(fn)


def run(task_id, cond, provider, **kw):
    out = tempfile.mkdtemp()
    return harness.run_one(TASKS[task_id], cond, provider, out, binary=BINARY, **kw)


need_bin = unittest.skipUnless(BINARY.exists(), "build bin/neuromesh first")


class ResearchTests(unittest.TestCase):
    @need_bin
    def test_good_run_both_conditions_score_clean(self):
        for cond in harness.CONDITIONS:
            path, log = run(RES, cond, scripted(research_packet()))
            self.assertEqual(log["status"], "completed", cond)
            sc = score_auto.score_log(path)["auto_checks"]
            self.assertTrue(all(c["model_ok"] and c["arbitrated_ok"] for c in sc["claims"]), (cond, sc["claims"]))
            self.assertTrue(all(p["ok"] for p in sc["provenance"]) and all(g["ok"] for g in sc["grades"]))
            self.assertFalse(any(c["overclaim"] for c in sc["claims"]))

    @need_bin
    def test_majority_vote_model_is_caught_by_arbitration(self):
        path, log = run(RES, "single_agent_tool_loop", scripted(research_packet(overclaim=True)))
        sc = score_auto.score_log(path)["auto_checks"]
        c2 = sc["claims"][1]
        self.assertEqual(c2["model_status"], "supported")
        # Mislabelled derived items count as original support, so strong contradiction
        # leaves the claim disputed rather than rejected; either way it is not supported.
        self.assertEqual(c2["arbitrated_status"], "disputed")
        self.assertTrue(c2["overclaim"] and not c2["model_ok"])
        self.assertFalse(all(p["ok"] for p in sc["provenance"]))

    def test_verifier_never_sees_explorer_narrative(self):
        prov = scripted(research_packet())
        run(RES, "sequential_planner_explorer_verifier", prov)
        ver = [s for s in prov.seen if role_of(s["messages"]) == "verifier"]
        self.assertTrue(ver)
        blob = json.dumps(ver[0]["messages"])
        self.assertNotIn("SECRET_NARRATIVE_CANARY", blob)
        self.assertNotIn("reasoned privately", blob)
        self.assertNotIn("1. read sources", blob)  # planner text withheld too

    def test_smuggled_reasoning_key_triggers_repair_then_invalid(self):
        prov = scripted(research_packet(), explorer_extra={"reasoning": "my chain of thought"})
        _, log = run(RES, "sequential_planner_explorer_verifier", prov)
        self.assertEqual(log["status"], "invalid_output")
        self.assertTrue(any("unknown top-level keys" in e for e in log["invalid_output"]))
        exp = [s for s in log["stages"] if s["name"].endswith("explorer")][0]
        self.assertTrue(exp["repair_attempted"])
        self.assertFalse(any(role_of(s["messages"]) == "verifier" for s in prov.seen))
        # exactly one repair: tool step + invalid answer + repaired answer, then stop
        self.assertEqual(len(exp["calls"]), 3)

    def test_narrative_cannot_ride_inside_evidence_or_claim_records(self):
        inputs, vis = ROOT / TASKS[RES]["input_dir"], {"s1_release_notes_3.2.0.txt"}
        for where in ("evidence", "claims"):
            bad = research_packet()
            bad["evidence"] = bad["evidence"][:1]
            bad["evidence"][0]["supports"] = ["C1"]
            bad[where][0]["reasoning"] = "private chain of thought"
            errs = pk.validate_packet(bad, inputs, vis)
            self.assertTrue(any("unknown keys" in x for x in errs), (where, errs))
        ok = research_packet(); ok["evidence"] = ok["evidence"][:1]
        self.assertEqual(pk.validate_packet(ok, inputs, vis), [])

    def test_fabricated_quote_is_rejected(self):
        bad = research_packet(); bad["evidence"][0]["excerpt"] = "The maintainers guarantee a complete fix in every setup."
        errs = pk.validate_packet(bad, ROOT / TASKS[RES]["input_dir"], {e["source_file"] for e in bad["evidence"]})
        self.assertTrue(any("not a verbatim quote" in e for e in errs))

    def test_repair_succeeds_when_model_fixes_output(self):
        good, bad = research_packet(), research_packet()
        bad["evidence"][0]["excerpt"] = "made up text that is not in the source"
        def fn(messages, tools, n):
            r = role_of(messages)
            if r == "single":
                body = good if "invalid" in messages[1]["content"] else bad
                return msg(json.dumps({"answer": "a", **body}))
        _, log = run(RES, "single_agent_tool_loop", MockProvider(fn))
        self.assertEqual(log["status"], "completed")
        self.assertTrue(log["stages"][0]["repair_attempted"])


class DebugTests(unittest.TestCase):
    def fixed(self, name):
        return (ROOT / "spec/gold/multi_step_debugging-01/fixed/ledger" / name).read_text()

    def agent(self, apply_fix):
        def fn(messages, tools, n):
            if role_of(messages) != "single": return None
            steps = sum(1 for m in messages if m["role"] == "tool")
            plan = [("read_file", {"path": "repo/ledger/money.py"}), ("read_file", {"path": "repo/ledger/report.py"})]
            if apply_fix:
                plan += [("write_file", {"path": "repo/ledger/money.py", "content": self.fixed("money.py")}),
                         ("write_file", {"path": "repo/ledger/report.py", "content": self.fixed("report.py")})]
            plan += [("run_tests", {})]
            if steps < len(plan): return msg(tool=plan[steps])
            c = [{"claim_id": "C1", "statement": "float truncation in parse_amount drops a cent", "status": "supported"},
                 {"claim_id": "C2", "statement": "format_cents floor division breaks negative amounts", "status": "supported"}]
            e = [ev("e1", "repo/ledger/money.py", "primary_document", "a", "independent_origin", "int(float(cleaned) * 100)", ["C1"]),
                 ev("e2", "repo/ledger/report.py", "primary_document", "a", "independent_origin", "cents // 100", ["C2"]),
                 ev("e3", "tool:run_tests", "executed_code_or_test", "a", "independent_origin", "Ran 8 tests", ["C1", "C2"])]
            return msg(json.dumps({"answer": "fixed", "claims": c, "evidence": e}))
        return MockProvider(fn)

    def test_correct_fix_passes_hidden_tests_and_stays_minimal(self):
        path, log = run(DBG, "single_agent_tool_loop", self.agent(True))
        self.assertEqual(log["status"], "completed")
        sc = score_auto.score_log(path)["auto_checks"]
        self.assertTrue(sc["visible_tests_pass"] and sc["hidden_tests_pass"])
        self.assertFalse(sc["tests_modified"] or sc["touched_distractor"])
        self.assertLessEqual(sc["changed_lines"], 12)
        self.assertEqual(sorted(sc["files_changed"]), ["ledger/money.py", "ledger/report.py"])

    def test_no_fix_fails_hidden_tests(self):
        path, _ = run(DBG, "single_agent_tool_loop", self.agent(False))
        sc = score_auto.score_log(path)["auto_checks"]
        self.assertFalse(sc["visible_tests_pass"] or sc["hidden_tests_pass"])

    def test_test_tampering_is_detected(self):
        tb = ToolBox(ROOT / TASKS[DBG]["input_dir"], tempfile.mkdtemp(), allow_tests=True, allow_write=True)
        tb.call("write_file", {"path": "repo/tests/test_money.py", "content": "import unittest\n"})
        # Editing tests is permitted in the sandbox, but scoring always runs pristine tests,
        # so tampering cannot turn a failing fix into a pass.
        from shutil import copytree
        work = pathlib.Path(tempfile.mkdtemp()); copytree(tb.root / "repo", work / "repo")
        log = {"task_id": DBG, "condition": "x", "status": "completed", "workspace": str(work), "stage_states": {}}
        lp = work / "log.json"; lp.write_text(json.dumps(log))
        sc = score_auto.score_log(lp)["auto_checks"]
        self.assertTrue(sc["tests_modified"])
        self.assertFalse(sc["visible_tests_pass"])


class StatefulTests(unittest.TestCase):
    @need_bin
    def test_two_stage_revision_with_supersession(self):
        s1 = {"claims": [{"claim_id": "C1", "statement": "X900 1 TB endurance is 600 TBW", "status": "supported"}],
              "evidence": [ev("d1", "stage1_datasheet_v1.txt", "official_documentation", "b", "independent_origin",
                              "Endurance rating: 600 TBW", ["C1"], pub="Aurelia"),
                           ev("r1", "stage1_review_site.txt", "reputable_secondary_source", "c", "same_quoted_source",
                              "Aurelia rates the X900 for 600 TBW", ["C1"], pub="DriveReviewer", der=["d1"])]}
        s2 = {"claims": [{"claim_id": "C1", "statement": "X900 1 TB endurance is 600 TBW", "status": "rejected"},
                         {"claim_id": "C2", "statement": "X900 1 TB endurance is 300 TBW", "status": "supported", "supersedes": ["C1"]}],
              "evidence": s1["evidence"][:1] and [dict(s1["evidence"][0], superseded_by="x1"), s1["evidence"][1]] + [
                  ev("x1", "stage2_datasheet_errata.txt", "official_documentation", "a", "independent_origin",
                     "X900 1 TB: 300 TBW", ["C2"], ["C1"], pub="Aurelia"),
                  ev("w1", "stage2_wear_test.txt", "executed_code_or_test", "a", "independent_origin",
                     "Both 1 TB units reached the SMART wear threshold at 312 TB and 318 TB written.", ["C2"], ["C1"], pub="StorageLab")]}
        prompts = []
        def fn(messages, tools, n):
            if role_of(messages) != "single": return None
            if not last_is_tool(messages) and "invalid" not in messages[1]["content"]: return msg(tool=("list_files", {}))
            prompts.append(messages[1]["content"])
            stage2 = "Stage 2 of 2" in messages[1]["content"]
            return msg(json.dumps({"answer": "updated" if stage2 else "initial", **(s2 if stage2 else s1)}))
        path, log = run(STA, "single_agent_tool_loop", MockProvider(fn))
        self.assertEqual(log["status"], "completed", log.get("invalid_output"))
        self.assertIn("CURRENT CANONICAL STATE (version 1)", prompts[-1])
        sc = score_auto.score_log(path)["auto_checks"]
        self.assertTrue(sc["stage1"]["model_ok"] and sc["stage1"]["arbitrated_ok"])
        st2 = sc["stage2"]
        self.assertTrue(st2["old_claim_retained"] and st2["new_claim_supersedes_old"] and st2["old_evidence_carried_over"])
        self.assertTrue(st2["old_claim"]["arbitrated_ok"] and st2["new_claim"]["arbitrated_ok"], st2)

    def test_stage_two_files_hidden_during_stage_one(self):
        tb = ToolBox(ROOT / TASKS[STA]["input_dir"], tempfile.mkdtemp(), visible=TASKS[STA]["stages"][0]["visible"])
        self.assertNotIn("stage2", tb.call("list_files", {}))
        self.assertTrue(tb.call("read_file", {"path": "stage2_datasheet_errata.txt"}).startswith("ERROR"))


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.tb = ToolBox(ROOT / TASKS[DBG]["input_dir"], tempfile.mkdtemp(), allow_tests=True, allow_write=True)

    def test_cannot_read_gold_or_escape(self):
        for p in ["../../../../spec/gold/multi_step_debugging-01/hidden_tests.py", "/etc/passwd", "../gold"]:
            self.assertTrue(self.tb.call("read_file", {"path": p}).startswith("ERROR"), p)
        self.assertNotIn("gold", self.tb.call("list_files", {}))
        self.assertNotIn("hidden", self.tb.call("search_text", {"pattern": "hidden"}).lower().replace("hidden tests", ""))

    def test_writes_confined_to_repo(self):
        self.assertTrue(self.tb.call("write_file", {"path": "logs/failure.log", "content": "x"}).startswith("ERROR"))
        self.assertTrue(self.tb.call("write_file", {"path": "repo/../logs/x", "content": "x"}).startswith("ERROR"))

    def test_verifier_schema_is_read_only(self):
        names = lambda ss: {s["function"]["name"] for s in ss}
        self.assertIn("write_file", names(self.tb.schemas()))
        self.assertNotIn("write_file", names(self.tb.schemas(readonly=True)))


class BudgetAndFailureTests(unittest.TestCase):
    def test_token_cap_stops_run_and_is_recorded(self):
        prov = scripted(research_packet())
        _, log = run(RES, "sequential_planner_explorer_verifier", prov, max_total_tokens=250)
        self.assertEqual(log["status"], "token_cap")
        self.assertLessEqual(log["budget"]["calls"], 3)
        self.assertGreaterEqual(log["budget"]["tokens_used"], 250)

    def test_wall_clock_cap(self):
        t = [0.0]
        def clock(): t[0] += 400; return t[0]
        _, log = run(RES, "single_agent_tool_loop", scripted(research_packet()), wall_clock_seconds=500, clock=clock)
        self.assertEqual(log["status"], "wall_clock_cap")

    def test_missing_usage_is_estimated_and_flagged(self):
        def fn(messages, tools, n): return msg(json.dumps({"answer": "a", **research_packet()})), {}
        _, log = run(RES, "single_agent_tool_loop", MockProvider(fn))
        self.assertTrue(log["budget"]["usage_estimated"])

    def test_retries_are_recorded_then_succeed(self):
        calls, sleeps = [], []
        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return json.dumps({"choices": [{"message": {"role": "assistant", "content": "hi"}}], "usage": {"total_tokens": 5}}).encode()
        def fake(req, timeout=0):
            calls.append(1)
            if len(calls) <= 2: raise urllib.error.HTTPError("u", 429, "rate", {}, None)
            return R()
        with mock.patch("urllib.request.urlopen", fake):
            r = OpenAICompatible("http://x", "k", "m", sleep=sleeps.append).chat([{"role": "user", "content": "q"}])
        self.assertEqual([a["ok"] for a in r["attempts"]], [False, False, True])
        self.assertEqual(sleeps, [2, 4])

    def test_non_retryable_and_exhausted_failures_do_not_crash_the_run(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("u", 401, "no", {}, None)):
            with self.assertRaises(ProviderError) as cm:
                OpenAICompatible("http://x", "k", "m", sleep=lambda s: None).chat([])
            self.assertEqual(len(cm.exception.attempts), 1)
        class Boom:
            model = "boom"
            def chat(self, *a, **k): raise ProviderError("retries exhausted", [{"attempt": 1, "ok": False, "error": "HTTP 503"}])
        path, log = run(RES, "single_agent_tool_loop", Boom())
        self.assertEqual(log["status"], "provider_failed")
        self.assertTrue(path.exists())
        self.assertEqual(log["failure"]["attempts"][0]["error"], "HTTP 503")


class LedgerAndRunnerTests(unittest.TestCase):
    def test_ledger_round_trip_and_totals(self):
        led = BudgetLedger("run-1", RES, "single_agent_tool_loop", "gemini-2.5-flash", 200_000, 100, 900)
        led.reserve(4000, 1, "dispatch")
        led.record_actual(1500, 1, "provider_call")
        led.release(2500, 0, "unused_reservation")
        self.assertEqual(led.used_tokens, 1500)
        self.assertEqual(led.reserved_tokens, 1500)
        self.assertEqual(led.remaining_tokens, 198_500)
        self.assertFalse(led.usage_estimated)
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "ledger.json"
            led.write(p)
            back = BudgetLedger.read(p)
        self.assertEqual(back.run_id, "run-1")
        self.assertEqual(back.used_tokens, 1500)
        self.assertEqual([e["kind"] for e in back.entries], ["reserve", "actual", "release"])

    def test_ledger_rejects_bad_schema(self):
        led = BudgetLedger("r", "t", "c", "m", 100, None, 60)
        with self.assertRaises(LedgerError):
            led.reserve(-1)
        with self.assertRaises(LedgerError):
            led._event("bogus", 1, 1, "x")
        bad = led.to_dict()
        bad["schema_version"] = 99
        with self.assertRaises(LedgerError):
            BudgetLedger.validate(bad)

    def test_from_harness_log_marks_estimated_remainder(self):
        log = {"task_id": RES, "condition": "single_agent_tool_loop", "model": "m",
               "status": "token_cap",
               "budget": {"tokens_used": 500, "token_cap": 400, "calls": 3,
                          "wall_seconds": 12.0, "wall_cap": 900, "usage_estimated": True},
               "stages": [{"calls": [{"usage": {"total_tokens": 100}}, {"usage": {}}]}]}
        led = BudgetLedger.from_harness_log(log, "run-9")
        self.assertEqual(led.used_tokens, 500)
        self.assertTrue(led.usage_estimated)
        self.assertEqual(led.entries[-1]["kind"], "stop")
        self.assertEqual(led.entries[-1]["reason"], "token_cap")

    def test_recording_provider_writes_full_transcript(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            rec = RecordingProvider(scripted(research_packet()), out / "transcript.jsonl")
            _, log = harness.run_one(TASKS[RES], "single_agent_tool_loop", rec, out, binary=BINARY)
            self.assertEqual(log["status"], "completed")
            lines = (out / "transcript.jsonl").read_text().splitlines()
            self.assertGreaterEqual(len(lines), 1)
            first = json.loads(lines[0])
            self.assertIn("request", first)
            self.assertIn("response", first)
            self.assertIn("messages", first["request"])
            self.assertIn("message", first["response"])

    def test_run_all_mock_no_clobber(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir, manifest = run_baselines.run_all(
                scripted(research_packet()), [TASKS[RES]], ["single_agent_tool_loop"],
                2, d, 200_000, 900, BINARY)
            self.assertEqual(len(manifest["runs"]), 2)
            self.assertTrue(all(r["status"] == "completed" for r in manifest["runs"]))
            reps = sorted(p for p in run_dir.iterdir() if p.is_dir())
            self.assertEqual(len(reps), 2)
            self.assertNotEqual(reps[0], reps[1])
            for rep in reps:
                self.assertTrue((rep / "transcript.jsonl").exists())
                self.assertTrue((rep / "budget-ledger.json").exists())
                self.assertTrue((rep / "scores.json").exists())
                self.assertTrue(BudgetLedger.read(rep / "budget-ledger.json"))
            self.assertTrue((run_dir / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
