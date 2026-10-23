---
name: radar-profile
description: Draft or revise radar.yaml, the profile that makes radar-triage verdicts relative to the user's own repos. Use when a repo tree exists but no radar.yaml does, or when a triage reported blank or inferred "where we have it" cells.
---

# radar-profile

The triage is only as good as the profile. This skill **drafts**; a human reviews and commits. Never write a lane the user has not confirmed is real work.

## Read, in this order

1. Each repo's README, scope / plan / open-items / backlog files, and the last ~50 commit subjects.
2. Any results pages or decision notes the README links to.
3. Existing `radar.yaml`, if any, and the latest triage section's "what radar.yaml was missing" paragraph.

## Write one lane per question actually being worked or parked

For every lane, all of these keys. A lane missing any of them produced inferred cells in testing.

| key | what goes in | test |
|---|---|---|
| `id`, `repo`, `status` | short id; repo name; `live` / `next` / `in-progress` / `queued` / `parked` / `killed <date>` | status is a word from this list |
| `question` | one sentence, the question the lane exists to answer | contains a verb and a measurable noun |
| `what_exists` | the artefacts: counts, files, pages, decisions already taken | at least one number or file name |
| `lists` | the named places a CANDIDATE can land: a decision note, a bake-off list, a case backlog, a reading pile | one or more names; the triage will cite them |
| `glossary` | the lane's own words, so a row can say "this is our X" | 5–15 terms |
| `reopen_when` | concrete events, each with its **bar** when one is implied (licence: permissive = Apache/MIT/BSD; revenue-capped counts or not; size ≤ N B; cost ≤ X) | no bare adjectives like "cheap" or "permissive" |
| `not_now` | what the lane has explicitly declined | present, even if short |
| `candidates` (optional) | third-party items already on a list, with size and date, so a re-release is recognisable | id + date |

## Also

- Every `tracks` entry maps to a lane or is marked `watch: true` (then the triage lists its items once, with "watch track, no lane", and never promotes them).
- `rules:` holds cross-lane constraints (dormant projects nothing routes through; "no autonomous digest"; tier orders).
- Prices: either a `price_source` stanza or none, in which case the template's Prices line is dropped.
- Keep third-party product names out of `question` and `reopen_when`; they belong in `candidates`.

## Output

`radar.yaml` plus a short "review me" list: every lane whose `status` or `what_exists` you inferred rather than read.
