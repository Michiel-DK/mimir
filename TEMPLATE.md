# TEMPLATE.md — one triage section

```markdown
## <YYYY-MM-DD> · Feed triage (<feed section name>, <N> items) + GitHub trending <from> → <to>

_Scope: <what was read: "full abstracts from the arXiv abs pages for the K papers read", "HF posts read from the page + model-card licence via the API", "repo READMEs + API metadata + licence files at every tree depth">. Nothing cloned or run; repo and model claims are the projects' own. <late? say by how much.>
**Triage log: arXiv promoted A (of X) [+ W watch], HF promoted B (of Y), trending promoted C (of Z) — <strike / no strike> per source.**_

**What moved:** <at most eight bullets, lane-first; say explicitly when the priority order is unchanged>

| Item | Mechanism | Lane · where we have it | Verdict | Reopen threshold |
|---|---|---|---|---|
| [Title](url) (id) | What it does, with the numbers the source gives | `<lane id>` — the sentence that says what in that lane this touches | `VERDICT` (evidence scope) | the concrete event that reopens it |

**Skipped by title (noise for our lanes):** …

**GitHub trending <from> → <to> — <N> true arrivals (first appearance in the full daily history), <K> read:**

| Repo | What it is (their words, checked) | Licence (every depth) | Verdict |
|---|---|---|---|

Not read, by description: …

**Prices (if a price source is configured):** …
```

**Triage log line:** "promoted A (of X)" — A = rows at `CANDIDATE` or stronger (`ALREADY` counts), X = items the feed *listed* for that source, not items read. `[+ W watch]` = watch-track items listed. A strike needs two consecutive zero-promotion triages; on the first triage on record write "no strike (first triage)"; when the feed was fetched for another profile's tracks write "strikes not counted" (see the skill).

**Verdict vocabulary (fixed):** `ADOPTED` (in use) · `MOTIVATED` (a lane changed because of it) · `ALREADY` (we do this) · `CANDIDATE` (goes on a named list in a lane; may be `narrow`) · `PARKED` (correct lane, wrong time) · `NOT-ADOPT` (read, rejected, reason stated) · `WATCH` (unverified market or premise; one check before any outward sentence). Every verdict carries its evidence scope in brackets.

**Pickup note per lane** (`pickup/<lane id>.md`, appended per triage; `scripts/handoff.py --date <triage date>` carries each block to the lane's repo, so keep the heading exact):

```markdown
## <date> — from triage <date>
- <item> → <what moves in this lane, one sentence> · reopen: <threshold> · evidence: <abstract | body | README+licence | run>
- citations: <ALREADY and cite-only items, one clause each; omit the line if none>
```

The whole block, citations included, is what `handoff.py` posts to the lane's repo.
