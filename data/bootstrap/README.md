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

**Remaining work for full #5 completion**: DBZ/Super, Black Clover,
Boruto, and both FMA series (Naruto original, Bleach, and Fairy Tail —
all done, see below).

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

## #5 — naruto-episodes.json

**Complete — all 220 episodes of the original Naruto TV series
(2002–2007, pre-Shippuuden).** Sourced from a community Reddit
canon/mixed/filler breakdown, independently corroborated by a second
Reddit thread (different poster) with an identical episode-by-episode
breakdown. Complete, gap-free, non-overlapping coverage of 1–220
confirmed before writing the file. Live in production 2026-08-22
(74 canon / 90 filler / 56 mixed).

## #5/#59 — fairy-tail-episodes.json, fairy-tail-2014-episodes.json,
fairy-tail-2018-episodes.json

**Complete — all 328 episodes across Fairy Tail's three real AniList
catalog entries.** A single community Reddit breakdown (canon/mixed/
filler/"anime canon") numbers all three series continuously as 1–328,
per common filler-guide convention, corroborated by a second independent
Reddit thread with an identical breakdown. This project splits it back
into each series' own absolute numbering to match its real catalog
entries (see #59 for why two new entries — Fairy Tail (2014), Fairy Tail
(2018) — were added rather than merging everything under one series):

- `fairy-tail-episodes.json`: episodes 1–175 (original 2009 series),
  additionally cross-checked against a Radio Times filler/optional-
  viewing guide — agreed on every episode it covered except two (49,
  151), resolved in favor of the two-source Reddit agreement, same
  precedent as Bleach's episode 227.
- `fairy-tail-2014-episodes.json`: original episodes 176–277, renumbered
  1–102.
- `fairy-tail-2018-episodes.json`: original episodes 278–328, renumbered
  1–51.

"Anime Canon" (episodes 246, 256 in the original 1–328 numbering) mapped
to plain `canon` per the 2026-08-22 decision — the same mapping applied
wherever this category has shown up (also seen in One Piece and Naruto:
Shippuuden's sources, not yet loaded for the former).

Live in production 2026-08-22: all three load clean (175+102+51 = 328
episodes), linked via `series_relations` (#59) so each entry's page shows
"Also on this site" links to the other two.

## #5 — one-piece-episodes.json

**Complete — all 1168 episodes.** Sourced from a community-compiled Reddit
manga-canon/mixed/filler breakdown, independently corroborated by a second
Reddit thread with an identical episode-by-episode breakdown, cross-checked
against a Crunchyroll/Anime Filler List skippable-filler guide. The two
cross-referenced sources agreed on every episode except one (807 — the two
Reddit threads call it mixed, the cross-reference guide doesn't list it in
either non-canon category, implying canon; resolved in favor of mixed, 2
sources vs 1 — same precedent as Bleach episode 227, see that episode's
`status_note`). "Anime Canon" (episodes 50-51, 93, 213-216, 418-420,
453-456, 497-499, 506, 737, 775, 1084) mapped to plain `canon`, same
mapping as Fairy Tail/Shippuuden. One transcription slip caught and fixed
before writing this file: the pasted "Anime Canon" list ended in a stray
"10" rather than a real episode number — confirmed as "1084", the exact
single gap between 1083 and 1085 in the manga-canon range, once the full
1-1168 coverage check came back non-empty. Complete, gap-free,
non-overlapping coverage of 1-1168 confirmed before writing the file.
Written directly in #77's split citation shape (`description` +
`methodology_note`) rather than the old single-field format, since #77
shipped first.

## #5 — meitantei-conan-episodes.json

**Complete — all 1212 episodes, canon/filler only (no mixed episodes found
in this show's sourcing).** Sourced from two independent Reddit threads
with an identical manga-canon breakdown, cross-checked directly against
animefillerlist.com's own Manga Canon Episodes list — the two sources
agreed on every single episode, no disputes to resolve (unlike Bleach/One
Piece). "Anime Canon" (episode 1187) mapped to plain `canon`, same
convention as every other show. Complete, gap-free, non-overlapping
coverage of 1-1212 confirmed before writing the file. Note: the bootstrap
catalog's own `anilist_episode_count` shows 1205 — a few behind this
breakdown's 1212, almost certainly AniList being a few episodes stale on
an ongoing series rather than an error in this data.

## #5 — boruto-episodes.json

**Complete — all 293 episodes.** Same two-Reddit-threads-plus-
animefillerlist.com-cross-reference sourcing as Conan above, again zero
disagreements between the two sources. Complete, gap-free, non-overlapping
coverage of 1-293 confirmed before writing the file. Notably large "Anime
Canon" share (179 of 293 episodes, mapped to `canon`) — Boruto's anime
ran well ahead of its source manga for long stretches, with those
anime-original arcs later folded back into manga canon, which the
source's own categorization reflects directly.

## #5 — gintama-episodes.json

**Complete — all 369 episodes.** Sourced from a community-compiled Reddit
breakdown, corroborated by a second independent thread — same
corroboration bar as every other show, but no separate cross-reference
source was checked for this one (unlike Conan/Boruto/Bleach/Fairy Tail).
Complete, gap-free, non-overlapping coverage of 1-369 confirmed before
writing the file.

## Format note for whoever builds the loader

Both files are plain JSON, not SQL, and don't yet match `episodes`/
`citations`/`series` table shapes exactly — deliberate, since #6 hadn't
landed a real `schema.sql` when this work started. Field names were chosen
to map onto the schema discussed in `CLAUDE.md` (`status`, `episode_number`,
citation `url`/`description`) but expect to need a real transform step, not
a direct `COPY`.

(Superseded by `load_episodes.py`, which does exactly this transform —
kept above for the historical trail, not because the loader doesn't exist.)

## #73/#74 (2026-08-23): title + source_count, both optional per episode

Each episode entry may now carry two more optional keys, both non-
contentious metadata rather than a filler/canon claim, so `load_episodes.py`
applies them even on a re-run where the status is unchanged (no
`--allow-corrections` needed — see the script's own docstring):

- `"title"` — the episode's title. Not hand-typed here; see
  `backfill_episode_titles_from_anilist.py` for the (partial — AniList's
  own `streamingEpisodes` field is a rolling/incomplete list, not a full
  archive) automated backfill instead.
- `"source_count"` — how many independent sources agree with this
  episode's status, backing the episode detail page's "N independent
  sources agree" badge. All six already-loaded datasets (Naruto, Naruto:
  Shippuuden, Bleach, Fairy Tail × 3) were backfilled to `2` uniformly —
  every one of their citation descriptions claims at least "a second
  independent thread" corroborating the first; Shippuuden's own citation
  says "several," but 2 is the honest, defensible floor rather than
  inventing a more specific number with no real citation behind it. A
  single shared citation can't hold two different source_counts for
  different episodes that cite it (e.g. Fairy Tail's original-series
  citation covers episodes 49/151 too, where Radio Times was silent
  rather than agreeing) — 2 was picked as the value that's true for every
  episode sharing that citation, not the maximum true for any of them.

## #77 (2026-08-23): citation_sources gains an optional methodology_note

Each `citation_sources` entry may now carry an optional `"methodology_note"`
key alongside `"description"` — splitting what used to be one long paragraph
mixing a reader-facing source claim with internal research notes ("per
project decision 2026-08-22", "not recorded at compile time") into two:
`description` stays short and reader-facing, `methodology_note` holds
everything else, shown behind a "How was this verified?" disclosure on the
episode detail panel rather than inline with the main citation text.

All six already-loaded datasets' `citation_sources` were rewritten into
this shape — no content dropped, just relocated. `load_episodes.py` syncs
the split into already-loaded episodes' citation rows on a plain re-run
(same non-contentious-metadata treatment as `title`/`source_count` above),
which is how the six existing shows got backfilled without a separate
one-off script.

## #5 — fullmetal-alchemist-episodes.json, fullmetal-alchemist-brotherhood-episodes.json

**Complete — both Fullmetal Alchemist series (51 + 64 = 115 episodes), 2026-08-25.**
Sourced from filler guides rather than Reddit breakdowns this time (none
found for these two shows specifically) — two independently-fetched guides
(epicdope.com, QuoteTheAnime) agreed on an identical episode-by-episode
breakdown for the 2003 series; a third (SuperHeroJacked) additionally
agreed exactly for Brotherhood. A fourth Brotherhood guide (aniyume.net)
was checked and discarded as unreliable — it flagged episodes 37, 48, and
49 as filler, which contradicts all three agreeing sources and
well-established fan consensus (these are some of the show's most
acclaimed, clearly manga-adapted canon episodes: Father's origin reveal,
and the Mustang/Envy and Trisha's-backstory episodes respectively).

**The 2003 series' "filler" status covers two different things**, both
folded into `filler` since the project's 3-value schema has no separate
bucket for this: 3 pure standalone filler episodes (4, 10, 37, agreed
skippable by both sources) and 28 episodes of the anime's own original
continuation once it outpaced Arakawa's still-ongoing manga (mostly 29
onward, with a handful of earlier anime-original episodes interspersed).
The second group is plot-critical to the 2003 anime's own ending (a
different central antagonist and different conclusion than the manga)
and explicitly *not* skippable padding per every guide checked — each of
those episodes' `status_note` says so, so a reader isn't misled by the
bare `filler` status alone.

**Brotherhood is almost entirely canon** (58/64), with episode 1 recorded
as `mixed` (a reordered, compressed preview built from real but
non-sequential manga content, not a straight adaptation), episodes 4/9/13/14
as `mixed` ("partial filler" — part manga-adapted, part original, within
the same episode), and episode 27 as the show's one pure `filler` episode.

Both series' catalog titles matched exactly against `series-candidates.json`
("Fullmetal Alchemist", AniList 121; "Fullmetal Alchemist: Brotherhood",
AniList 5114) — no title-mismatch issue this time, unlike Shippuuden's
earlier one. `load_episodes.py` ran clean against a locally-seeded test
copy of both series before being applied to production (51/51 and 64/64,
zero failures) — see `CLAUDE.local.md` for the production load confirmation.

## #5 — dragon-ball-z-episodes.json

**Complete — all 291 episodes, 2026-08-25.** Sourced from two
independently-fetched filler guides (OtakusNotes, SuperHeroJacked) whose
breakdowns matched almost exactly — same 38 pure-filler episodes, same
canon range for the vast majority of the show — diverging only on
episodes 17-20 (SuperHeroJacked calls them straight canon; OtakusNotes
calls them mixed) and episode 44 (SuperHeroJacked calls it pure filler;
OtakusNotes calls it mixed). Resolved in favor of the mixed
classification for all four, backed by two further independently-fetched
sources: CBR specifically corroborates 11/17/18/20/204/251/287 as mixed,
and ScreenRant specifically corroborates 44 as mixed (it closes out the
Fake Namek filler material and opens real canon content in the same
episode). Episode 229 is the one mixed episode with only a single
directly-fetched source behind it (OtakusNotes) — flagged in its own
status_note rather than silently treated as equally corroborated as the
rest, matching this project's honesty standard on citation confidence.

No episode titles included in this file, unlike every prior show — 291
episodes was too many to hand-type reliably, and title backfill already
has an automated path (`backfill_episode_titles_from_anilist.py`, #73)
that runs after loading regardless of whether the source JSON carried
titles. Complete, gap-free, non-overlapping coverage of 1–291 confirmed
before writing the file.

## #5 — dragon-ball-super-episodes.json

**Complete — all 131 episodes, 2026-08-25.** The 14-episode filler list
(4, 15, 42-46, 68-70, 73-76) is corroborated by three independently-
fetched sources (ListFist, ComicBook.com, The Mary Sue) agreeing exactly.
A fourth guide (animefillerguide.com) was checked and discarded — its
filler list (adding episodes 16-17, 52, 87-90 that none of the three
agreeing sources call filler) contradicted the consensus, the same
unreliable-fourth-source pattern already hit once this session with
Fullmetal Alchemist: Brotherhood's aniyume.net outlier. Episodes 1-2 are
`mixed` per ListFist (partial filler alongside real story content);
episode 89 is also `mixed` per ListFist but flagged in its own
status_note as backed by only one source, unlike everything else in this
file. Worth noting for whoever reads this later: Dragon Ball Super's
production history is genuinely unusual for this project's canon/filler
model — much of its story originates from Toriyama's own movie scripts
and outlines, adapted into anime before or alongside Toyotaro's manga,
rather than the more typical "anime runs ahead, so it pads with filler"
pattern this project's other shows follow. The canon/filler line drawn
here is the fan-consensus one, same as every other show in this dataset,
just worth flagging as a different kind of "canon" underneath the same
label. No titles hand-compiled — left for #73's automated backfill, same
as Dragon Ball Z. Complete, gap-free, non-overlapping coverage of 1-131
confirmed before writing the file.

**Remaining for full #5 completion**: Black Clover — the one series
named in #5's scope list not yet compiled as of this entry. Every other
series listed (Naruto, Naruto: Shippuuden, Bleach, Dragon Ball Z,
Dragon Ball Super, Fairy Tail, Boruto, both Fullmetal Alchemist series)
now has hand-compiled episode data loaded and live.
