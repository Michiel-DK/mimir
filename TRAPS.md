# TRAPS.md — ways this data lies, learned the hard way

Read before writing a verdict. Each trap has cost a wrong sentence at least once.

1. **Newcomers ≠ arrivals.** "New on trending today" means new in *this window*. A true arrival is a slug never seen in the full daily history. Re-scan all of `data/daily` for the slug before calling anything new. (A repo with 16 snapshots since July was once called a newcomer.)
2. **Window-local day counts lie.** "Seen 2 days" inside a 7-day window says nothing about the repo's history. Count across all data.
3. **`rank_in_source` is not a rank** and `rolling_top` has no relevance filter. Read `description` before rank.
4. **`license.key == "other"` means UNKNOWN, not "weird licence".** Read the root LICENSE file, then every LICENSE at every tree depth (`git/trees/<branch>?recursive=1`). Per-directory licence splits exist (2 of 7 repos checked once had them). A root MIT with a GPL sub-package is not MIT.
5. **A licence badge is not a licence.** README badges drift; the file wins.
6. **A repo vanishing from trending ≠ decline.** Trending is a daily top list, not a time series.
7. **Descriptions drift.** The description in today's snapshot may not be the description when the repo arrived.
8. **Sub-30-day growth windows manufacture fake blowups.** Flat rows are junk; moving rows are exact.
9. **Vendor benchmarks are the vendor's.** Label them so. An HF launch post is marketing with a table in it.
10. **Abstracts are abstracts.** An abstract-only read is labelled `(abstract)`. A body read says what was read and what the HTML export stripped (arXiv HTML drops numbers inside math).
11. **Prices move both ways and revert.** A −78% on day one reverted on day three. Quote the change note, not the number, and say the date.
12. **Memory is rank-F evidence.** A fact remembered from a previous session is unverified until a tool call this session shows it.
13. **Tag matches are hints, not filters.** Title-keyword tags on the papers feed say where to look first; untagged items are still listed and still read by title.
