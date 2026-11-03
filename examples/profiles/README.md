# examples/profiles — two more fictional profiles, for the transfer test

The shipped week (`examples/2026-10-19/`) was fetched with the tracks of a team that builds agents,
evals and serving. These two profiles are for projects unlike that, so you can check that the skill
gives honest verdicts relative to lanes the feed was never fetched for.

- `radar.datashop.yaml` — a two-person data consultancy, no AI product, no GPU: dbt checks, a CPU-only
  invoice-extraction job, static client reports.
- `radar.indieapp.yaml` — a solo developer shipping an iOS journaling app with an on-device assistant:
  models ≤ 2B, a 1.2 GB download budget, a no-revenue-cap licence rule, offline speech input.

One fresh agent's run on each against the shipped week (Claude Opus, 2026-11-03, unedited, not a
reference answer):

| profile | promoted | rows | pickup notes | hand-off dry run |
|---|---|---|---|---|
| datashop | 0 | 4, all NOT-ADOPT | none | "nothing to hand off" |
| indieapp | 1 narrow (a 470M speech model, three unmet preconditions stated) | 6 | 1 | 1 note |

Try one: `cp examples/profiles/radar.indieapp.yaml radar.yaml`, then run the skill on
`examples/2026-10-19` as in the quickstart. Expect "nothing for you" rows; the point is that they say
why, against *these* constraints, and what would reopen them. For a real run, fetch the feed with the
profile's own `tracks:` first.
