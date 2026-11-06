# mimir

**Verdicts on new tech, relative to your own repos, each with a reopen threshold.**

Paper bots and trending feeds tell you what is new. Mimir tells you what, if anything, it changes in
*your* lanes, and when to look again. The output nobody else ships is the row that says
`PARKED — reopen when the laptop tier is memory-bound at 4k prompts`.

Named after the counsellor Odin consults before deciding. Status: **v0**.

**This is a public rework of a private project.** The author has run a private radar daily since
mid-2026. This repo is that radar re-cut so that anyone with a `radar.yaml` can reproduce the
judgement. The author's real profile, verdicts and pickup notes stay in a private repo; what ships
here is a fictional profile (`radar.example.yaml`), one real week of feed, and one fresh agent's
unedited run of the skill on that week (`examples/2026-10-19/`). `VERDICTS.md` and `pickup/` at the
root are empty on purpose: they are where *your* triage writes.

## How it works

**The public repo is the tool, not the tracker.** It ships the fetchers, the skills and one example
week (`examples/2026-10-19/`). You run the fetchers on your own schedule; the author's tracking runs
in a private instance. The Actions below have no `schedule:` trigger here (`workflow_dispatch` only),
so nothing updates this repo on its own. The snapshots under `data/` end on 2026-11-06, the date of
this change.

```
radar.yaml  ─┐
             ├─▶  weekly feed (papers + launch posts + trending arrivals)
fetchers    ─┘                 │
                               ▼
                  skills/radar-triage  (your agent runs it)
                               │
                 ┌─────────────┴─────────────┐
                 ▼                           ▼
            VERDICTS.md                pickup/<lane>.md
   (dated sections, newest first)   (one note per lane an agent can act on)
                                             │
                                             ▼
                                   scripts/handoff.py
                                 (one issue or docs PR per lane, on that lane's repo)
```

1. **Profile.** `radar.yaml` holds your *lanes*: one per question you are actually working or have
   parked, with what exists, the lists a candidate can land on, the words you use, what would reopen
   the lane, and what is explicitly not now. Draft it with `skills/radar-profile`, then review and
   commit it. Verdicts come from this file and the fetched evidence only, never from a live read of
   your repos.
2. **Fetch.** Two GitHub Actions (manual-dispatch here; add a `schedule:` in your own fork or run the scripts from cron): daily trending (per language slice, with retries and a coverage
   sidecar so a silently missing slice is loud) and weekly papers (Hugging Face blog + arXiv through
   OpenAlex, queries from your `tracks`). Demand signals from Hacker News are optional.
   **In CI there is no profile** (`radar.yaml` is git-ignored), so the Actions fetch with built-in
   default queries; that is why this repo's own `PAPERS.md` has generic track names. To fetch with
   your tracks, either run the fetchers where your profile lives, or commit a queries-only profile
   (e.g. `radar.tracks.yaml`: `tracks:` and `sources:`, no lanes) and set the repository variable
   `RADAR_YAML` to its path. The arrivals list is weak until `data/daily` holds ~30 snapshots; the
   file says so in its header.
3. **Triage.** Your agent (Claude Code or anything that reads a `SKILL.md`) runs
   `skills/radar-triage` on the new section. The rules live in the skill, not in prose: every row
   cites a saved artefact, abstract-only reads are labelled, licence files are read at every tree
   depth before any verdict stronger than PARKED, every verdict carries a reopen threshold, and
   nothing is cloned or run unless you say so.
4. **Pick up.** Each lane that moved gets a block in `pickup/<lane>.md`. Triage opens no work by
   itself.
5. **Hand off.** `python3 scripts/handoff.py --date <triage date>` carries each new block to the
   lane's own repo: one issue per lane by default (a reading note, with the lane's question and a
   link back to the verdict section), or a docs file on a dated branch as a PR. `--dry-run` prints
   every note first. Commit and push `VERDICTS.md` and `pickup/` before the real send: each note
   links to the section on `main` (or to `handoff.verdicts_url` if your verdicts live in another repo),
   and the script refuses to send while they are uncommitted. `--pickup-dir` points it at a pickup
   folder outside this checkout, e.g. a private radar repo. A ledger under `data/handoff/` makes re-runs open nothing twice, and the
   leak gate runs on every body before it leaves the machine. The agent working in that repo
   finds the note where it works, not here.

## Quickstart

```
git clone https://github.com/Michiel-DK/mimir && cd mimir
pip install -r requirements.txt
cp radar.example.yaml radar.yaml           # then edit, or run skills/radar-profile against your repos

# try the triage now, on a shipped week of real feed (no cron needed):
#   in your agent: "run skills/radar-triage on examples/2026-10-19 against radar.yaml"

# your own feed, from the second week on:
python3 scripts/fetch_trending.py && python3 scripts/compute_trends.py   # daily (on your own schedule)
python3 scripts/fetch_papers.py            # weekly; OPENALEX_API_KEY optional
python3 scripts/fetch_feeds.py             # weekly, after fetch_papers; reads sources.feeds / pages / problems_digest
python3 scripts/arrivals.py --since <day after your last triage>          # → data/arrivals/<date>.md
#   in your agent: "run skills/radar-triage on the newest PAPERS.md section + data/arrivals/<date>.md"
python3 scripts/handoff.py --date <date> --dry-run   # then without --dry-run: one issue per moved lane, on its repo
python3 scripts/handoff.py --date 2026-10-19 --dry-run --pickup-dir examples/2026-10-19/pickup   # hand-off on the shipped run, no agent needed

# the skill cites evidence it fetched; this does the fetching and the licence walk:
python3 scripts/evidence.py --date <date> 2610.18813 hf:org/model owner/repo https://huggingface.co/blog/...

python3 -m unittest discover -s tests      # no network
```

Two things the scripts guarantee that the prose cannot: `arrivals.py` computes **arrivals**
(first appearance in the full history), not "newcomers" (first seen today), and `evidence.py`
reads **every** LICENSE/COPYING file at every tree depth and flags a mixed or missing licence.
Both traps cost real triage weeks before they became functions (see TRAPS.md).

## What the triage will and will not claim

- **Evidence scope on every verdict:** `(abstract)`, `(body read)`, `(post read; benchmarks are the vendor's)`, `(README + licence files, not run)`.
- **Licence at every depth.** `other` means unknown until the files are read. One LICENSE in a
  sub-directory can change the verdict. The gate caught a repo whose LICENSE was a notice saying the
  code derived from proprietary source while the README badge said MIT.
- **Arrivals, not newcomers.** New in this week's window is not new; new in the full history is.
- **Kill clause per source.** Two consecutive triages with zero promotions from a source and the
  source gets a strike. Feeds that never move anything should be dropped, not tolerated.
- Read `TRAPS.md` before trusting any number.

## Does the judgement transfer?

Tested before this repo was created: two fresh agents with no session context, given only
`radar.yaml`, the triage skill, and one week's feed each, reproduced the author's hand triage on the
author's six repos at **5 of 5** and **5 of 6** promotes, with 0 and 2 false promotes. Both agents
reported the same profile gaps, which became the checklist in `skills/radar-profile`. Pass marks
were written down before the runs.

## Honest notes

- GitHub trending has no API; the fetcher parses the HTML page. Keep the request rate as shipped.
- arXiv is read through OpenAlex because arXiv's own API throttles CI runners.
- There is no hosted service, dashboard, memory graph or autonomous digest, and none is planned.
- Cost is roughly one agent session per week. Fetching is free.
- The hand-off is deterministic and runs after the session: it posts what the agent wrote, it does
  not judge. It needs `gh` with write access to the lanes' repos; `.github/workflows/handoff.yml`
  is a manual trigger for the same step, dry-run by default.
- Leak gate: `scripts/leak_gate.py` blocks a publish on secret shapes and on your own banned terms.
  Run it on anything that leaves the repo.

## Layout

```
radar.yaml              your profile (git-ignored by choice; radar.example.yaml is the shape)
scripts/fetch_trending.py   GitHub trending → data/daily/<date>.jsonl (+ .meta.json coverage)
scripts/compute_trends.py   daily diff: newcomers / climbers / persisters, rolling top-N
scripts/fetch_papers.py     HF blog + arXiv (OpenAlex) by track → PAPERS.md section
scripts/fetch_feeds.py      any RSS/Atom feed, a watched page's diff, the HN problems digest → extra `###` sections in the same PAPERS.md block
scripts/fetch_problems.py   demand signals (best effort) → data/problems/
scripts/arrivals.py         true arrivals over a window → data/arrivals/<date>.md  (triage input 2)
scripts/evidence.py         arXiv / HF model / HF blog / GitHub + licence-at-every-depth → evidence/<date>/
scripts/handoff.py          pickup blocks → one issue / docs PR per lane on the lane's repo; ledger in data/handoff/
scripts/leak_gate.py        blocks secrets and your banned terms (leakgate.txt) before a push
scripts/radar_config.py     the loader every fetcher reads radar.yaml through
skills/radar-triage/    the triage procedure and its non-optional rules
skills/radar-profile/   how to draft radar.yaml from a repo tree
examples/2026-10-19/    one real week (papers section + arrivals) to try the skill on
tests/                  smoke tests, no network; .github/workflows/ci.yml runs them
TEMPLATE.md             the output shape and verdict vocabulary
TRAPS.md                how the data lies
```
