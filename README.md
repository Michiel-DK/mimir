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

```bash
git clone <this repo> && cd mimir
pip install -r requirements.txt
cp radar.example.yaml radar.yaml           # then edit, or run skills/radar-profile against your repos
cp leakgate.example.txt leakgate.txt       # your banned terms, git-ignored
python3 scripts/fetch_trending.py && python3 scripts/compute_trends.py
python3 scripts/fetch_papers.py            # OPENALEX_API_KEY optional
# now run the radar-triage skill on the new PAPERS.md section + data/daily arrivals
```

Enable the two workflows in `.github/workflows/` to run the fetchers on a schedule.

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
radar.example.yaml      the profile format, filled in for a fictional team
TEMPLATE.md             one triage section, and the fixed verdict vocabulary
TRAPS.md                thirteen ways this data lies
skills/radar-triage/    the triage procedure and its non-optional rules
skills/radar-profile/   how to draft radar.yaml from a repo tree
scripts/                fetch_trending, compute_trends, fetch_problems, fetch_papers, leak_gate, radar_config
.github/workflows/      daily-radar, weekly-papers
data/ pickup/ evidence/ outputs
```

Apache-2.0.
