"""Leak gate: a planted secret shape must fail the gate with file:line. Stdlib only, no network.

Secret shapes are assembled at runtime so this file itself never contains one
(the CI gate scans every tracked file, tests included).
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "leak_gate.py"
TERMS = ROOT / "leakgate.example.txt"


def run_gate(*args):
    return subprocess.run([sys.executable, "-I", str(GATE), *args],
                          capture_output=True, text=True)


class LeakGateTests(unittest.TestCase):
    def test_planted_secret_shape_is_caught_with_file_and_line(self):
        planted = "gh" + "p_" + "A" * 36
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "note.md"
            f.write_text(f"fine line\ntoken: {planted}\n", encoding="utf-8")
            r = run_gate(f"--terms={TERMS}", str(f))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("note.md:2", r.stdout)

    def test_clean_file_passes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "ok.md"
            f.write_text("tmrr_your_api_key is a placeholder\n", encoding="utf-8")
            r = run_gate(f"--terms={TERMS}", str(f))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_terms_file_is_used_for_banned_terms(self):
        with tempfile.TemporaryDirectory() as d:
            terms = Path(d) / "terms.txt"
            terms.write_text("# c\n\\bzorblax\\b\n", encoding="utf-8")
            f = Path(d) / "a.md"
            f.write_text("x\nwe use Zorblax here\n", encoding="utf-8")
            r = run_gate(f"--terms={terms}", str(f))
        self.assertEqual(r.returncode, 1)
        self.assertIn("a.md:2", r.stdout)

    def test_tracked_tree_is_clean(self):
        files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                               capture_output=True, text=True).stdout.split("\0")
        files = [str(ROOT / f) for f in files if f]
        if not files:
            self.skipTest("not a git checkout")
        r = run_gate(f"--terms={TERMS}", *files)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
