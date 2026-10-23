"""Diff today's snapshot against history; classify repos and write rolling top-N.

Inputs: data/daily/YYYY-MM-DD.jsonl files (last 30 used for rolling window).
Outputs:
  data/seen.json — for every slug ever seen: first_seen, last_seen, days_seen,
                   max_stars, latest stars / stars_today / sources.
  data/rolling/top-30d.json — top N by stars_gained over the trailing 30 days,
                              plus today's newcomers, climbers, persisters.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "data" / "daily"
ROLLING_DIR = ROOT / "data" / "rolling"
SEEN_PATH = ROOT / "data" / "seen.json"
WINDOW_DAYS = 30
TOP_N = 25


def load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def list_snapshots() -> list[tuple[str, Path]]:
    files = sorted(DAILY_DIR.glob("*.jsonl"))
    return [(p.stem, p) for p in files]


def main() -> int:
    snapshots = list_snapshots()
    if not snapshots:
        print("[trends] no daily snapshots found; nothing to compute", file=sys.stderr)
        return 1

    today_date, today_path = snapshots[-1]
    today = load_jsonl(today_path)
    today_by_slug = {r["slug"]: r for r in today}

    # ---- Update seen.json ----
    seen: dict[str, dict] = {}
    if SEEN_PATH.exists():
        seen = json.loads(SEEN_PATH.read_text())

    for date_str, path in snapshots:
        for repo in load_jsonl(path):
            slug = repo["slug"]
            entry = seen.setdefault(slug, {
                "slug": slug,
                "first_seen": date_str,
                "last_seen": date_str,
                "days_seen": 0,
                "seen_dates": [],
                "max_stars": 0,
                "max_stars_today": 0,
            })
            if date_str not in entry["seen_dates"]:
                entry["seen_dates"].append(date_str)
                entry["days_seen"] = len(entry["seen_dates"])
            entry["last_seen"] = max(entry["last_seen"], date_str)
            entry["first_seen"] = min(entry["first_seen"], date_str)
            if repo.get("stars"):
                entry["max_stars"] = max(entry["max_stars"], repo["stars"])
            if repo.get("stars_today"):
                entry["max_stars_today"] = max(entry["max_stars_today"], repo["stars_today"])

    # Annotate seen with today's snapshot for the latest fields
    for slug, repo in today_by_slug.items():
        entry = seen[slug]
        entry["latest_stars"] = repo.get("stars")
        entry["latest_stars_today"] = repo.get("stars_today")
        entry["latest_sources"] = repo.get("sources", [])
        entry["description"] = repo.get("api_description") or repo.get("description")
        entry["language"] = repo.get("language")
        entry["license"] = repo.get("license")

    SEEN_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True))
    print(f"[trends] seen.json: {len(seen)} unique slugs across {len(snapshots)} snapshots")

    # ---- Classify today's repos ----
    today_dt = dt.date.fromisoformat(today_date)
    window_start = today_dt - dt.timedelta(days=WINDOW_DAYS - 1)
    in_window = [
        (d, p) for d, p in snapshots
        if dt.date.fromisoformat(d) >= window_start
    ]

    # stars_gained_30d for each slug = sum of stars_today across the window
    stars_gained: dict[str, int] = {}
    days_in_window: dict[str, int] = {}
    for date_str, path in in_window:
        for repo in load_jsonl(path):
            slug = repo["slug"]
            stars_gained[slug] = stars_gained.get(slug, 0) + (repo.get("stars_today") or 0)
            days_in_window[slug] = days_in_window.get(slug, 0) + 1

    def card(slug: str) -> dict:
        repo = today_by_slug.get(slug, {})
        entry = seen.get(slug, {})
        return {
            "slug": slug,
            "url": f"https://github.com/{slug}",
            "description": repo.get("api_description") or repo.get("description") or entry.get("description"),
            "language": repo.get("language") or entry.get("language"),
            "stars": repo.get("stars") or entry.get("latest_stars"),
            "stars_today": repo.get("stars_today"),
            "stars_gained_window": stars_gained.get(slug, 0),
            "days_in_window": days_in_window.get(slug, 0),
            "first_seen": entry.get("first_seen"),
            "days_seen": entry.get("days_seen"),
            "sources": repo.get("sources", []),
        }

    newcomers = [
        card(r["slug"]) for r in today
        if seen[r["slug"]]["first_seen"] == today_date
    ]
    persisters = [
        card(r["slug"]) for r in today
        if seen[r["slug"]]["days_seen"] >= 3
    ]
    persisters.sort(key=lambda r: -(r["days_seen"] or 0))

    # Climbers: in today's snapshot, ranked by stars_today
    climbers = sorted(
        [card(r["slug"]) for r in today],
        key=lambda r: -(r["stars_today"] or 0),
    )[:TOP_N]

    # Rolling top-N over window by stars_gained_window
    rolling_top = sorted(
        [card(slug) for slug in stars_gained],
        key=lambda r: -(r["stars_gained_window"] or 0),
    )[:TOP_N]

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "today": today_date,
        "window_days": WINDOW_DAYS,
        "snapshot_count": len(snapshots),
        "total_repos_today": len(today),
        "newcomers": newcomers,
        "climbers": climbers,
        "persisters": persisters[:TOP_N],
        "rolling_top": rolling_top,
    }
    ROLLING_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ROLLING_DIR / f"top-{WINDOW_DAYS}d.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[trends] wrote {out_path}")
    print(f"  newcomers: {len(newcomers)}  climbers: {len(climbers)}  persisters≥3d: {len(persisters)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
