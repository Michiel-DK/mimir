---
name: radar-triage
description: Triage a week of papers, launch posts and GitHub trending arrivals against the lanes in radar.yaml and write verdict rows with reopen thresholds plus one pickup note per lane. Use when a new feed section or a list of trending arrivals needs judging relative to the user's own repos.
---

# radar-triage

You are judging a week of new tech **relative to the lanes in `radar.yaml`**, not in general. The output nobody else produces is "not now, reopen when X", stated against the user's own code. Fetching is commodity; the judgement is the product. Verdicts come from `radar.yaml` and the fetched evidence only, never from a live read of the repos.

## Inputs

1. `radar.yaml` — lanes with `question`, `what_exists`, `glossary`, `reopen_when`, `not_now`; the `rules` block.
2. The feed: a papers section (title, link, date, snippet per item, grouped by track; the newest `## <date>` block of `PAPERS.md`) and an arrivals list (slug, stars, language, licence key, created_at, days seen in history, description; `data/arrivals/<date>.md`, produced by `python3 scripts/arrivals.py --since <day after the last triage>`). If no arrivals file exists for the window, run the script first; never substitute compute_trends' "newcomers".
3. `TEMPLATE.md` (output shape) and `TRAPS.md` (how the data lies). Read both before the first row.

## Procedure

1. **Title screen.** For every item decide: read, or skip by title. Skip only when no lane's `question`, `glossary` or `reopen_when` could plausibly match. List every skipped item by name under "Skipped by title". Err toward reading; a skipped item costs one line, a missed one costs a week.
2. **Read what you keep.** Run `python3 scripts/evidence.py --date <date> <item> ...` for every kept item (arXiv id, `hf:org/model`, HF blog URL, `owner/repo`); it writes one file per item under `evidence/<date>/` and does the licence walk. Read the files it wrote, and fetch by hand only what it flagged ⚠️. What it fetches, for the record: papers: the arXiv abs page (`https://arxiv.org/abs/<id>`) and use the abstract; read the body only when a verdict stronger than CANDIDATE depends on a number. Launch posts: read the page and fetch the model card's licence field (`https://huggingface.co/api/models/<id>`). Repos: README via the API, `created_at`, star velocity, `pushed_at`, and **every LICENSE/COPYING file at every tree depth**. Save what you read under `evidence/<date>/` so each row can cite a file.
3. **Fill the row** (see TEMPLATE.md). "Mechanism" carries the source's own numbers. "Lane · where we have it" names a lane id and one sentence tying the item to that lane's `what_exists`. Leave no lane cell empty. An item you read past the title screen that then fits no lane gets one line under "Read, no lane" and **no row**: do not stretch a lane to give it one.
4. **Verdict** from the fixed vocabulary. A `CANDIDATE` lands on one of the lane's `lists` (name it in the row); an `ALREADY` or cite-only item goes to the lane's pickup note under `citations`; an item from a track marked `watch` with no lane is listed once under "Skipped by title" with "watch track, no lane", with evidence scope in brackets: `(abstract)`, `(body read)`, `(post read; benchmarks are the vendor's)`, `(README + licence files, not run)`. A `CANDIDATE` must land on a list that exists in a lane (a bake-off list, a decision note, a case backlog). `narrow` means it matters only after a stated precondition.
5. **Reopen threshold** on every row: a concrete event, not a date. Prefer the lane's own `reopen_when` phrasing.
6. **Counts and kill clause.** Count promotions per source (promoted = CANDIDATE or stronger). A source with two consecutive triages at zero promotions gets a strike; state strike / no strike per source in the triage log line. Strikes count only when the feed was fetched with *this* profile's `tracks:`; if the feed's sections belong to another profile (the shipped example, a fork), write "strikes not counted: feed fetched for another profile" instead.
7. **Pickup notes.** For each lane that received a row stronger than PARKED, append a block to `pickup/<lane id>.md` in the TEMPLATE shape. Lanes with nothing get nothing. The heading must be exactly `## <date> — from triage <date>`: `scripts/handoff.py` finds blocks by it.
8. **"What moved" summary**, at most eight bullets, lane-first, placed in the triage log. Say explicitly when the priority order across lanes is unchanged.

## Rules that are not optional

- **Calibrated claims.** Numbers come from the fetched artefact. Vendor benchmarks are labelled as the vendor's. Anything you could not verify carries ⚠️ UNVERIFIED. "Nothing cloned or run" is stated once per section and stays true unless an `investigate` step ran.
- **Licence at every depth** before any verdict stronger than PARKED on a repo, and the model-card licence (plus its LICENSE file when the card says `other`) before any verdict stronger than PARKED on a model. `other` = unknown until read. A `NOT-ADOPT` or `PARKED` on grounds other than licence needs no licence fetch.
- **Arrivals, not newcomers.** An arrival is a slug absent from the full daily history; if the input gives `days seen`, a repo with many days is not new and the row says so.
- **No lane, no verdict.** Do not invent a lane. If an item is interesting but belongs to no lane, write it in one line under "Skipped by title" with "no lane".
- **Respect `not_now`.** An item that matches a lane's `not_now` list is `NOT-ADOPT` or `PARKED` with that reason, never `CANDIDATE`.
- **No builds.** Triage opens nothing. A row can say what a lane should add to a list; it cannot start work.
- **Feed sections vs `tracks:`.** Triage every `###` section the feed has, whatever `tracks:` says; the names need not match. A section whose name starts with `watch:` is a watch track.
- **One row per item.** An item that fits two lanes gets its row in the lane it moves most and a `citations` clause in the other lane's pickup block.
- **No list, no CANDIDATE.** If the lane has no list the item could land on (no backlog, bake-off or decision note in `what_exists`), the verdict is `PARKED` with "no list in lane" as the reason.
- **Hand-fetched evidence.** When `evidence.py` flags ⚠️ and you fetch the file yourself, save it next to the item's file as `<item file stem>.<what>.txt` (e.g. `hfmodel-org-model.LICENSE.txt`) so the row can cite it.
- **Evidence is today's.** `evidence.py` fetches the state on the day you run it, not the feed week's: stars, `pushed_at` and arrivals counts drift. Write the fetch date in the scope line and do not explain the drift away.
- **Say what you did not do.** Late triage: by how many days. Items not read: why. Evidence stripped by an HTML export: say so.

## Output

- `VERDICTS.md`: prepend the new section (newest first).
- `pickup/<lane id>.md`: appended blocks.
- `evidence/<date>/`: the fetched pages, one file per item.
- Stdout: the triage log line and the "what moved" bullets, then the output of `python3 scripts/handoff.py --date <date> --dry-run` so the user sees every note that would land on a repo. Sending (the same command without `--dry-run`) is the user's call, not yours: it posts to other repos. Before a real send, `VERDICTS.md` and `pickup/` must be committed and pushed: each note links to the section on `main`, and `handoff.py` refuses to send while they are uncommitted.
