"""Feeds, watched pages and the HN problems digest → `###` sections in the newest PAPERS.md block.

The papers fetcher covers arXiv and the HF blog. A lane about a platform (n8n, HubSpot, …) needs
that platform's release feed, and its prices, which never appear in release notes. This script adds
three generic source types, all declared in radar.yaml `sources:`:

    feeds:                     # RSS or Atom; new entries since the last run become one line each
      - {section: "platform releases", name: "n8n releases", url: "https://github.com/n8n-io/n8n/releases.atom"}
    pages:                     # a page's text, filtered to the lines matching `keep`, diffed against last run
      - {section: "pricing changes", name: "n8n pricing", url: "https://n8n.io/pricing/", keep: "[$€£]"}
    problems_digest:           # the HN problems data (fetch_problems.py output) as a titles section
      {section: "HN problems", dir: "data/problems", days: 7, max: 25}

Output: the sections are appended to the newest `## <date>` block of PAPERS.md (the one the papers
fetcher just wrote), so the triage skill reads them like any other `###` section. State lives in
`data/feeds/` (seen entry ids, page snapshots), so a weekly run lists only what is new.

Run:  python3 scripts/fetch_feeds.py                 # append to PAPERS.md
      python3 scripts/fetch_feeds.py --dry-run       # print, write nothing
      python3 scripts/fetch_feeds.py --papers PATH --state-dir DIR
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import radar_config  # noqa: E402

UA = "mimir-fetch-feeds (+https://github.com/Michiel-DK/mimir)"
ATOM = "{http://www.w3.org/2005/Atom}"
MAX_PER_FEED = 15


def http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


# ---------- feeds ----------

def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 or Atom → [{id, title, link, date}] in feed order."""
    root = ET.fromstring(xml_text)
    out = []
    if root.tag == f"{ATOM}feed":
        for e in root.findall(f"{ATOM}entry"):
            link = e.find(f"{ATOM}link[@rel='alternate']")
            if link is None:  # Element truthiness is "has children", so no `or` here
                link = e.find(f"{ATOM}link")
            out.append({
                "id": (e.findtext(f"{ATOM}id") or "").strip(),
                "title": (e.findtext(f"{ATOM}title") or "").strip(),
                "link": link.get("href", "") if link is not None else "",
                "date": (e.findtext(f"{ATOM}updated") or e.findtext(f"{ATOM}published") or "")[:10],
            })
    else:
        for it in root.iter("item"):
            pub = (it.findtext("pubDate") or "").strip()
            try:
                d = datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S").date().isoformat()
            except ValueError:
                d = pub[:16]
            link = (it.findtext("link") or "").strip()
            out.append({"id": (it.findtext("guid") or link).strip(), "title": html.unescape((it.findtext("title") or "").strip()),
                        "link": link, "date": d})
    return [x for x in out if x["id"] or x["link"]]


def feed_lines(feed: dict, seen: set, fetch=http_get) -> tuple[list[str], list[str]]:
    """Return (lines for new entries, ids of those entries). First run lists the newest MAX_PER_FEED."""
    entries = parse_feed(fetch(feed["url"]))
    new = [e for e in entries if (e["id"] or e["link"]) not in seen][:MAX_PER_FEED]
    lines = [f"- [{e['title'] or e['link']}]({e['link']}) ({e['date']}) — {feed['name']}" for e in new]
    return lines, [e["id"] or e["link"] for e in new]


# ---------- pages ----------

def page_text(raw_html: str, keep: str | None) -> list[str]:
    t = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", "", raw_html, flags=re.S | re.I)
    t = re.sub(r"<(br|p|div|li|tr|h[1-6])[^>]*>", "\n", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln]
    if keep:
        rx = re.compile(keep)
        lines = [ln for ln in lines if rx.search(ln)]
    return lines


def page_lines(page: dict, state_dir: Path, fetch=http_get, write=True) -> list[str]:
    snap = state_dir / "pages" / (re.sub(r"[^a-z0-9]+", "-", page["name"].lower()).strip("-") + ".txt")
    try:
        now = page_text(fetch(page["url"]), page.get("keep"))
    except Exception as e:  # say so in the feed; a silent skip would read as "no change"
        return [f"- ⚠️ {page['name']}: fetch failed ({type(e).__name__}); not compared — {page['url']}"]
    if not now:
        return [f"- ⚠️ {page['name']}: no lines matched `keep`; page layout may have changed — {page['url']}"]
    before = snap.read_text(encoding="utf-8").splitlines() if snap.exists() else None
    if write:
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text("\n".join(now) + "\n", encoding="utf-8")
    if before is None:
        return [f"- {page['name']}: first snapshot ({len(now)} lines kept), nothing to compare yet — {page['url']}"]
    diff = [d for d in difflib.unified_diff(before, now, lineterm="", n=0) if d[:1] in "+-" and d[:3] not in ("+++", "---")]
    if not diff:
        return []
    shown = diff[:12]
    out = [f"- **{page['name']} changed** ({sum(d[0] == '+' for d in diff)} lines added, {sum(d[0] == '-' for d in diff)} removed) — {page['url']}"]
    out += [f"  - `{d[0]}` {d[1:][:160]}" for d in shown]
    if len(diff) > len(shown):
        out.append(f"  - … {len(diff) - len(shown)} more changed lines in `{snap.relative_to(ROOT) if snap.is_relative_to(ROOT) else snap}`")
    return out


# ---------- HN problems digest ----------

def problems_lines(cfg: dict, today: date) -> list[str]:
    d = Path(cfg.get("dir", "data/problems"))
    d = d if d.is_absolute() else (ROOT / d).resolve()
    since = today - timedelta(days=int(cfg.get("days", 7)))
    rows, seen = [], set()
    for f in sorted(d.glob("*.jsonl")):
        try:
            fd = date.fromisoformat(f.stem[:10])
        except ValueError:
            continue
        if fd <= since:
            continue
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("id") in seen:
                continue
            seen.add(r.get("id"))
            rows.append(r)
    asks = sorted((r for r in rows if r.get("kind") != "pain_match"), key=lambda r: -(r.get("points") or 0))
    pains = [r for r in rows if r.get("kind") == "pain_match"]
    pick = (asks + pains)[: int(cfg.get("max", 25))]
    return [f"- [{r.get('title', '')}]({r.get('url', '')}) ({r.get('kind')}, {r.get('points') or '–'} pts)"
            + (f" — matched “{r['matched']}”" if r.get("matched") else "") for r in pick]


# ---------- assemble ----------

def build_sections(sources: dict, state_dir: Path, today: date, fetch=http_get, write=True) -> tuple[dict, dict]:
    """Return ({section: [lines]}, new_seen_ids_by_feed)."""
    seen_path = state_dir / "seen.json"
    seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}
    sections: dict[str, list[str]] = {}
    new_seen: dict[str, list[str]] = {}
    for feed in sources.get("feeds") or []:
        key = feed["url"]
        try:
            lines, ids = feed_lines(feed, set(seen.get(key, [])), fetch)
        except Exception as e:
            lines, ids = [f"- ⚠️ {feed['name']}: fetch or parse failed ({type(e).__name__}) — {feed['url']}"], []
        sections.setdefault(feed.get("section", "feeds"), []).extend(lines)
        new_seen[key] = ids
    for page in sources.get("pages") or []:
        sections.setdefault(page.get("section", "page changes"), []).extend(page_lines(page, state_dir, fetch, write))
    pd = sources.get("problems_digest")
    if pd:
        sections.setdefault(pd.get("section", "HN problems"), []).extend(problems_lines(pd, today))
    return sections, new_seen


def render(sections: dict) -> str:
    out = []
    for name, lines in sections.items():
        out.append(f"### {name}\n" + ("\n".join(lines) if lines else "- nothing new since the last run") + "\n")
    return "\n".join(out)


def append_to_newest_block(papers: str, text: str, today: date) -> str:
    """Insert `text` at the end of the newest `## <date>` block; start a block for today if there is none."""
    m = re.search(r"^## \d{4}-\d{2}-\d{2}\s*$", papers, flags=re.M)
    if not m:
        return papers.rstrip("\n") + f"\n\n## {today.isoformat()}\n\n{text}"
    nxt = re.search(r"^## \d{4}-\d{2}-\d{2}\s*$", papers[m.end():], flags=re.M)
    cut = m.end() + nxt.start() if nxt else len(papers)
    head, tail = papers[:cut].rstrip("\n"), papers[cut:]
    return f"{head}\n\n{text.rstrip()}\n\n{tail}" if tail else f"{head}\n\n{text.rstrip()}\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--papers", type=Path, default=ROOT / "PAPERS.md")
    ap.add_argument("--state-dir", type=Path, default=ROOT / "data" / "feeds")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    sources = radar_config.get("sources", default={}) or {}
    if not any(sources.get(k) for k in ("feeds", "pages", "problems_digest")):
        print("[fetch_feeds] radar.yaml declares no feeds, pages or problems_digest; nothing to do")
        return 0
    today = datetime.now(timezone.utc).date()
    sections, new_seen = build_sections(sources, a.state_dir, today, write=not a.dry_run)
    text = render(sections)
    if a.dry_run:
        print(text)
        return 0
    a.papers.write_text(append_to_newest_block(a.papers.read_text(encoding="utf-8"), text, today), encoding="utf-8")
    seen_path = a.state_dir / "seen.json"
    seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}
    for k, ids in new_seen.items():
        seen[k] = sorted(set(seen.get(k, [])) | set(ids))
    a.state_dir.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(seen, indent=1) + "\n")
    n = sum(len(v) for v in sections.values())
    print(f"[fetch_feeds] {len(sections)} sections, {n} lines → {a.papers}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
