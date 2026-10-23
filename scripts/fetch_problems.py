#!/usr/bin/env python3
"""Fetch demand / problem signal for mimir.

The radar's trending source is *supply* — buildable tech and launched
solutions. This one is *demand*: unmet pain, "I wish X existed", complaints
about incumbents, manual work people pay to do. It feeds the problem side of
the daily digest.

Sources
-------
- **Hacker News** (Algolia API) — Ask HN threads + pain-phrase matches across
  stories and comments. No auth, no key. ALWAYS ON.
- **Reddit** (OAuth script app) — vertical + builder subreddits, top posts +
  pain-phrase search. Needs REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET env vars
  (free; one-time app registration — see progress.md). Skipped if unset.
- **Upwork** — NOT implemented. The public job feed is hard-blocked (HTTP 403);
  it's partner-API-only. See `UPWORK_NOTE` below for the realistic options.

Output
------
data/problems/<UTC-date>.jsonl — one JSON row per problem signal, `source`-tagged.
Stdlib only (urllib) so it runs in CI with no extra deps.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "problems"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW = int(time.time())
UA = "mimir-radar-problems/0.1 (demand-signal watch)"

# Phrases that signal latent demand rather than a finished solution.
import radar_config
PAIN_PHRASES = radar_config.get("sources", "hn_problems", "phrases", default=[
    "I wish there was", "is there a tool", "someone should build", "most tedious part",
    "biggest pain", "why is there no", "hate that I have to", "doing this manually",
])

# Reddit: vertical operators first (the demographic gap), then builders.
SUBREDDITS = radar_config.get("sources", "reddit", "subreddits", default=[
    "SaaS", "startups", "SomebodyMakeThis", "AppIdeas", "smallbusiness", "sysadmin",
])

UPWORK_NOTE = (
    "Upwork public job feed returns HTTP 403 (hard-blocked). No free scrape. "
    "Real options: (1) Upwork partner API — gated approval + OAuth; "
    "(2) headless-browser scrape — fragile, ToS-risky; "
    "(3) substitute validated-demand source. Not implemented."
)


def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# --------------------------------------------------------------------------- HN

def fetch_hn(days=21, min_points=80, per_query=20):
    """Ask HN threads + pain-phrase matches via the Algolia HN API."""
    cutoff = NOW - days * 86400
    rows, seen = [], set()

    def add(hit, kind, matched=None):
        oid = hit.get("objectID")
        if not oid or oid in seen:
            return
        seen.add(oid)
        title = hit.get("title") or hit.get("story_title") or ""
        text = (hit.get("comment_text") or hit.get("story_text") or "")
        rows.append({
            "source": "hn",
            "kind": kind,                       # 'ask_hn' | 'pain_match'
            "id": oid,
            "title": title.strip(),
            "snippet": _strip_html(text)[:400],
            "url": f"https://news.ycombinator.com/item?id={oid}",
            "points": hit.get("points"),
            "num_comments": hit.get("num_comments"),
            "author": hit.get("author"),
            "created_at": hit.get("created_at"),
            "matched": matched,
        })

    # 1) Recent, well-upvoted Ask HN threads.
    q = (f"https://hn.algolia.com/api/v1/search?tags=ask_hn"
         f"&numericFilters=points%3E{min_points},created_at_i%3E{cutoff}"
         f"&hitsPerPage={per_query}")
    try:
        for h in _get(q).get("hits", []):
            add(h, "ask_hn")
    except Exception as e:  # noqa: BLE001
        print(f"[hn] ask_hn query failed: {e}", file=sys.stderr)

    # 2) Pain-phrase matches across stories + comments.
    for phrase in PAIN_PHRASES:
        qp = urllib.parse.quote(f'"{phrase}"')
        url = (f"https://hn.algolia.com/api/v1/search?query={qp}"
               f"&tags=(story,comment)&numericFilters=created_at_i%3E{cutoff}"
               f"&hitsPerPage=10")
        try:
            for h in _get(url).get("hits", []):
                add(h, "pain_match", matched=phrase)
        except Exception as e:  # noqa: BLE001
            print(f"[hn] phrase '{phrase}' failed: {e}", file=sys.stderr)
        time.sleep(0.3)  # be polite to Algolia

    print(f"[hn] {len(rows)} signals "
          f"({sum(r['kind']=='ask_hn' for r in rows)} ask_hn, "
          f"{sum(r['kind']=='pain_match' for r in rows)} pain_match)")
    return rows


def _strip_html(s):
    # Algolia comment_text contains HTML entities + tags; cheap cleanup.
    import html
    import re
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


# ----------------------------------------------------------------------- Reddit

def fetch_reddit(per_sub=10):
    cid = os.environ.get("REDDIT_CLIENT_ID")
    secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        print("[reddit] REDDIT_CLIENT_ID/SECRET not set — skipping "
              "(see progress.md for one-time app setup)")
        return []

    # OAuth2 client-credentials (script app).
    import base64
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token", data=data,
        headers={"Authorization": f"Basic {auth}", "User-Agent": UA})
    try:
        token = json.load(urllib.request.urlopen(req, timeout=20))["access_token"]
    except Exception as e:  # noqa: BLE001
        print(f"[reddit] auth failed: {e}", file=sys.stderr)
        return []

    hdr = {"Authorization": f"Bearer {token}", "User-Agent": UA}
    rows = []
    for sub in SUBREDDITS:
        url = f"https://oauth.reddit.com/r/{sub}/top?t=week&limit={per_sub}"
        try:
            data = _get(url, headers=hdr)
            for c in data["data"]["children"]:
                d = c["data"]
                rows.append({
                    "source": "reddit",
                    "kind": "top_week",
                    "subreddit": sub,
                    "id": d.get("id"),
                    "title": (d.get("title") or "").strip(),
                    "snippet": (d.get("selftext") or "")[:400],
                    "url": "https://www.reddit.com" + d.get("permalink", ""),
                    "score": d.get("score"),
                    "num_comments": d.get("num_comments"),
                    "author": d.get("author"),
                    "created_at": datetime.fromtimestamp(
                        d.get("created_utc", 0), timezone.utc).isoformat(),
                })
        except Exception as e:  # noqa: BLE001
            print(f"[reddit] r/{sub} failed: {e}", file=sys.stderr)
        time.sleep(0.5)
    print(f"[reddit] {len(rows)} signals across {len(SUBREDDITS)} subs")
    return rows


# ------------------------------------------------------------------------- main

def main():
    print(f"[problems] fetch for {TODAY}")
    rows = []
    rows += fetch_hn()
    rows += fetch_reddit()
    print(f"[upwork] {UPWORK_NOTE}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{TODAY}.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[problems] wrote {len(rows)} rows -> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
