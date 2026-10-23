# mimir

**Verdicts on new tech, relative to your own repos, each with a reopen threshold.**

Paper bots and trending feeds tell you what is new. Mimir tells you what, if anything, it changes in
*your* lanes, and when to look again. The output nobody else ships is the row that says
`PARKED — reopen when the laptop tier is memory-bound at 4k prompts`.

Named after the counsellor Odin consults before deciding. Status: **v0**, extracted from a private
radar the author has run daily since mid-2026.

## How it works

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
```

1. **Profile.** `radar.yaml` holds your *lanes*: one per question you are actually working or have
   parked, with what exists, the lists a candidate can land on, the words you use, what would reopen
   the lane, and what is explicitly not now. Draft it with `skills/radar-profile`, then review and
   commit it. Verdicts come from this file and the fetched evidence only, never from a live read of
   your repos.
2. **Fetch.** Two GitHub Actions: daily trending (per language slice, with retries and a coverage
   sidecar so a silently missing slice is loud) and weekly papers (Hugging Face blog + arXiv through
   OpenAlex, queries from your `tracks`). Demand signals from Hacker News are optional.
3. **Triage.** Your agent (Claude Code or anything that reads a `SKILL.md`) runs
   `skills/radar-triage` on the new section. The rules live in the skill, not in prose: every row
   cites a saved artefact, abstract-only reads are labelled, licence files are read at every tree
   depth before any verdict stronger than PARKED, every verdict carries a reopen threshold, and
   nothing is cloned or run unless you say so.
4. **Pick up.** Each lane that moved gets a block in `pickup/<lane>.md`. Hand that to the agent
   working in that repo. Triage opens no work by itself.

## Quickstart

```
git clone https://github.com/Michiel-DK/mimir && cd mimir
pip install -r requirements.txt
cp radar.example.yaml radar.yaml           # then edit, or run skills/radar-profile against your repos

# try the triage now, on a shipped week of real feed (no cron needed):
#   in your agent: "run skills/radar-triage on examples/2026-10-19 against radar.yaml"

# your own feed, from the second week on:
python3 scripts/fetch_trending.py && python3 scripts/compute_trends.py   # daily (or let daily.yml run it)
python3 scripts/fetch_papers.py            # weekly; OPENALEX_API_KEY optional
python3 scripts/arrivals.py --since <day after your last triage>          # → data/arrivals/<date>.md
#   in your agent: "run skills/radar-triage on the newest PAPERS.md section + data/arrivals/<date>.md"

# the skill cites evidence it fetched; this does the fetching and the licence walk:
python3 scripts/evidence.py 2610.18813 hf:org/model owner/repo https://huggingface.co/blog/...

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
- Leak gate: `scripts/leak_gate.py` blocks a publish on secret shapes and on your own banned terms.
  Run it on anything that leaves the repo.

## Layout

```
radar.yaml              your profile (git-ignored by choice; radar.example.yaml is the shape)
scripts/fetch_trending.py   GitHub trending → data/daily/<date>.jsonl (+ .meta.json coverage)
scripts/compute_trends.py   daily diff: newcomers / climbers / persisters, rolling top-N
scripts/fetch_papers.py     HF blog + arXiv (OpenAlex) by track → PAPERS.md section
scripts/fetch_problems.py   demand signals (best effort) → data/problems/
scripts/arrivals.py         true arrivals over a window → data/arrivals/<date>.md  (triage input 2)
scripts/evidence.py         arXiv / HF model / HF blog / GitHub + licence-at-every-depth → evidence/<date>/
scripts/leak_gate.py        blocks secrets and your banned terms (leakgate.txt) before a push
scripts/radar_config.py     the loader every fetcher reads radar.yaml through
skills/radar-triage/    the triage procedure and its non-optional rules
skills/radar-profile/   how to draft radar.yaml from a repo tree
examples/2026-10-19/    one real week (papers section + arrivals) to try the skill on
tests/                  smoke tests, no network; .github/workflows/ci.yml runs them
TEMPLATE.md             the output shape and verdict vocabulary
TRAPS.md                how the data lies
```
