"""Smoke tests: no network. Run with  python3 -m unittest discover -s tests  (or pytest)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import arrivals  # noqa: E402
import evidence  # noqa: E402
import radar_config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_example_profile_loads_with_lanes(self):
        os.environ["RADAR_YAML"] = str(ROOT / "radar.example.yaml")
        try:
            cfg = radar_config.load(reload=True)
        finally:
            del os.environ["RADAR_YAML"]
        self.assertIn("lanes", cfg)
        self.assertGreaterEqual(len(cfg["lanes"]), 1)
        for lane in cfg["lanes"]:
            for key in ("id", "question", "what_exists", "reopen_when", "not_now"):
                self.assertIn(key, lane, f"lane {lane.get('id')} lacks {key}")
        self.assertTrue(cfg.get("tracks"))

    def test_missing_profile_gives_empty_dict(self):
        os.environ["RADAR_YAML"] = str(ROOT / "does-not-exist.yaml")
        try:
            self.assertEqual(radar_config.load(reload=True), {})
        finally:
            del os.environ["RADAR_YAML"]


class ArrivalsTests(unittest.TestCase):
    def _history(self, tmp: Path):
        rows = {
            "2026-01-01": [{"slug": "old/one", "stars": 10}],
            "2026-01-05": [{"slug": "old/one", "stars": 11}, {"slug": "mid/two", "stars": 5, "license": "MIT"}],
            "2026-01-06": [{"slug": "mid/two", "stars": 6}],
            "2026-01-08": [{"slug": "old/one", "stars": 12}, {"slug": "new/three", "stars": 99, "created_at": "2020-01-01T00:00:00Z",
                                                               "api_description": "pipes | in | desc"}],
        }
        for d, items in rows.items():
            (tmp / f"{d}.jsonl").write_text("\n".join(json.dumps(r) for r in items) + "\n")
        (tmp / "2026-01-08.meta.json").write_text("{}")  # must be ignored
        (tmp / "notes.txt").write_text("ignored")
        return arrivals.list_snapshots(tmp)

    def test_arrivals_are_first_seen_in_window_not_newcomers(self):
        with tempfile.TemporaryDirectory() as t:
            snaps = self._history(Path(t))
            self.assertEqual(len(snaps), 4)
            rows, info = arrivals.compute_arrivals(snaps, date(2026, 1, 5), date(2026, 1, 8))
            slugs = {r["slug"]: r for r in rows}
            self.assertEqual(set(slugs), {"mid/two", "new/three"})     # old/one first seen 01-01 → not an arrival
            self.assertEqual(slugs["mid/two"]["days_seen"], 2)          # full-history count, not window
            self.assertEqual(slugs["mid/two"]["first_seen"], "2026-01-05")
            self.assertEqual(slugs["mid/two"]["license_key"], "MIT")   # 01-06 row lacks the key; the 01-05 value is kept
            self.assertEqual(slugs["new/three"]["license_key"], "unknown")
            self.assertEqual(slugs["new/three"]["created_at"], "2020-01-01")
            self.assertEqual(rows[0]["slug"], "new/three")              # sorted by stars desc
            self.assertEqual(info["snapshots"], 4)

    def test_window_is_inclusive_on_both_ends(self):
        with tempfile.TemporaryDirectory() as t:
            snaps = self._history(Path(t))
            rows, _ = arrivals.compute_arrivals(snaps, date(2026, 1, 8), date(2026, 1, 8))
            self.assertEqual([r["slug"] for r in rows], ["new/three"])
            rows, _ = arrivals.compute_arrivals(snaps, date(2026, 1, 6), date(2026, 1, 7))
            self.assertEqual(rows, [])

    def test_markdown_escapes_pipes_and_warns_on_short_history(self):
        with tempfile.TemporaryDirectory() as t:
            snaps = self._history(Path(t))
            rows, info = arrivals.compute_arrivals(snaps, date(2026, 1, 5), date(2026, 1, 8))
            md = arrivals.render_md(rows, info)
            self.assertIn("pipes \\| in \\| desc", md)
            self.assertIn("⚠️ History is only 7 days", md)
            self.assertIn("| slug | stars | lang | licence key | created_at | days | description |", md)

    def test_cli_writes_md_and_json(self):
        with tempfile.TemporaryDirectory() as t:
            self._history(Path(t))
            out = Path(t) / "out"
            rc = arrivals.main(["--since", "2026-01-05", "--daily-dir", t, "--out-dir", str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue((out / "2026-01-08.md").exists())
            data = json.loads((out / "2026-01-08.json").read_text())
            self.assertEqual({r["slug"] for r in data["arrivals"]}, {"mid/two", "new/three"})

    def test_cli_rejects_inverted_window(self):
        with tempfile.TemporaryDirectory() as t:
            self._history(Path(t))
            self.assertEqual(arrivals.main(["--since", "2026-02-01", "--daily-dir", t, "--stdout"]), 2)


class EvidenceTests(unittest.TestCase):
    def test_detect(self):
        cases = {
            "2610.18813": ("arxiv", "2610.18813"),
            "https://arxiv.org/abs/2610.18813v2": ("arxiv", "2610.18813"),
            "arxiv.org/pdf/2610.18813": ("arxiv", "2610.18813"),
            "hf:org/model-name": ("hfmodel", "org/model-name"),
            "https://huggingface.co/org/model-name": ("hfmodel", "org/model-name"),
            "https://huggingface.co/blog/org/post": ("hfblog", "https://huggingface.co/blog/org/post"),
            "owner/repo": ("github", "owner/repo"),
            "https://github.com/owner/repo/tree/main/docs": ("github", "owner/repo"),
            "https://github.com/owner/repo.git": ("github", "owner/repo"),
        }
        for item, want in cases.items():
            self.assertEqual(evidence.detect(item), want, item)
        with self.assertRaises(ValueError):
            evidence.detect("just some words here")

    def test_spdx_guess(self):
        self.assertEqual(evidence.spdx_guess("Apache License\n Version 2.0, January 2004"), "Apache-2.0")
        self.assertEqual(evidence.spdx_guess("MIT License\n\nCopyright (c)"), "MIT")
        self.assertEqual(evidence.spdx_guess("GNU AFFERO GENERAL PUBLIC LICENSE Version 3"), "AGPL-3.0")
        self.assertEqual(evidence.spdx_guess("Business Source License 1.1"), "BUSL-1.1")
        self.assertTrue(evidence.spdx_guess("Do whatever, idk").startswith("unrecognised"))

    def test_licence_path_regex_hits_every_depth_and_misses_code(self):
        hits = ["LICENSE", "LICENCE.md", "COPYING", "sub/dir/LICENSE-APACHE", "a/b/c/NOTICE", "pkg/license.txt"]
        misses = ["src/licensing.py", "docs/unlicensed_ideas.md", "LICENSEE_LIST"]
        for p in hits:
            self.assertIsNotNone(evidence.LICENCE_PATH_RE.search(p), p)
        for p in misses:
            self.assertIsNone(evidence.LICENCE_PATH_RE.search(p), p)

    def test_safe_name(self):
        self.assertEqual(evidence.safe_name("github", "owner/repo"), "github-owner-repo.md")
        self.assertEqual(evidence.safe_name("hfblog", "https://huggingface.co/blog/org/post"), "hfblog-org-post.md")


if __name__ == "__main__":
    unittest.main()
