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

**Complete — all 500 episodes, updated 2026-08-22 (third pass).** Replaces
the prior 100-episode partial dataset (episodes 1–44, 57–112 only, with
45–56 deliberately excluded — see git history for that dataset's own
reasoning) with a comprehensive breakdown sourced from a community Reddit
compilation, corroborated by several other closely-matching Reddit
threads. This resolved the previously-excluded 45–56 gap outright.

Cross-checked against what was already loaded before replacing it: 79/100
episodes agreed exactly with the prior Wikipedia + filler-guide sourced
data. 21 (episodes 1–19, 24–25) disagreed — this source calls them
`mixed`, the prior data called them `canon` — corrected after explicit
confirmation to treat this newer, multiply-corroborated source as
authoritative. One "Anime Canon" episode (28) needed no change, since the
decided mapping (anime-original content later confirmed canon → `canon`)
matched what was already there.

`load_episodes.py` gained `--allow-corrections` for this: an episode that
already exists with a different status than a file proposes is reported
(never silently touched) unless the flag is passed, in which case a real
correction is applied via a new contribution row — the prior contribution
and the episode's full history stay intact, only the current approved
state changes.

**Which show got researched first, and why**: Naruto: Shippuuden
specifically (the seven-show list in #5 names it first, and it's the most
heavily publicly documented of the seven, which mattered for finding
independently corroborated sources quickly).

**Remaining work for full #5 completion**: the other 6 shows in scope
(Naruto original, Bleach — done, see below — DBZ/Super, Fairy Tail, Black
Clover, Boruto, and both FMA series).

## #5 — bleach-episodes.json

**Complete — all 366 episodes of the original Bleach TV series (2004–2012,
pre-Thousand-Year Blood War).** Sourced from a community-compiled Reddit
canon/mixed/filler breakdown, independently corroborated by a second Reddit
thread with an identical episode-by-episode breakdown, cross-checked
against a Radio Times filler-only guide. All three sources agreed on every
episode except one (227 — two Reddit threads call it canon, Radio Times
calls it the start of a filler run; resolved in favor of canon, 2 sources
vs 1 — see that episode's `status_note` for the full reasoning). Complete,
gap-free, non-overlapping coverage of 1–366 confirmed before writing the
file. Live in production 2026-08-22: `load_episodes.py` ran clean (366/366,
162 canon / 163 filler / 41 mixed).

Bleach: Sennen Kessen-hen (the 2022+ continuation) is a separate AniList/MAL
catalog entry, not covered by this file.

## Format note for whoever builds the loader

Both files are plain JSON, not SQL, and don't yet match `episodes`/
`citations`/`series` table shapes exactly — deliberate, since #6 hadn't
landed a real `schema.sql` when this work started. Field names were chosen
to map onto the schema discussed in `CLAUDE.md` (`status`, `episode_number`,
citation `url`/`description`) but expect to need a real transform step, not
a direct `COPY`.
