"""handoff.py tests: no network, no gh. A fake runner records every command."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import handoff  # noqa: E402

PICKUP_A = """# pickup — ticket-agent-evals

## 2026-10-20 — from triage 2026-10-20
- old item → ignore me · reopen: never · evidence: abstract

## 2026-11-03 — from triage 2026-11-03
- [DeLoop](https://arxiv.org/abs/2610.00001) (2610.00001) → trajectory-level loop check, deterministic · reopen: n/a, CANDIDATE on case backlog · evidence: abstract
- citations: one ALREADY row

## Notes
not a pickup block
"""

PICKUP_B = """## 2026-11-03 - from triage 2026-11-03
- hyphen variant → still a block · reopen: x · evidence: README+licence
"""

CFG = {
    "handoff": {"mode": "issue", "repos": {"support-agent": "example-labs/support-agent"}, "labels": ["mimir"],
                "source": "https://github.com/example-labs/mimir"},
    "lanes": [
        {"id": "ticket-agent-evals", "repo": "support-agent", "status": "live",
         "question": "Does a cheaper model resolve the same held-out tickets?"},
        {"id": "runtime-proxy", "repo": "support-agent", "status": "next", "question": "Adopt or build the proxy."},
        {"id": "orphan", "repo": "nowhere", "question": "unmapped repo label"},
    ],
}


class FakeRun:
    """Stands in for subprocess.run. Records commands; answers gh queries from `issues`/`prs`."""

    def __init__(self, issues=None, prs=None, fail_on=None, private=None):
        self.calls = []
        self.private = private or {}  # repo → True / False; missing = lookup fails
        self.issues = issues or {}   # repo → [{"title","url"}]
        self.prs = prs or {}         # (repo, branch) → url
        self.fail_on = fail_on       # substring of a command that should fail
        self.dirty = ""              # porcelain output for `git status -- VERDICTS.md pickup`

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        joined = " ".join(cmd)
        if self.fail_on and self.fail_on in joined:
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        if cmd[:2] == ["gh", "issue"] and cmd[2] == "list":
            repo = cmd[cmd.index("--repo") + 1]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(self.issues.get(repo, [])), "")
        if cmd[:3] == ["gh", "repo", "view"]:
            if cmd[3] not in self.private:
                return subprocess.CompletedProcess(cmd, 1, "", "not found")
            return subprocess.CompletedProcess(cmd, 0, "true\n" if self.private[cmd[3]] else "false\n", "")
        if cmd[:2] == ["gh", "issue"] and cmd[2] == "create":
            return subprocess.CompletedProcess(cmd, 0, "https://github.com/x/y/issues/7\n", "")
        if cmd[:2] == ["gh", "pr"] and cmd[2] == "list":
            repo = cmd[cmd.index("--repo") + 1]; branch = cmd[cmd.index("--head") + 1]
            url = self.prs.get((repo, branch))
            return subprocess.CompletedProcess(cmd, 0, json.dumps([{"url": url}] if url else []), "")
        if cmd[:2] == ["gh", "pr"] and cmd[2] == "create":
            return subprocess.CompletedProcess(cmd, 0, "https://github.com/x/y/pull/9\n", "")
        if cmd[:3] == ["gh", "repo", "clone"]:
            Path(cmd[4]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "git" and "status" in cmd:
            return subprocess.CompletedProcess(cmd, 0, self.dirty, "")
        if cmd[0] == "git" and "remote" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "git@github.com:example-labs/mimir.git\n", "")
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if str(handoff.LEAK_GATE) in joined:  # real gate would need a file; treat as clean
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected command: {cmd}")


def _env(pickups: dict):
    t = tempfile.TemporaryDirectory()
    root = Path(t.name)
    (root / "pickup").mkdir()
    for lane, text in pickups.items():
        (root / "pickup" / f"{lane}.md").write_text(text, encoding="utf-8")
    return t, root / "pickup", root / "ledger"


class ParseTests(unittest.TestCase):
    def test_blocks_split_on_heading_and_match_triage_date(self):
        blocks = handoff.parse_blocks(PICKUP_A)
        self.assertEqual([b["triage"] for b in blocks], ["2026-10-20", "2026-11-03"])
        self.assertIn("DeLoop", blocks[1]["body"])
        self.assertNotIn("not a pickup block", blocks[1]["body"])
        self.assertNotIn("old item", blocks[1]["body"])

    def test_hyphen_and_em_dash_headings_both_parse(self):
        self.assertEqual(len(handoff.parse_blocks(PICKUP_B)), 1)
        self.assertEqual(len(handoff.parse_blocks(PICKUP_B.replace(" - ", " — "))), 1)
        self.assertEqual(len(handoff.parse_blocks(PICKUP_B.replace(" - ", " – "))), 1)

    def test_blocks_for_picks_only_the_requested_triage(self):
        t, pick, _ = _env({"ticket-agent-evals": PICKUP_A, "runtime-proxy": PICKUP_B})
        with t:
            got = handoff.blocks_for(pick, "2026-11-03")
            self.assertEqual(set(got), {"ticket-agent-evals", "runtime-proxy"})
            self.assertEqual(handoff.blocks_for(pick, "2026-10-20").keys(), {"ticket-agent-evals"})
            self.assertEqual(handoff.blocks_for(pick, "2026-11-03", only_lane="runtime-proxy").keys(), {"runtime-proxy"})
            self.assertEqual(handoff.blocks_for(pick, "1999-01-01"), {})


class ConfigTests(unittest.TestCase):
    def test_missing_block_or_bad_repo_is_a_config_error(self):
        with self.assertRaises(SystemExit):
            handoff.handoff_config({"lanes": []})
        with self.assertRaises(SystemExit):
            handoff.handoff_config({"handoff": {"repos": {"a": "not-a-repo"}}})
        with self.assertRaises(SystemExit):
            handoff.handoff_config({"handoff": {"mode": "email", "repos": {"a": "o/r"}}})
        h = handoff.handoff_config({"handoff": {"repos": {"a": "o/r"}}})
        self.assertEqual((h["mode"], h["pr_path"], h["labels"]), ("issue", "docs/pickup", []))

    def test_lane_repo_written_as_owner_name_resolves_without_a_map_entry(self):
        h = handoff.handoff_config({"handoff": {"repos": {"a": "o/r"}}})
        self.assertEqual(handoff.resolve_repo({"repo": "someone/else"}, h), "someone/else")
        self.assertEqual(handoff.resolve_repo({"repo": "a"}, h), "o/r")
        self.assertIsNone(handoff.resolve_repo({"repo": "nowhere"}, h))
        self.assertIsNone(handoff.resolve_repo({}, h))


class RenderTests(unittest.TestCase):
    def test_body_carries_lane_question_block_and_link_back(self):
        block = handoff.parse_blocks(PICKUP_A)[1]
        body = handoff.render_body("ticket-agent-evals", CFG["lanes"][0], block, "2026-11-03",
                                   "https://github.com/example-labs/mimir")
        self.assertIn("`ticket-agent-evals`", body)
        self.assertIn("> Does a cheaper model", body)
        self.assertIn("DeLoop", body)
        self.assertIn("https://github.com/example-labs/mimir/blob/main/VERDICTS.md", body)
        body2 = handoff.render_body("ticket-agent-evals", CFG["lanes"][0], block, "2026-11-03",
                                    "https://github.com/example-labs/mimir", "https://github.com/example-labs/radar/blob/master/VERDICTS.md")
        self.assertIn("example-labs/radar/blob/master/VERDICTS.md", body2)
        self.assertNotIn("example-labs/mimir/blob/main", body2)
        self.assertIn("Triage opens no work", body)
        self.assertEqual(handoff.title_for("2026-11-03", "runtime-proxy"), "mimir pickup 2026-11-03: runtime-proxy")

    def test_source_url_from_ssh_remote(self):
        run = FakeRun()
        self.assertEqual(handoff.source_url({"source": None}, run), "https://github.com/example-labs/mimir")
        self.assertEqual(handoff.source_url({"source": "https://x/y/"}, run), "https://x/y")


PRIVATE_CFG = {**CFG, "handoff": {**CFG["handoff"], "private_only": True}}


class PrivateOnlyTests(unittest.TestCase):
    def _send(self, private):
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            run = FakeRun(private=private)
            res = handoff.handoff(PRIVATE_CFG, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None)
            creates = [c for c in run.calls if c[:3] == ["gh", "issue", "create"]]
            return res, creates, (ledger / "2026-11-03.json").exists()

    def test_public_repo_is_refused(self):
        res, creates, wrote = self._send({"example-labs/support-agent": False})
        self.assertEqual(res["refused"], ["ticket-agent-evals"]); self.assertEqual(creates, []); self.assertFalse(wrote)

    def test_unreadable_visibility_is_refused(self):
        res, creates, _ = self._send({})
        self.assertEqual(res["refused"], ["ticket-agent-evals"]); self.assertEqual(creates, [])

    def test_private_repo_is_sent(self):
        res, creates, wrote = self._send({"example-labs/support-agent": True})
        self.assertEqual(res["sent"], ["ticket-agent-evals"]); self.assertEqual(len(creates), 1); self.assertTrue(wrote)

    def test_allow_public_exempts_a_named_repo(self):
        cfg = {**CFG, "handoff": {**CFG["handoff"], "private_only": True, "allow_public": ["example-labs/support-agent"]}}
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            run = FakeRun(private={"example-labs/support-agent": False})
            res = handoff.handoff(cfg, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None)
            self.assertEqual(res["sent"], ["ticket-agent-evals"])
            self.assertFalse(any(c[:3] == ["gh", "repo", "view"] for c in run.calls))

    def test_private_only_must_be_bool(self):
        with self.assertRaises(SystemExit):
            handoff.handoff_config({"handoff": {**CFG["handoff"], "private_only": "yes"}})

    def test_off_by_default_makes_no_visibility_call(self):
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            run = FakeRun()
            handoff.handoff(CFG, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None)
            self.assertFalse(any(c[:3] == ["gh", "repo", "view"] for c in run.calls))


class IssueModeTests(unittest.TestCase):
    def test_dry_run_sends_nothing_and_writes_no_ledger(self):
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            run = FakeRun(); lines = []
            res = handoff.handoff(CFG, "2026-11-03", dry_run=True, pickup_dir=pick, ledger_dir=ledger, run=run, out=lines.append)
            self.assertEqual(res["sent"], ["ticket-agent-evals"])
            self.assertFalse(any(c[0] == "gh" for c in run.calls))
            self.assertFalse(ledger.exists())
            self.assertTrue(any("DRY RUN issue → example-labs/support-agent" in l for l in lines))

    def test_opens_one_issue_per_lane_and_is_idempotent(self):
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A, "runtime-proxy": PICKUP_B, "orphan": PICKUP_B})
        with t:
            run = FakeRun(); lines = []
            res = handoff.handoff(CFG, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lines.append)
            self.assertEqual(sorted(res["sent"]), ["runtime-proxy", "ticket-agent-evals"])
            self.assertEqual(res["unmapped"], ["orphan"])
            creates = [c for c in run.calls if c[:3] == ["gh", "issue", "create"]]
            self.assertEqual(len(creates), 2)
            self.assertIn("--label", creates[0]); self.assertIn("mimir", creates[0])
            self.assertIn("mimir pickup 2026-11-03: runtime-proxy", " ".join(creates[1]) + " ".join(creates[0]))
            led = json.loads((ledger / "2026-11-03.json").read_text())
            self.assertEqual(set(led), {"runtime-proxy", "ticket-agent-evals"})
            self.assertEqual(led["runtime-proxy"]["url"], "https://github.com/x/y/issues/7")
            # second run: nothing re-sent
            run2 = FakeRun()
            res2 = handoff.handoff(CFG, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run2, out=lambda *_: None)
            self.assertEqual(res2["sent"], [])
            self.assertEqual(sorted(res2["skipped"]), ["runtime-proxy", "ticket-agent-evals"])
            self.assertFalse(any(c[:3] == ["gh", "issue", "create"] for c in run2.calls))

    def test_existing_issue_with_same_title_is_recorded_not_duplicated(self):
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            run = FakeRun(issues={"example-labs/support-agent": [
                {"title": "mimir pickup 2026-11-03: ticket-agent-evals", "url": "https://github.com/x/y/issues/3"},
                {"title": "mimir pickup 2026-11-03: ticket-agent-evals (old)", "url": "https://github.com/x/y/issues/2"}]})
            res = handoff.handoff(CFG, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None)
            self.assertEqual(res["skipped"], ["ticket-agent-evals"])
            self.assertFalse(any(c[:3] == ["gh", "issue", "create"] for c in run.calls))
            led = json.loads((ledger / "2026-11-03.json").read_text())
            self.assertEqual(led["ticket-agent-evals"]["url"], "https://github.com/x/y/issues/3")
            self.assertEqual(led["ticket-agent-evals"]["note"], "pre-existing")

    def test_gh_failure_stops_with_a_message_and_keeps_earlier_sends(self):
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A, "runtime-proxy": PICKUP_B})
        with t:
            run = FakeRun(fail_on="issue create --repo example-labs/support-agent --title mimir pickup 2026-11-03: ticket-agent-evals")
            with self.assertRaises(SystemExit) as cm:
                handoff.handoff(CFG, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None)
            self.assertIn("gh issue create failed", str(cm.exception))
            led = json.loads((ledger / "2026-11-03.json").read_text())
            self.assertEqual(set(led), {"runtime-proxy"})  # the lane sent before the failure is on record

    def test_leak_gate_hit_blocks_the_send(self):
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            run = FakeRun(fail_on="leak_gate.py")
            with self.assertRaises(SystemExit) as cm:
                handoff.handoff(CFG, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None)
            self.assertIn("leak gate blocked", str(cm.exception))
            self.assertFalse(any(c[:3] == ["gh", "issue", "create"] for c in run.calls))

    def test_no_blocks_for_the_date_is_a_clean_no_op(self):
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            res = handoff.handoff(CFG, "2030-01-01", pickup_dir=pick, ledger_dir=ledger, run=FakeRun(), out=lambda *_: None)
            self.assertTrue(res["none"]); self.assertEqual(res["sent"], [])


class PrModeTests(unittest.TestCase):
    def test_pr_mode_writes_the_note_on_a_dated_branch(self):
        cfg = json.loads(json.dumps(CFG)); cfg["handoff"]["mode"] = "pr"; cfg["handoff"]["pr_path"] = "docs/radar"
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            run = FakeRun()
            res = handoff.handoff(cfg, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None)
            self.assertEqual(res["sent"], ["ticket-agent-evals"])
            checkout = next(c for c in run.calls if c[0] == "git" and "checkout" in c)
            self.assertEqual(checkout[-1], "mimir/pickup-2026-11-03-ticket-agent-evals")
            add = next(c for c in run.calls if c[0] == "git" and "add" in c)
            self.assertEqual(add[-1], "docs/radar/2026-11-03-ticket-agent-evals.md")
            clone = next(c for c in run.calls if c[:3] == ["gh", "repo", "clone"])
            written = Path(clone[4]) / "docs/radar/2026-11-03-ticket-agent-evals.md"
            self.assertIn("DeLoop", written.read_text())
            self.assertTrue(any(c[:3] == ["gh", "pr", "create"] for c in run.calls))
            led = json.loads((ledger / "2026-11-03.json").read_text())
            self.assertEqual(led["ticket-agent-evals"]["kind"], "pr")

    def test_pr_mode_skips_when_branch_already_has_a_pr(self):
        cfg = json.loads(json.dumps(CFG)); cfg["handoff"]["mode"] = "pr"
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            run = FakeRun(prs={("example-labs/support-agent", "mimir/pickup-2026-11-03-ticket-agent-evals"): "https://github.com/x/y/pull/4"})
            res = handoff.handoff(cfg, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None)
            self.assertEqual(res["skipped"], ["ticket-agent-evals"])
            self.assertFalse(any(c[:3] == ["gh", "repo", "clone"] for c in run.calls))


if __name__ == "__main__":
    unittest.main()


class CliPickupDir(unittest.TestCase):
    def test_cli_reads_blocks_from_pickup_dir_and_ledger_dir_in_dry_run(self):
        import contextlib, io, os
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as d:
            ledger = Path(d) / "ledger"
            env_before = os.environ.get("RADAR_YAML")
            os.environ["RADAR_YAML"] = str(root / "radar.example.yaml")
            try:
                import radar_config
                radar_config.load(reload=True)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = handoff.main(["--date", "2026-10-19", "--dry-run",
                                       "--pickup-dir", str(root / "examples" / "2026-10-19" / "pickup"),
                                       "--ledger-dir", str(ledger)])
            finally:
                if env_before is None:
                    os.environ.pop("RADAR_YAML", None)
                else:
                    os.environ["RADAR_YAML"] = env_before
                radar_config.load(reload=True)
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("DRY RUN issue → example-labs/support-agent", out)
        for lane in ("runtime-proxy", "ticket-agent-evals", "harness"):
            self.assertIn(f"mimir pickup 2026-10-19: {lane}", out)
        self.assertIn("DRY RUN issue → example-labs/dev-harness", out)
        self.assertIn("3 would be sent, 0 already done, 0 unmapped", out)
        self.assertFalse(ledger.exists(), "dry run must write no ledger")


class DirtyTree(unittest.TestCase):
    def test_real_send_refuses_uncommitted_outputs_unless_allowed(self):
        t, pick, ledger = _env({"ticket-agent-evals": PICKUP_A})
        with t:
            run = FakeRun(); run.dirty = "?? VERDICTS.md\n?? pickup/ticket-agent-evals.md\n"
            with self.assertRaises(SystemExit) as cm:
                handoff.handoff(CFG, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None)
            self.assertIn("uncommitted", str(cm.exception))
            self.assertFalse(any(c[:3] == ["gh", "issue", "create"] for c in run.calls))
            res = handoff.handoff(CFG, "2026-11-03", pickup_dir=pick, ledger_dir=ledger, run=run, out=lambda *_: None,
                                  allow_dirty=True)
            self.assertEqual(res["sent"], ["ticket-agent-evals"])
            run2 = FakeRun(); run2.dirty = "?? VERDICTS.md\n"
            res = handoff.handoff(CFG, "2026-11-03", dry_run=True, pickup_dir=pick, ledger_dir=ledger, run=run2,
                                  out=lambda *_: None)
            self.assertEqual(res["sent"], [])
            self.assertFalse(any(c[0] == "git" and "status" in c for c in run2.calls), "dry run never checks the tree")
