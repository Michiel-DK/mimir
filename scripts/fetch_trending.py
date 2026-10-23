"""Fetch GitHub trending (overall + selected languages) and enrich each repo via the GitHub API.

Output: data/daily/YYYY-MM-DD.jsonl, one JSON object per repo with:
  slug, owner, name, url, description, language, stars, stars_today,
  forks, license, pushed_at, created_at, topics, readme_excerpt,
  source ("overall" | "lang:python" | ...), fetched_at.

Reads GITHUB_TOKEN from env or `gh auth token` for authenticated API calls.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "data" / "daily"
import radar_config
_SLICES = radar_config.get("sources", "github_trending", "slices", default=["overall", "python", "typescript", "rust", "go"])
LANGUAGES = ["" if s == "overall" else s for s in _SLICES]  # "" = overall
TRENDING_URL = "https://github.com/trending/{lang}?since=daily"
USER_AGENT = "mimir-radar/0.1 (github trending watch)"
README_MAX_CHARS = 2000
SLICE_ATTEMPTS = 3      # per-slice retries; a slice that parses 0 rows is retried too
SLICE_BACKOFF_S = 4     # linear backoff between attempts (4s, 8s)


def github_token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        out = subprocess.check_output(["gh", "auth", "token"], stderr=subprocess.DEVNULL, text=True)
        return out.strip() or None
    except Exception:
        return None


def session(token: str | None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def parse_trending(html: str, source: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for rank, art in enumerate(soup.select("article.Box-row"), start=1):
        h2 = art.select_one("h2 a")
        if not h2 or not h2.get("href"):
            continue
        slug = h2["href"].strip("/")
        if "/" not in slug:
            continue
        owner, name = slug.split("/", 1)

        desc_el = art.select_one("p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        # Footer line: language span, total stars, forks, "N stars today"
        lang_el = art.select_one("span[itemprop='programmingLanguage']")
        language = lang_el.get_text(strip=True) if lang_el else None

        stars_today = None
        for span in art.select("span.d-inline-block"):
            txt = span.get_text(" ", strip=True)
            m = re.match(r"([\d,]+)\s+stars\s+today", txt)
            if m:
                stars_today = int(m.group(1).replace(",", ""))
                break

        out.append({
            "slug": slug,
            "owner": owner,
            "name": name,
            "url": f"https://github.com/{slug}",
            "description": description,
            "language_hint": language,
            "stars_today": stars_today,
            "rank_in_source": rank,
            "source": source,
        })
    return out


def fetch_slice(s: requests.Session, lang: str, src: str) -> tuple[list[dict], str | None]:
    """Fetch ONE trending slice, with retries. Returns (repos, error_or_None).

    Two distinct failure modes both used to vanish here (see the 2026-09-15 audit):
      (a) the request errors / non-2xx  -> warning printed, slice skipped;
      (b) the request 200s but `parse_trending` yields ZERO rows -> NO warning at all,
          the slice just silently contributes nothing.
    Between 2026-09-01 and 2026-09-14, ten of sixteen days were missing at least one
    slice and `overall` -- the highest-signal one -- was absent on eight, while the
    workflow reported success every single day. So **zero rows is treated as a
    failure and is retried**, not accepted.
    """
    url = TRENDING_URL.format(lang=lang)
    last_err: str | None = None
    for attempt in range(1, SLICE_ATTEMPTS + 1):
        try:
            r = s.get(url, timeout=20)
            r.raise_for_status()
            repos = parse_trending(r.text, src)
            if repos:
                if attempt > 1:
                    print(f"  {src}: {len(repos)} repos (recovered on attempt {attempt})")
                else:
                    print(f"  {src}: {len(repos)} repos")
                return repos, None
            last_err = f"HTTP {r.status_code} but 0 rows parsed (len={len(r.text)})"
        except Exception as e:  # noqa: BLE001 - any transport/HTTP failure is retryable
            last_err = f"{type(e).__name__}: {e}"
        if attempt < SLICE_ATTEMPTS:
            backoff = SLICE_BACKOFF_S * attempt
            print(f"  [retry] {src} attempt {attempt}/{SLICE_ATTEMPTS} failed "
                  f"({last_err}); sleeping {backoff}s", file=sys.stderr)
            time.sleep(backoff)
    return [], last_err


def fetch_trending_all() -> tuple[dict[str, dict], dict[str, str | None]]:
    """Fetch trending for every configured language; dedupe by slug, keep best rank/source.

    Returns (by_slug, slice_status) where slice_status maps each source name to None
    (ok) or an error string. The caller is responsible for reporting failures LOUDLY --
    this function still returns whatever it got, because a partial snapshot is worth
    more than no snapshot (dropping out here would also skip demand + traction + the
    commit, which all run in the same workflow step).
    """
    by_slug: dict[str, dict] = {}
    slice_status: dict[str, str | None] = {}
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    for lang in LANGUAGES:
        src = "overall" if not lang else f"lang:{lang}"
        repos, err = fetch_slice(s, lang, src)
        slice_status[src] = err
        if err:
            print(f"  [warn] slice {src} FAILED after {SLICE_ATTEMPTS} attempts: {err}",
                  file=sys.stderr)
        for repo in repos:
            existing = by_slug.get(repo["slug"])
            if existing is None:
                repo["sources"] = [repo.pop("source")]
                by_slug[repo["slug"]] = repo
            else:
                existing["sources"].append(repo["source"])
                # keep the best (lowest) rank
                existing["rank_in_source"] = min(existing["rank_in_source"], repo["rank_in_source"])
        time.sleep(0.3)  # be polite to github.com
    return by_slug, slice_status


def enrich(repo: dict, api: requests.Session) -> dict:
    slug = repo["slug"]
    try:
        r = api.get(f"https://api.github.com/repos/{slug}", timeout=20)
        if r.status_code == 404:
            repo["enrich_error"] = "404"
            return repo
        r.raise_for_status()
        d = r.json()
        repo["stars"] = d.get("stargazers_count")
        repo["forks"] = d.get("forks_count")
        repo["watchers"] = d.get("subscribers_count")
        repo["language"] = d.get("language") or repo.get("language_hint")
        repo["license"] = (d.get("license") or {}).get("spdx_id")
        repo["pushed_at"] = d.get("pushed_at")
        repo["created_at"] = d.get("created_at")
        repo["topics"] = d.get("topics") or []
        repo["default_branch"] = d.get("default_branch")
        repo["open_issues"] = d.get("open_issues_count")
        repo["archived"] = d.get("archived", False)
        repo["api_description"] = d.get("description")
    except Exception as e:
        repo["enrich_error"] = str(e)
        return repo

    # README excerpt (markdown, decoded)
    try:
        rr = api.get(
            f"https://api.github.com/repos/{slug}/readme",
            headers={"Accept": "application/vnd.github.raw"},
            timeout=20,
        )
        if rr.status_code == 200:
            text = rr.text
            # strip HTML comments + collapse blank runs to keep excerpt readable
            text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            repo["readme_excerpt"] = text[:README_MAX_CHARS]
        elif rr.status_code != 404:
            repo["readme_error"] = f"status {rr.status_code}"
    except Exception as e:
        repo["readme_error"] = str(e)

    return repo


def main() -> int:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DAILY_DIR / f"{today}.jsonl"

    print(f"[fetch] scraping github.com/trending for {LANGUAGES}…")
    by_slug, slice_status = fetch_trending_all()
    print(f"[fetch] {len(by_slug)} unique repos after dedup")

    token = github_token()
    if not token:
        print("[warn] no GITHUB_TOKEN found (or `gh auth token`); enrichment will be unauthenticated and may hit rate limits", file=sys.stderr)
    api = session(token)

    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
    enriched: list[dict] = []
    for i, (slug, repo) in enumerate(by_slug.items(), start=1):
        print(f"  [{i}/{len(by_slug)}] {slug}")
        repo["fetched_at"] = fetched_at
        enriched.append(enrich(repo, api))

    # Sort by stars_today desc (None last), then stars desc
    enriched.sort(key=lambda r: (-(r.get("stars_today") or 0), -(r.get("stars") or 0)))

    with out_path.open("w") as f:
        for repo in enriched:
            f.write(json.dumps(repo, ensure_ascii=False) + "\n")
    print(f"[fetch] wrote {out_path} ({len(enriched)} repos)")

    # --- slice-coverage sidecar + loud reporting -------------------------------
    # Written as .meta.json so it never shows up in the `data/daily/*.jsonl` globs
    # every downstream reader uses. This is what lets a later digest tell a real
    # absence ("the repo left trending") from a fetch gap ("we never asked") --
    # the distinction `radar-data-reading-traps` says to check per repo, now
    # recorded per day at the coverage level.
    failed = {src: err for src, err in slice_status.items() if err}
    meta = {
        "date": today,
        "fetched_at": fetched_at,
        "slices_expected": [("overall" if not l else f"lang:{l}") for l in LANGUAGES],
        "slices_ok": sorted(src for src, err in slice_status.items() if not err),
        "slices_failed": failed,
        "complete": not failed,
        "unique_repos": len(enriched),
    }
    meta_path = DAILY_DIR / f"{today}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"[fetch] wrote {meta_path} (complete={meta['complete']})")

    if failed:
        # GitHub Actions annotation: surfaces on the run page in red WITHOUT failing
        # the step. Exiting non-zero here would abort the whole step and skip
        # compute_trends, fetch_problems, fetch_traction AND the commit/push --
        # turning a partial day into a zero-data day. Write first, shout second.
        detail = "; ".join(f"{src} ({err})" for src, err in sorted(failed.items()))
        print(f"::error title=Incomplete trending snapshot::{today}: "
              f"{len(failed)} of {len(LANGUAGES)} slices failed after {SLICE_ATTEMPTS} "
              f"attempts — {detail}. Snapshot written with {len(enriched)} repos but is "
              f"NOT comparable to a complete day.")
        print(f"[fetch] ⚠️  INCOMPLETE: missing {sorted(failed)}", file=sys.stderr)
    else:
        print(f"[fetch] all {len(LANGUAGES)} slices ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
