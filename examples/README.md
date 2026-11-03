# examples

One real week of feed, so the triage skill can be tried before the first cron run.

- `2026-10-19/papers.md` — the weekly papers section exactly as `scripts/fetch_papers.py` writes it
  (HF blog posts + arXiv items grouped by track; the tracks are the author's, yours will differ).
- `2026-10-19/arrivals.md` — the GitHub-trending arrivals for 2026-10-19 → 2026-10-21 exactly as
  `scripts/arrivals.py` writes them (18 repos, computed over 130 daily snapshots). The window is
  the three days after the papers section; `days` counts snapshots in the full 130-day history, so a
  2 or 3 there means the repo really is new. Evidence you fetch today will show today's stars.
- `2026-10-19/VERDICTS.md`, `2026-10-19/pickup/` — the fresh agent's run (see below); the pickup
  blocks are what `handoff.py --dry-run --pickup-dir examples/2026-10-19/pickup` renders.
- `profiles/` — two more fictional profiles for projects unlike the example's, with what a fresh
  agent produced on each (see `profiles/README.md`).

Try it:

```
cp radar.example.yaml radar.yaml          # or your own profile
# in your agent:  "run skills/radar-triage on examples/2026-10-19 against radar.yaml"
python3 scripts/handoff.py --date 2026-10-19 --dry-run   # the notes your agent's triage would send

# or skip the agent and see the hand-off alone, on the shipped run's pickup blocks:
python3 scripts/handoff.py --date 2026-10-19 --dry-run --pickup-dir examples/2026-10-19/pickup
```

On a fresh clone with the example profile, pickup blocks written for *someone else's* lanes are
skipped with a `no lane ... in radar.yaml` warning; that is by design, not a bug.

Expect most rows to be PARKED or NOT-ADOPT against the example profile; that is the point.
The output nobody else produces is "not now, reopen when X" against *your* lanes. Every item
here is public (arXiv, Hugging Face, GitHub).

`VERDICTS.md` and `pickup/` in this folder are **one fresh agent's unedited run** of the skill on this
week against the example profile (Claude Opus, 2026-11-03, no session context, nothing cloned or
run). They show the output shape and the kind of call the skill produces. They are not a reference
answer: the author did not review the verdicts, and a second agent will disagree on some rows. Your
run on the same inputs is the test.
