#!/usr/bin/env python3
"""Weekly reading watch: Hugging Face blog + arXiv papers (via OpenAlex), keyed to the live tracks.

Appends ONE dated section to PAPERS.md:
  - `### HF blog` — up to HF_CAP new posts from https://huggingface.co/blog/feed.xml,
    title-keyword track tags as triage hints (the feed has no summaries). Dedupe:
    data/hf_blog_seen.json (post URLs).
  - one `### <track>` per paper track — up to CAP new arXiv papers each, most relevant first,
    from the last ARXIV_WINDOW_DAYS. Dedupe: data/papers_seen.json (arXiv ids).
Stdlib only.

Why OpenAlex, not the arXiv API (2026-09-28): export.arxiv.org 429'd/406'd the scheduled CI run on
three straight Mondays, 09-14/21/28 (all 7 tracks; urllib, then curl on 09-28; 09-07 had worked) while the same queries passed
from the laptop: intermittent server-side throttling, most likely of GitHub's shared runner IPs.
Two client-side patches (urllib -> curl, 09-23) did not fix it, so the source moved instead.
OpenAlex indexes arXiv (source S4306400194) with ~2 days of lag, gives each arXiv paper its
DataCite DOI 10.48550/arxiv.<id> (so papers_seen.json keeps working), and is built for automated
access. Costs, measured 09-28 without a key: $0.10/day free budget; a search costs $0.001, so a
run is ~$0.01. BUT anonymous *search* gets 429 whenever OpenAlex's search cluster is under load
(seen 09-28, Retry-After 35s); the script waits and retries 3x. A free key in OPENALEX_API_KEY
(repo secret) is the real fix, per OpenAlex's own error message.
Differences from the old arXiv queries: no arXiv categories (approximated with OpenAlex's
Computer Science field), stemmed search (so "harness" also matches "harnessing"), and results
ranked by relevance instead of newest first.

House rules baked in:
  - Caps are hard — an uncapped feed is an unread inbox (BUILD_TRACK ground rule).
  - This file is the CANDIDATE list. Promotion into BUILD_TRACK.md's resource inbox is a
    manual, human triage act — never automated.
  - KILL CLAUSE, PER SOURCE (re-registered 2026-09-23): two consecutive weekly triages
    promoting nothing from a source → drop that source. Both dead → delete the workflow
    and this script. arXiv starts on notice: 0 of 92 listed papers promoted 08-10 → 09-21
    (operator kept it 09-23 regardless); the HF blog had 4 hand-promotions in that window.

Run:  python3 scripts/fetch_papers.py            # append to PAPERS.md
      python3 scripts/fetch_papers.py --dry-run  # print, write nothing
"""
import json
import re
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HF_SEEN_PATH = ROOT / "data" / "hf_blog_seen.json"
ARXIV_SEEN_PATH = ROOT / "data" / "papers_seen.json"
OUT_PATH = ROOT / "PAPERS.md"
FEED_URL = "https://huggingface.co/blog/feed.xml"
WINDOW_DAYS = 8  # weekly cadence + 1 day slack (HF blog)
ARXIV_WINDOW_DAYS = 10  # OpenAlex lists arXiv papers ~2 days late; the seen-file stops repeats
HF_CAP = 10      # max new HF posts per week (feed runs ~3-5/week, so this rarely bites)
CAP = 3          # max new arXiv papers per track per week
FETCH = 40       # results pulled per query before local filtering
OPENALEX_URL = "https://api.openalex.org/works"
ARXIV_SOURCE = "S4306400194"  # OpenAlex source id for arXiv (Cornell University)
CS_FIELD = "fields/17"        # Computer Science: stands in for the old cs.* category filters

# track → OpenAlex title+abstract search (boolean OR, quoted phrases). Tracks mirror
# BUILD_TRACK's queue + the two watch-trends named 2026-08-10 (mid-training, self-hosted inference).
import radar_config
DEFAULT_TRACKS = {
    "agents": '"agent harness" OR "agent evaluation" OR "long-horizon agent" OR "self-improving agent"',
    "retrieval": '"retrieval evaluation" OR "embedding fine-tuning" OR reranker OR "late interaction"',
    "post-training": '"verifiable rewards" OR RLVR OR GRPO OR "reward hacking"',
    "serving": '"LLM inference" OR "speculative decoding" OR "KV cache" OR "serving system"',
}
TRACKS = radar_config.get("tracks", default=DEFAULT_TRACKS)

NS = {"a": "http://www.w3.org/2005/Atom"}

# Title-keyword → track tag. The feed carries title + link + date only (no summary), so
# tagging is a triage hint, not a filter: untagged posts are still listed.
DEFAULT_TAGS = {
    "agents":   r"\bagents?\b|agentic|harness|memory",
    "evals":    r"benchmark|leaderboard|eval|reproduc|measur",
    "post-training": r"grpo|rlvr|\brl\b|reinforcement|reward|fine-?tun|distill|post-train",
    "retrieval": r"embedding|retriev|rerank|late interaction|multi-vector|encoder",
    "serving":  r"inference|quantiz|quants?\b|kernel|serving|latency|gpu|llama\.cpp|mlx|4-bit",
}
TAGS = radar_config.get("tags", default=DEFAULT_TAGS)


def fetch_hf():
    with urllib.request.urlopen(FEED_URL, timeout=60) as r:
        tree = ET.fromstring(r.read())
    out = []
    for item in tree.iter("item"):
        link = (item.findtext("link") or "").strip()
        try:
            pub = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        out.append({
            "url": link,
            "title": re.sub(r"\s+", " ", item.findtext("title") or "").strip(),
            "published": pub,
        })
    return out


def _arxiv_id(work) -> str | None:
    """arXiv id from the DataCite DOI (10.48550/arxiv.<id>) or an arxiv.org/abs link; None
    when the record isn't an arXiv paper (the source filter lets a few Zenodo records through)."""
    m = re.search(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", (work.get("doi") or "").lower())
    if not m:
        link = (work.get("primary_location") or {}).get("landing_page_url") or ""
        m = re.search(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", link)
    return m.group(1) if m else None


def _abstract(inverted) -> str:
    if not inverted:
        return ""
    words = sorted((pos, w) for w, positions in inverted.items() for pos in positions)
    return " ".join(w for _, w in words)


def _openalex_key() -> str:
    """OPENALEX_API_KEY (CI secret) or OPENALEX_API (the name used in the local .env)."""
    return (os.environ.get("OPENALEX_API_KEY") or os.environ.get("OPENALEX_API") or "").strip().strip("'\"")


def fetch_arxiv(search: str, since: str):
    params = {
        "filter": f"primary_location.source.id:{ARXIV_SOURCE},primary_topic.field.id:{CS_FIELD},"
                  f"from_publication_date:{since},title_and_abstract.search:{search}",
        "per-page": FETCH,
        "select": "title,publication_date,doi,primary_location,abstract_inverted_index",
    }
    key = _openalex_key()
    if key:
        params["api_key"] = key
    url = OPENALEX_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            # 429 = anonymous search throttled "while the search cluster is under elevated load"
            # (measured 09-28); OpenAlex sends Retry-After. A free OPENALEX_API_KEY avoids it.
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(min(int(e.headers.get("Retry-After") or 30), 120) + 1)
    out = []
    for w in data.get("results", []):  # relevance order (OpenAlex's default when searching)
        aid = _arxiv_id(w)
        if not aid:
            continue
        out.append({
            "id": aid,
            "title": re.sub(r"\s+", " ", w.get("title") or "").strip(),
            "published": w.get("publication_date") or "",
            "summary": re.sub(r"\s+", " ", _abstract(w.get("abstract_inverted_index"))).strip()[:300],
        })
    return out


def tags_for(title: str):
    t = title.lower()
    return [tag for tag, pat in TAGS.items() if re.search(pat, t)]


def hf_section(seen, cutoff):
    """→ (markdown lines, new urls)."""
    try:
        posts = fetch_hf()
    except Exception as e:  # say so in the file — a silent empty week reads as "nothing new"
        return ["### HF blog", f"- ⚠️ feed fetch failed: {e}"], []
    fresh = sorted((p for p in posts if p["published"] >= cutoff and p["url"] not in seen),
                   key=lambda p: p["published"], reverse=True)
    dropped = max(0, len(fresh) - HF_CAP)
    fresh = fresh[:HF_CAP]
    if not fresh:
        return [], []
    lines = ["### HF blog"]
    for p in fresh:
        tags = tags_for(p["title"])
        tag_str = " · " + ", ".join(f"`{t}`" for t in tags) if tags else ""
        lines.append(f"- [{p['title']}]({p['url']}) ({p['published']:%Y-%m-%d}){tag_str}")
    if dropped:
        lines.append(f"- _…{dropped} more over the cap of {HF_CAP} — not listed, not marked seen._")
    return lines, [p["url"] for p in fresh]


def arxiv_sections(seen, cutoff):
    """→ (list of markdown blocks, new ids). `cutoff` is unused: the date window is applied
    server-side (ARXIV_WINDOW_DAYS), because OpenAlex lists papers ~2 days late."""
    since = (datetime.now(timezone.utc) - timedelta(days=ARXIV_WINDOW_DAYS)).strftime("%Y-%m-%d")
    print(f"openalex: {'API key' if _openalex_key() else 'anonymous (no key — search may be throttled)'}",
          file=sys.stderr)
    sections, new_ids = [], []
    seen = set(seen)  # grows as tracks list papers, so one paper can't appear under two tracks
    for i, (track, query) in enumerate(TRACKS.items()):
        if i:
            time.sleep(0.5)  # well under OpenAlex's rate limit; it's the daily $ budget that binds
        entries = None
        for attempt in (1, 2):
            try:
                entries = fetch_arxiv(query, since)
                break
            except Exception as e:  # one dead query must not kill the sweep — but say so
                if attempt == 2:
                    sections.append(f"### {track}\n- ⚠️ query failed twice: {e}\n")
                else:
                    time.sleep(10)
        if entries is None:
            continue
        fresh = []
        for p in entries:
            if p["id"] in seen:
                continue
            fresh.append(p)
            if len(fresh) >= CAP:
                break
        if not fresh:
            continue
        lines = [f"### {track}"]
        for p in fresh:
            lines.append(f"- [{p['title']}](https://arxiv.org/abs/{p['id']}) "
                         f"({p['published'][:10]}) — {p['summary']}…")
            new_ids.append(p["id"])
            seen.add(p["id"])
        sections.append("\n".join(lines) + "\n")
    return sections, new_ids


def load_seen(path):
    return set(json.loads(path.read_text())) if path.exists() else set()


def main():
    dry = "--dry-run" in sys.argv
    hf_seen, arxiv_seen = load_seen(HF_SEEN_PATH), load_seen(ARXIV_SEEN_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    hf_lines, new_urls = hf_section(hf_seen, cutoff)
    ax_sections, new_ids = arxiv_sections(arxiv_seen, cutoff)
    parts = (["\n".join(hf_lines) + "\n"] if hf_lines else []) + ax_sections

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not parts:
        block = f"## {today}\n\n_Nothing new from the HF blog or any arXiv track this week._\n"
    else:
        block = f"## {today}\n\n" + "\n".join(parts)

    if dry:
        print(block)
        return

    header = ""
    body = ""
    if OUT_PATH.exists():
        text = OUT_PATH.read_text()
        split = text.split("\n## ", 1)
        header = split[0]
        body = ("\n## " + split[1]) if len(split) > 1 else ""
    else:
        header = (
            "# PAPERS.md — weekly reading watch: HF blog + arXiv (candidates, NOT the inbox)\n\n"
            "_Generated by `scripts/fetch_papers.py` (weekly Actions cron). Newest first._\n"
        )
    OUT_PATH.write_text(header.rstrip() + "\n\n" + block + body)
    HF_SEEN_PATH.write_text(json.dumps(sorted(hf_seen | set(new_urls)), indent=0) + "\n")
    ARXIV_SEEN_PATH.write_text(json.dumps(sorted(arxiv_seen | set(new_ids)), indent=0) + "\n")
    print(f"papers: {len(new_urls)} HF post(s), {len(new_ids)} arXiv paper(s) → {OUT_PATH.name}")


if __name__ == "__main__":
    main()
