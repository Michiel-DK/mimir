# examples

One real week of feed, so the triage skill can be tried before the first cron run.

- `2026-10-19/papers.md` — the weekly papers section exactly as `scripts/fetch_papers.py` writes it
  (HF blog posts + arXiv items grouped by track; the tracks are the author's, yours will differ).
- `2026-10-19/arrivals.md` — the GitHub-trending arrivals for 2026-10-19 → 2026-10-21 exactly as
  `scripts/arrivals.py` writes them (18 repos, computed over 130 daily snapshots).

Try it:

```
cp radar.example.yaml radar.yaml          # or your own profile
# in your agent:  "run skills/radar-triage on examples/2026-10-19 against radar.yaml"
```

Expect most rows to be PARKED or NOT-ADOPT against the example profile; that is the point.
The output nobody else produces is "not now, reopen when X" against *your* lanes. Every item
here is public (arXiv, Hugging Face, GitHub). No verdicts are shipped with the examples, so the
skill's output is not anchored on the author's.
