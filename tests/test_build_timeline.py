import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "postmortem-timeline"
FILES = SKILL / "evals" / "files"
sys.path.insert(0, str(SKILL / "scripts"))

import build_timeline  # noqa: E402


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = build_timeline.main([str(item) for item in argv])
    return code, out.getvalue(), err.getvalue()


def run_json(argv):
    code, out, err = run_main(list(argv) + ["--json"])
    return code, (json.loads(out) if out else None), err


def refs(result):
    return [event["ref"] for event in result["timeline"]]


def codes(result, level=None):
    return [f["code"] for f in result["findings"] if level in (None, f["level"])]


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def jsonl(self, name, rows):
        return self.write(name, "".join(json.dumps(row) + "\n" for row in rows))


class TzTrapFixtureTests(unittest.TestCase):
    ARGS = ["--events", FILES / "tz-trap" / "alerts.jsonl", "--events", FILES / "tz-trap" / "deploys.csv",
            "--git-log", FILES / "tz-trap" / "git-log.txt", "--chat", FILES / "tz-trap" / "incident-channel.json"]
    TRUE_ORDER = [
        "git-log.txt:2", "deploys.csv:2", "deploys.csv:3", "git-log.txt:1", "alerts.jsonl:1",
        "alerts.jsonl:2", "alerts.jsonl:3", "incident-channel.json#/0", "incident-channel.json#/1",
        "incident-channel.json#/2", "incident-channel.json#/3", "deploys.csv:4", "deploys.csv:5",
        "alerts.jsonl:4", "incident-channel.json#/4", "incident-channel.json#/5", "alerts.jsonl:5"]

    def test_zoneless_deploy_times_block_and_are_not_placed(self):
        code, result, _ = run_json(self.ARGS)
        self.assertEqual(code, 1)
        self.assertEqual(codes(result, "error"), ["no-zone"])
        finding = result["findings"][0]
        self.assertEqual(finding["evidence"], ["deploys.csv:2", "deploys.csv:3", "deploys.csv:4", "deploys.csv:5"])
        self.assertIn("--assume-zone deploys=+HH:MM", finding["message"])
        self.assertEqual([e["ref"] for e in result["not_placed"]], finding["evidence"])
        self.assertFalse(any(ref.startswith("deploys.csv") for ref in refs(result)))
        self.assertEqual(result["summary"]["placed"], 13)
        self.assertTrue(result["summary"]["blocked"])

    def test_commits_are_ordered_by_utc_not_by_local_clock_text(self):
        _, result, _ = run_json(self.ARGS)
        order = refs(result)
        self.assertLess(order.index("git-log.txt:2"), order.index("git-log.txt:1"))
        self.assertEqual(result["timeline"][0]["utc"], "2026-03-14T08:52:05Z")

    def test_with_the_documented_offset_the_known_order_is_produced(self):
        code, result, _ = run_json(self.ARGS + ["--assume-zone", "deploys=+05:00"])
        self.assertEqual(code, 0)
        self.assertEqual(refs(result), self.TRUE_ORDER)
        self.assertEqual(codes(result), ["assumed-zone"])
        self.assertEqual(result["gaps"], [])
        deploy = result["timeline"][1]
        self.assertEqual(deploy["utc"], "2026-03-14T09:02:11Z")
        self.assertEqual((deploy["zone"], deploy["zone_detail"]), ("assumed", "+05:00"))
        durations = {(d["from"], d["to"]): d["seconds"] for d in result["durations"]}
        self.assertEqual(durations, {("detected", "acknowledged"): 165, ("detected", "mitigated"): 958,
                                     ("detected", "resolved"): 1678})

    def test_markdown_marks_assumed_zone_and_unplaced_events(self):
        _, out, _ = run_main(self.ARGS)
        self.assertIn("## Not placed", out)
        self.assertIn("| 2026-03-14 14:02:11 | deploys |", out)
        self.assertIn("Result: BLOCKED (1 error(s), 0 warning(s))", out)
        _, out, _ = run_main(self.ARGS + ["--assume-zone", "deploys=+05:00"])
        self.assertIn("| 2026-03-14 09:02:11 (zone assumed: +05:00) | deploys |", out)
        self.assertNotIn("## Not placed", out)
        self.assertIn("- detected to mitigated: 15m 58s (alerts.jsonl:2 to alerts.jsonl:4)", out)

    def test_roles_file_removes_names_and_user_ids(self):
        code, out, _ = run_main(self.ARGS + ["--assume-zone", "deploys=+05:00",
                                             "--roles", FILES / "tz-trap" / "roles.json"])
        self.assertEqual(code, 0)
        for name in ("rhea", "lindqvist", "tomas", "achterberg", "U07RHL4QX", "U03TMA9KD"):
            self.assertNotIn(name, out)
        self.assertIn("on-call engineer: Yes, roll back to v2.30.4.", out)
        self.assertIn("on-call engineer do you want a rollback?", out)
        self.assertNotIn("no-role", out)

    def test_argument_order_does_not_change_the_output(self):
        _, first, _ = run_main(self.ARGS)
        reordered = self.ARGS[6:8] + self.ARGS[2:4] + self.ARGS[4:6] + self.ARGS[0:2]
        _, second, _ = run_main(reordered)
        self.assertEqual(first, second)


class GapFixtureTests(unittest.TestCase):
    ARGS = ["--events", FILES / "unexplained-gap" / "alerts.csv",
            "--git-log", FILES / "unexplained-gap" / "git-log.txt",
            "--chat", FILES / "unexplained-gap" / "incident-channel.json"]

    def test_gap_inside_the_incident_window_is_reported_with_evidence(self):
        code, result, _ = run_json(self.ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(codes(result, "error"), [])
        self.assertEqual(codes(result), ["gap", "gap"])
        inside = [gap for gap in result["gaps"] if gap["in_incident_window"]]
        self.assertEqual(len(inside), 1)
        self.assertEqual(inside[0]["seconds"], 47 * 60 + 8)
        self.assertEqual(inside[0]["after_ref"], "incident-channel.json#/2")
        self.assertEqual(inside[0]["before_ref"], "incident-channel.json#/3")
        self.assertEqual(inside[0]["start_utc"], "2026-05-08T23:52:31Z")
        self.assertEqual(inside[0]["end_utc"], "2026-05-09T00:39:39Z")

    def test_gap_before_detection_is_outside_the_window(self):
        _, result, _ = run_json(self.ARGS)
        outside = [gap for gap in result["gaps"] if gap["in_incident_window"] is False]
        self.assertEqual(len(outside), 1)
        self.assertEqual(outside[0]["seconds"], 2 * 3600 + 30 * 60 + 23)
        self.assertEqual((outside[0]["after_ref"], outside[0]["before_ref"]), ("git-log.txt:1", "alerts.csv:2"))

    def test_markdown_has_a_gap_row_between_the_two_events(self):
        _, out, _ = run_main(self.ARGS)
        lines = out.splitlines()
        row = [i for i, line in enumerate(lines) if "GAP: no events from any source for 47m 08s" in line]
        self.assertEqual(len(row), 1)
        self.assertIn("(inside the incident window)", lines[row[0]])
        self.assertIn("incident-channel.json#/2 to incident-channel.json#/3", lines[row[0]])
        self.assertIn("incident-channel.json#/2 |", lines[row[0] - 1])
        self.assertIn("incident-channel.json#/3 |", lines[row[0] + 1])

    def test_offsets_cross_midnight_and_durations_follow(self):
        _, result, _ = run_json(self.ARGS)
        self.assertEqual(result["milestones"]["detected"]["utc"], "2026-05-08T23:41:07Z")
        self.assertEqual(result["milestones"]["resolved"]["utc"], "2026-05-09T01:05:00Z")
        durations = {(d["from"], d["to"]): d["text"] for d in result["durations"]}
        self.assertEqual(durations[("detected", "resolved")], "1h 23m 53s")

    def test_fail_on_warning_makes_gaps_blocking(self):
        code, _, _ = run_main(self.ARGS + ["--fail-on", "warning"])
        self.assertEqual(code, 1)

    def test_wider_threshold_hides_only_the_shorter_gap(self):
        _, result, _ = run_json(self.ARGS + ["--gap-minutes", "60"])
        self.assertEqual([gap["seconds"] for gap in result["gaps"]], [9023])


class CleanFixtureTests(unittest.TestCase):
    ARGS = ["--events", FILES / "clean" / "events.jsonl", "--git-log", FILES / "clean" / "git-log.txt",
            "--chat", FILES / "clean" / "incident-channel.json"]

    def test_clean_bundle_has_no_findings(self):
        code, result, _ = run_json(self.ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["not_placed"], [])
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["summary"]["placed"], 11)
        code, _, _ = run_main(self.ARGS + ["--fail-on", "warning"])
        self.assertEqual(code, 0)

    def test_all_six_durations_are_computed(self):
        _, result, _ = run_json(self.ARGS)
        durations = {(d["from"], d["to"]): d["seconds"] for d in result["durations"]}
        self.assertEqual(durations, {
            ("started", "detected"): 165, ("detected", "acknowledged"): 98,
            ("detected", "mitigated"): 785, ("detected", "resolved"): 1535,
            ("started", "mitigated"): 950, ("started", "resolved"): 1700})

    def test_order(self):
        _, result, _ = run_json(self.ARGS)
        self.assertEqual(refs(result), [
            "git-log.txt:1", "events.jsonl:1", "events.jsonl:2", "events.jsonl:3", "events.jsonl:4",
            "incident-channel.json#/0", "incident-channel.json#/1", "events.jsonl:5", "events.jsonl:6",
            "incident-channel.json#/2", "events.jsonl:7"])


class MilestoneTests(TempDirCase):
    def events(self, rows):
        return self.jsonl("events.jsonl", [
            {"timestamp": stamp, "source": "monitor", "text": text, "tag": tag} for stamp, text, tag in rows])

    def test_tag_option_attaches_a_milestone_to_an_evidence_line(self):
        path = self.events([("2026-03-14T09:00:00Z", "alert", None), ("2026-03-14T09:04:10Z", "ok", None)])
        code, result, _ = run_json(["--events", path, "--tag", "detected=events.jsonl:1",
                                    "--tag", "Resolved=events.jsonl:2"])
        self.assertEqual(code, 0)
        self.assertEqual(result["durations"], [
            {"from": "detected", "to": "resolved", "seconds": 250, "text": "4m 10s", "reason": None}])
        self.assertEqual(result["milestones"]["resolved"], {"utc": "2026-03-14T09:04:10Z", "ref": "events.jsonl:2"})

    def test_tag_on_unknown_evidence_is_a_usage_error(self):
        path = self.events([("2026-03-14T09:00:00Z", "alert", None)])
        code, _, err = run_main(["--events", path, "--tag", "detected=events.jsonl:9"])
        self.assertEqual(code, 2)
        self.assertIn("events.jsonl:9", err)

    def test_duplicate_milestone_blocks_and_duration_is_not_computed(self):
        path = self.events([("2026-03-14T09:00:00Z", "alert", "detected"),
                            ("2026-03-14T09:01:00Z", "alert again", "detected"),
                            ("2026-03-14T09:05:00Z", "ok", "resolved")])
        code, result, _ = run_json(["--events", path])
        self.assertEqual(code, 1)
        self.assertEqual(codes(result, "error"), ["duplicate-milestone"])
        self.assertEqual(result["findings"][0]["evidence"], ["events.jsonl:1", "events.jsonl:2"])
        self.assertIsNone(result["durations"][0]["seconds"])
        self.assertIn("tagged on 2 events", result["durations"][0]["reason"])

    def test_milestones_out_of_order_block(self):
        path = self.events([("2026-03-14T09:10:00Z", "alert", "detected"),
                            ("2026-03-14T09:02:00Z", "ack", "acknowledged"),
                            ("2026-03-14T09:30:00Z", "ok", "resolved")])
        code, result, _ = run_json(["--events", path])
        self.assertEqual(code, 1)
        self.assertEqual(codes(result, "error"), ["milestone-order"])
        self.assertEqual(result["findings"][0]["evidence"], ["events.jsonl:1", "events.jsonl:2"])
        by_pair = {(d["from"], d["to"]): d for d in result["durations"]}
        self.assertIsNone(by_pair[("detected", "acknowledged")]["seconds"])
        self.assertIsNone(by_pair[("detected", "resolved")]["seconds"])

    def test_milestone_on_unplaced_event_gives_no_duration(self):
        path = self.events([("2026-03-14 09:00:00", "alert", "detected"), ("2026-03-14T09:05:00Z", "ok", "resolved")])
        code, result, _ = run_json(["--events", path])
        self.assertEqual(code, 1)
        self.assertIsNone(result["durations"][0]["seconds"])
        self.assertIn("not placed (events.jsonl:1)", result["durations"][0]["reason"])
        self.assertNotIn("detected", result["milestones"])

    def test_unknown_tag_warns(self):
        path = self.events([("2026-03-14T09:00:00Z", "alert", "detcted")])
        code, result, _ = run_json(["--events", path])
        self.assertEqual(code, 0)
        self.assertEqual(codes(result), ["unknown-tag"])

    def test_one_milestone_means_window_is_unknown(self):
        path = self.events([("2026-03-14T09:00:00Z", "alert", "detected"), ("2026-03-14T10:00:00Z", "later", None)])
        _, result, _ = run_json(["--events", path])
        self.assertIsNone(result["gaps"][0]["in_incident_window"])
        self.assertEqual(result["durations"], [])


class InputShapeTests(TempDirCase):
    def test_csv_epoch_and_minute_precision(self):
        path = self.write("log.csv", "Timestamp,Source,Text\n1773479610,pager,Paged\n2026-03-14 09:20Z,status,Posted update\n")
        code, out, _ = run_main(["--events", path])
        self.assertEqual(code, 0)
        self.assertIn("| 2026-03-14 09:13:30 | pager | Paged |  | log.csv:2 |", out)
        self.assertIn("| 2026-03-14 09:20 | status | Posted update |  | log.csv:3 |", out)

    def test_abbreviation_needs_zone_offset(self):
        path = self.jsonl("e.jsonl", [{"timestamp": "2026-03-14 14:32:00 IST", "source": "wiki", "text": "note"}])
        code, result, _ = run_json(["--events", path])
        self.assertEqual((code, codes(result)), (1, ["ambiguous-zone"]))
        self.assertIn("IST", result["findings"][0]["message"])
        code, result, _ = run_json(["--events", path, "--zone-offset", "IST=+05:30"])
        self.assertEqual((code, codes(result)), (0, ["assumed-zone"]))
        self.assertEqual(result["timeline"][0]["utc"], "2026-03-14T09:02:00Z")

    def test_bad_timestamp_is_a_finding_not_a_crash(self):
        path = self.jsonl("e.jsonl", [{"timestamp": "around lunch", "source": "wiki", "text": "note"},
                                      {"source": "wiki", "text": "no time"},
                                      {"timestamp": "2026-03-14T09:00:00Z", "source": "wiki", "text": "ok"}])
        code, result, _ = run_json(["--events", path])
        self.assertEqual(code, 1)
        self.assertEqual(codes(result), ["bad-timestamp"])
        self.assertEqual(result["findings"][0]["evidence"], ["e.jsonl:1", "e.jsonl:2"])
        self.assertEqual(refs(result), ["e.jsonl:3"])

    def test_chat_with_messages_object_and_content_key(self):
        path = self.write("chat.json", json.dumps({"messages": [
            {"timestamp": 1773479610, "content": "hello", "author": "kai"},
            {"ts": "1773479600.000100", "text": "first | piped\ntext"},
            {"text": "no time at all"}]}))
        code, result, _ = run_json(["--chat", "war-room=%s" % path])
        self.assertEqual(code, 1)
        self.assertEqual(refs(result), ["chat.json#/messages/1", "chat.json#/messages/0"])
        self.assertEqual(result["timeline"][1]["actor"], "kai")
        self.assertEqual(result["timeline"][0]["source"], "war-room")
        self.assertEqual(result["not_placed"][0]["ref"], "chat.json#/messages/2")
        _, out, _ = run_main(["--chat", path])
        self.assertIn("| chat | first \\| piped text |", out)

    def test_git_log_label_and_text(self):
        path = self.write("repo.txt", "\n0a1b2c3\t2026-03-14T10:00:00+01:00\tFix: handle\ttabs\n")
        _, result, _ = run_json(["--git-log", "billing=%s" % path])
        event = result["timeline"][0]
        self.assertEqual((event["source"], event["ref"], event["utc"]), ("billing", "repo.txt:2", "2026-03-14T09:00:00Z"))
        self.assertEqual(event["text"], "commit 0a1b2c3: Fix: handle\ttabs")

    def test_same_instant_keeps_file_order(self):
        path = self.jsonl("e.jsonl", [{"timestamp": "2026-03-14T09:00:00Z", "source": "s", "text": str(n)}
                                      for n in range(12)])
        _, result, _ = run_json(["--events", path])
        self.assertEqual(refs(result), ["e.jsonl:%d" % n for n in range(1, 13)])

    def test_long_text_is_cut_in_markdown_only(self):
        path = self.jsonl("e.jsonl", [{"timestamp": "2026-03-14T09:00:00Z", "source": "s", "text": "x" * 500}])
        _, out, _ = run_main(["--events", path])
        self.assertIn("x" * 200 + " [...]", out)
        self.assertNotIn("x" * 201, out)
        _, result, _ = run_json(["--events", path])
        self.assertEqual(len(result["timeline"][0]["text"]), 500)

    def test_roles_warn_about_actors_without_a_role(self):
        events = self.jsonl("e.jsonl", [
            {"timestamp": "2026-03-14T09:00:00Z", "source": "pager", "text": "ack", "actor": "kai.moreno"},
            {"timestamp": "2026-03-14T09:01:00Z", "source": "pager", "text": "kai.moreno paged ana.sorensen", "actor": "ana.sorensen"}])
        roles = self.write("roles.json", json.dumps({"kai.moreno": "on-call engineer"}))
        code, result, _ = run_json(["--events", events, "--roles", roles])
        self.assertEqual(code, 0)
        self.assertEqual(codes(result), ["no-role"])
        self.assertEqual(result["findings"][0]["evidence"], ["e.jsonl:2"])
        self.assertEqual(result["timeline"][0]["actor"], "on-call engineer")
        self.assertEqual(result["timeline"][1]["text"], "on-call engineer paged ana.sorensen")

    def test_roles_are_swapped_in_one_pass(self):
        events = self.jsonl("e.jsonl", [
            {"timestamp": "2026-03-14T09:00:00Z", "source": "chat", "actor": "U1",
             "text": "<@U2> and U1 paged engineer; U10 and kai.moreno@example.test were not involved"}])
        roles = self.write("roles.json", json.dumps({"U1": "on-call engineer", "U2": "service owner",
                                                     "engineer": "database engineer"}))
        _, result, _ = run_json(["--events", events, "--roles", roles])
        self.assertEqual(result["timeline"][0]["text"],
                         "service owner and on-call engineer paged database engineer; "
                         "U10 and kai.moreno@example.test were not involved")
        empty = self.write("none.json", "{}")
        code, result, _ = run_json(["--events", events, "--roles", empty])
        self.assertEqual((code, codes(result)), (0, ["no-role"]))

    def test_out_writes_the_file_and_prints_findings(self):
        events = self.jsonl("e.jsonl", [{"timestamp": "2026-03-14 09:00:00", "source": "s", "text": "t"}])
        target = self.dir / "timeline.md"
        code, out, _ = run_main(["--events", events, "--out", target])
        self.assertEqual(code, 1)
        self.assertIn("ERROR no-zone", out)
        self.assertTrue(target.read_text(encoding="utf-8").startswith("# Incident timeline (UTC)"))


class InputErrorTests(TempDirCase):
    def assert_usage_error(self, argv, fragment):
        code, out, err = run_main(argv)
        self.assertEqual(code, 2, err)
        self.assertEqual(out, "")
        self.assertIn(fragment, err)
        self.assertNotIn("Traceback", err)

    def test_input_errors(self):
        good = self.jsonl("good.jsonl", [{"timestamp": "2026-03-14T09:00:00Z", "source": "s", "text": "t"}])
        self.assert_usage_error([], "at least one of")
        self.assert_usage_error(["--events", self.dir / "missing.jsonl"], "cannot read")
        self.assert_usage_error(["--events", self.write("a.jsonl", "[1, 2]\n")], "a.jsonl:1: not a JSON object")
        self.assert_usage_error(["--events", self.write("b.jsonl", '{"timestamp": "x", "text": "t"}\n')],
                                "b.jsonl:1: each event needs")
        self.assert_usage_error(["--events", self.write("c.csv", "time,source,text\n1,a,b\n")], "CSV header")
        self.assert_usage_error(["--events", self.write("empty.jsonl", "\n")], "no events")
        self.assert_usage_error(["--git-log", self.write("g.txt", "commit 0a1b2c3\nAuthor: someone\n")],
                                "git log --pretty=format:'%h%x09%cI%x09%s'")
        self.assert_usage_error(["--chat", self.write("d.json", "{not json")], "not valid JSON")
        self.assert_usage_error(["--chat", self.write("e.json", '{"ok": true}')], "JSON array of message objects")
        self.assert_usage_error(["--events", good, "--assume-zone", "deploys=+05:00"], "not in the inputs")
        self.assert_usage_error(["--events", good, "--assume-zone", "s=EST"], "numeric offset")
        self.assert_usage_error(["--events", good, "--zone-offset", "IST"], "IST=+05:30")
        self.assert_usage_error(["--events", good, "--tag", "detected"], "NAME=VALUE")
        self.assert_usage_error(["--events", good, "--gap-minutes", "0"], "greater than 0")
        self.assert_usage_error(["--events", good, "--roles", self.write("r.json", "[]")], "maps each name")
        other = self.dir / "sub"
        other.mkdir()
        (other / "good.jsonl").write_text(good.read_text())
        self.assert_usage_error(["--events", good, "--events", other / "good.jsonl"], "both named good.jsonl")


class CommandLineTests(unittest.TestCase):
    def test_help_runs_as_a_script_and_documents_exit_codes(self):
        proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "build_timeline.py"), "--help"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0)
        text = proc.stdout.decode("utf-8")
        self.assertIn("Exit codes:", text)
        self.assertIn("Examples:", text)

    def test_script_exit_code_on_a_blocking_fixture(self):
        folder = FILES / "tz-trap"
        proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "build_timeline.py"),
                               "--events", str(folder / "deploys.csv")],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 1)


class DurationFormatTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(build_timeline.format_duration(45), "45s")
        self.assertEqual(build_timeline.format_duration(958), "15m 58s")
        self.assertEqual(build_timeline.format_duration(3600), "1h 00m 00s")
        self.assertEqual(build_timeline.format_duration(93784), "1d 2h 03m 04s")


class ValidateRepoTests(unittest.TestCase):
    def test_repository_passes_its_own_validator(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import validate
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = validate.main(["validate.py", str(ROOT)])
        self.assertEqual(code, 0, buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
