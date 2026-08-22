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

**Honest status: partial, not complete — updated 2026-08-21 (second pass).**
100 of Naruto: Shippuden's ~500 episodes now have real citations: episodes
1–44, 57–112. Two ranges are deliberately excluded rather than guessed:

- **Episodes 45–56**: two independent filler guides
  (narutoshippudenfillerguide.com, Yahoo Entertainment) agree episodes
  33–53ish are "canon/mixed" at the arc level, but only one of them gives
  single-episode-level mixed-status boundaries within that range (e.g.
  flagging ep 45 specifically as mixed, 46–48 as canon, etc.) — the second
  source doesn't confirm that exact granularity, so rather than assert one
  source's precision alone, this range was left out. Worth a dedicated pass
  later specifically to find a second source with matching per-episode
  detail, rather than treating it as unresearchable.
- **Episodes 113+**: not yet researched at all.

This pass's new citations: episodes 33–44 (Tenchi Bridge Reconnaissance
Mission, canon), 72–88 (Akatsuki Suppression Mission — Hidan and Kakuzu
arc, canon, includes Asuma's death), 89–90 (mixed transition), 91–112
(Three-Tails' Appearance arc, filler) — all cross-referenced across two
independent guides plus Wikipedia's episode list for exact titles.

Why it stopped at 112: same discipline as the first pass — a smaller,
genuinely well-cited dataset beats a larger rushed one for a citation-based
project. 113 onward is a fresh arc (Itachi Pursuit Mission) not yet
cross-checked.

**Which show got researched, and why**: Naruto: Shippuden specifically
(the seven-show list in #5 names it first, and it's the most heavily
publicly documented of the seven, which mattered for finding independently
corroborated sources quickly).

**Remaining work for full #5 completion**: episodes 45–56 (the disputed
gap above), 113–500 of Shippuden (this issue's Scope also still needs the
other 6 shows entirely — Naruto original, Bleach, DBZ/Super, Fairy Tail,
Black Clover, Boruto, and both FMA series — none of that was started
across either pass).

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
