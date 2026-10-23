"""Compute true GitHub-trending ARRIVALS over a window and write the triage input.

An arrival is a slug whose FIRST appearance in the full daily history falls inside
the window. This is not the same as compute_trends.py's "newcomers" (first seen
today): a repo that entered on day 1 of a 7-day window is still an arrival for the
week's triage, and a repo that has been on the list for 40 days is not an arrival
even if it is new to this week's window. See TRAPS.md: "arrivals, not newcomers".

Reads:   data/daily/YYYY-MM-DD.jsonl   (every snapshot, the whole history)
Writes:  data/arrivals/<until>.md      (the table radar-triage expects as input 2)
         data/arrivals/<until>.json    (same rows, machine-readable)

Run:  python3 scripts/arrivals.py --since 2026-10-19            # [since, latest], since = day after last triage
      python3 scripts/arrivals.py --since 2026-10-13 --until 2026-10-18
      python3 scripts/arrivals.py                                # last 7 days

Exit 0 on success, 1 when no snapshots exist. A history shorter than 30 days makes
nearly everything an arrival; the header says how long the history is so the reader
can weigh `days`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "data" / "daily"
OUT_DIR = ROOT / "data" / "arrivals"

HISTORY_WARN_DAYS = 30
DESC_MAX = 160


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def list_snapshots(daily_dir: Path) -> list[tuple[date, Path]]:
    out = []
    for p in sorted(daily_dir.glob("*.jsonl")):
        try:
            out.append((date.fromisoformat(p.stem), p))
        except ValueError:
            continue
    return out


def compute_arrivals(snapshots: list[tuple[date, Path]], since: date, until: date) -> tuple[list[dict], dict]:
    """Return (arrival rows, history info). Window is [since, until], both inclusive."""
    first_seen: dict[str, date] = {}
    days_seen: dict[str, int] = {}
    latest_row: dict[str, dict] = {}
    for d, path in snapshots:
        if d > until:
            break
        for repo in load_jsonl(path):
            slug = repo.get("slug")
            if not slug:
                continue
            first_seen.setdefault(slug, d)
            days_seen[slug] = days_seen.get(slug, 0) + 1
            prev = latest_row.get(slug, {})
            # newest non-empty value per field wins; an API miss on a later day keeps the earlier licence/created_at
            latest_row[slug] = {**prev, **{k: v for k, v in repo.items() if v not in (None, "")}}

    rows = []
    for slug, fs in first_seen.items():
        if since <= fs <= until:
            r = latest_row[slug]
            desc = (r.get("api_description") or r.get("description") or "").replace("|", "\\|").replace("\n", " ")
            rows.append({
                "slug": slug,
                "url": f"https://github.com/{slug}",
                "stars": r.get("stars"),
                "language": r.get("language") or r.get("language_hint"),
                "license_key": r.get("license") or "unknown",
                "created_at": (r.get("created_at") or "")[:10] or None,
                "pushed_at": (r.get("pushed_at") or "")[:10] or None,
                "first_seen": fs.isoformat(),
                "days_seen": days_seen[slug],
                "description": desc[:DESC_MAX],
            })
    rows.sort(key=lambda r: -(r["stars"] or 0))
    info = {
        "history_start": snapshots[0][0].isoformat(),
        "history_end": min(snapshots[-1][0], until).isoformat(),
        "snapshots": sum(1 for d, _ in snapshots if d <= until),
        "window": [since.isoformat(), until.isoformat()],
    }
    return rows, info


def render_md(rows: list[dict], info: dict) -> str:
    since, until = info["window"]
    lines = [
        f"# GitHub trending arrivals {since} → {until}",
        "",
        f"True arrivals = first appearance in the full daily history "
        f"({info['snapshots']} snapshots, {info['history_start']} → {info['history_end']}). "
        f"`days` = snapshots in the full history, not in the window. "
        f"Licence key is GitHub's; `other`/`NOASSERTION`/`unknown` = unknown until the files are read "
        f"(see TRAPS.md). `created_at` is the repo's age, not its arrival.",
        "",
    ]
    hist_days = (date.fromisoformat(info["history_end"]) - date.fromisoformat(info["history_start"])).days
    if hist_days < HISTORY_WARN_DAYS:
        lines += [f"⚠️ History is only {hist_days} days long; most repos will look like arrivals. "
                  f"Treat `days` and this list as weak until the history passes {HISTORY_WARN_DAYS} days.", ""]
    lines += [
        f"{len(rows)} arrivals.",
        "",
        "| slug | stars | lang | licence key | created_at | days | description |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['slug']} | {r['stars']} | {r['language']} | {r['license_key']} | "
            f"{r['created_at']} | {r['days_seen']} | {r['description']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", help="window start, INCLUSIVE (YYYY-MM-DD) = the day after your last triage; default = until − 6 days")
    ap.add_argument("--until", help="window end, inclusive; default = latest snapshot")
    ap.add_argument("--daily-dir", default=str(DAILY_DIR))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--stdout", action="store_true", help="print the markdown, write nothing")
    args = ap.parse_args(argv)

    snapshots = list_snapshots(Path(args.daily_dir))
    if not snapshots:
        print(f"[arrivals] no snapshots in {args.daily_dir}", file=sys.stderr)
        return 1
    until = date.fromisoformat(args.until) if args.until else snapshots[-1][0]
    since = date.fromisoformat(args.since) if args.since else until - timedelta(days=6)
    if since > until:
        print(f"[arrivals] --since {since} must not be after --until {until}", file=sys.stderr)
        return 2

    rows, info = compute_arrivals(snapshots, since, until)
    md = render_md(rows, info)
    if args.stdout:
        print(md)
        return 0
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{until}.md").write_text(md, encoding="utf-8")
    (out_dir / f"{until}.json").write_text(
        json.dumps({"info": info, "arrivals": rows}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[arrivals] {len(rows)} arrivals in [{since}, {until}] over {info['snapshots']} snapshots "
          f"→ {out_dir / f'{until}.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
