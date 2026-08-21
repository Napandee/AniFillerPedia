# Bootstrap data — working notes (2026-08-21)

Raw working output for issues #4 and #5. Not final schema/SQL — a landing
point for whoever builds the actual import once #6's `backend/schema.sql`
exists.

## #4 — series-candidates.json

- Source: `manami-project/anime-offline-database` release `2026-27`
  (2026-07-04, last release before the repo was archived — verbatim
  `anime-offline-database-minified.json`, 41,537 total entries, matches the
  count already recorded in `CLAUDE.local.md`'s research trail).
- **180 entries** matched `"canon filler"` or `"has fillers"` tags — 51 of
  those carry both tags. Matches the exact figures already in
  `CLAUDE.local.md` (180 / 51), confirming this is the same data referenced
  there, not a different snapshot.
- 174/180 have an AniList ID, 173/180 a MAL ID, all 180 have at least one
  synonym captured (the amended scope item — this data cannot be recovered
  later since the source is archived).
- `extract_candidates.py` is the extraction script — deterministic, safe to
  re-run against the same downloaded JSON. The 62MB source file itself was
  NOT committed (too large, and easily re-fetched from the GitHub release
  by anyone rebuilding this) — only the extracted `series-candidates.json`.

## #5 — naruto-shippuden-episodes.json

**Honest status: partial, not complete.** Only episodes 1–32 (Kazekage
Rescue Mission, canon) and 57–71 (Twelve Guardian Ninja Arc, filler) are
researched and cited — 47 of Naruto: Shippuden's ~500 episodes. Episodes
33–56 and 72+ are deliberately NOT included rather than guessed.

Why it stopped here: every claim in the output is backed by at least one
directly-fetched, re-readable source, most by two independent ones
cross-checked against each other (a genuine discrepancy actually turned up
mid-research — an AI-search-summarized "manga chapters 245–281" figure for
the Kazekage Rescue arc could not be corroborated by directly fetching two
of the pages that claim listed, so it was dropped rather than reported as
fact). Getting exact per-episode manga-chapter citations for the rest of a
500-episode series properly, not by asserting well-known fan consensus from
memory, is real, slow research work — the directive was explicit that a
smaller well-cited dataset beats a large rushed one for a citation-based
project, so this stopped rather than padding out further arcs on weaker
sourcing.

**Which show got researched, and why**: Naruto: Shippuden specifically
(the seven-show list in #5 names it first, and it's the most heavily
publicly documented of the seven, which mattered for finding independently
corroborated sources quickly).

**Remaining work for full #5 completion**: episodes 33–56, 72–500 of
Shippuden (this issue's Scope also still needs the other 6 shows entirely —
Naruto original, Bleach, DBZ/Super, Fairy Tail, Black Clover, Boruto, and
both FMA series — none of that was started this pass).

## Format note for whoever builds the loader

Both files are plain JSON, not SQL, and don't yet match `episodes`/
`citations`/`series` table shapes exactly — deliberate, since #6 hadn't
landed a real `schema.sql` when this work started. Field names were chosen
to map onto the schema discussed in `CLAUDE.md` (`status`, `episode_number`,
citation `url`/`description`) but expect to need a real transform step, not
a direct `COPY`.
