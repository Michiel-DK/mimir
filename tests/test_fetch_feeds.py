import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_feeds as ff  # noqa: E402

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>tag:a,1</id><title>v2</title><link rel="alternate" href="https://x/v2"/><updated>2026-11-04T00:00:00Z</updated></entry>
<entry><id>tag:a,0</id><title>v1</title><link href="https://x/v1"/><updated>2026-11-01T00:00:00Z</updated></entry></feed>"""
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Post &amp; one</title><link>https://b/1</link><guid>g1</guid><pubDate>Tue, 27 Oct 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""


class FeedTests(unittest.TestCase):
    def test_atom_link_without_children_is_found(self):
        e = ff.parse_feed(ATOM)
        self.assertEqual([x["link"] for x in e], ["https://x/v2", "https://x/v1"])  # Element truthiness trap
        self.assertEqual(e[0]["date"], "2026-11-04")

    def test_rss_title_unescaped_and_date_parsed(self):
        e = ff.parse_feed(RSS)
        self.assertEqual(e[0]["title"], "Post & one"); self.assertEqual(e[0]["date"], "2026-10-27")

    def test_only_unseen_entries_listed(self):
        lines, ids = ff.feed_lines({"name": "n", "url": "u"}, {"tag:a,0"}, fetch=lambda u: ATOM)
        self.assertEqual(ids, ["tag:a,1"]); self.assertEqual(len(lines), 1)


class PageTests(unittest.TestCase):
    def test_first_snapshot_then_diff_then_quiet(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d); page = {"name": "P pricing", "url": "u", "keep": r"\$"}
            v1 = "<p>Starter $20</p><p>noise</p>"; v2 = "<p>Starter $24</p><p>noise 2</p>"
            self.assertIn("first snapshot", ff.page_lines(page, st, fetch=lambda u: v1)[0])
            out = ff.page_lines(page, st, fetch=lambda u: v2)
            self.assertIn("changed", out[0]); self.assertTrue(any("$24" in l for l in out))
            self.assertEqual(ff.page_lines(page, st, fetch=lambda u: v2), [])

    def test_fetch_failure_is_reported_not_silent(self):
        def boom(u): raise OSError("x")
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("fetch failed", ff.page_lines({"name": "p", "url": "u"}, Path(d), fetch=boom)[0])


class AppendTests(unittest.TestCase):
    def test_appends_inside_newest_block(self):
        papers = "# head\n\n## 2026-11-09\n\n### HF blog\n- a\n\n## 2026-11-02\n\n### x\n- b\n"
        out = ff.append_to_newest_block(papers, "### platform releases\n- r\n", date(2026, 11, 9))
        self.assertLess(out.index("### platform releases"), out.index("## 2026-11-02"))
        self.assertGreater(out.index("### platform releases"), out.index("### HF blog"))

    def test_no_block_starts_one(self):
        out = ff.append_to_newest_block("# head\n", "### s\n- r\n", date(2026, 11, 9))
        self.assertIn("## 2026-11-09", out)


if __name__ == "__main__":
    unittest.main()
