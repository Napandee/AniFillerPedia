# Bootstrap data — working notes (2026-08-21)

Raw working output for issues #4 and #5. Not final schema/SQL — a landing
point for whoever builds the actual import once #6's `backend/schema.sql`
exists.

## needs-manual-research.json

Standing bucket (decided 2026-08-26) for candidates a batch attempted
and dropped rather than force-fitting weak/unclear/conflicting data —
Andreas reviews it manually to hunt down better sources himself.
Checked against before picking any future batch's candidates so a
dropped show is never silently re-attempted (this happened once before
the bucket existed: Urusei Yatsura, Tantei Gakuen Q, and Kinnikuman
were all independently re-attempted and re-dropped in #115 after
already failing in #113). An entry is removed once its show is
actually loaded in a later batch.

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

## #5 — black-clover-episodes.json

**Complete — all 170 episodes, 2026-08-25. #5 is now fully complete** —
every series in its original scope list has hand-compiled episode data
loaded and live.

The 17-episode pure-filler list (29, 66, 68, 82, 123-125, 131, 134-135,
142-148) is corroborated by two independently-fetched sources
(QuoteTheAnime, CBR) agreeing exactly, including the specific 148
boundary. **This file has a real, disclosed confidence gap the other six
shows compiled this session don't have**, on the "mixed" category
specifically: several candidate mixed episodes (2, 3, 8, 9, 12, 30, 67,
69, 85, 86, 88, 130) turned up across various sources, but no two
sources agreed with each other on which ones actually qualify — one
source (joinkaminari.com) even contradicted itself, listing episode 149
as both filler and the start of an "anime-canon" range in the same
article. Rather than guess, all of those candidates are recorded as
plain canon here; only episode 102 (the one candidate every source that
addressed mixed episodes at all agreed on) is recorded as mixed, and
even that's backed by only one directly-fetched source. Episode 149
itself is the one genuinely contested boundary case — resolved as canon
in favor of the two internally-consistent, agreeing sources (QuoteTheAnime,
CBR) over the two others that disagreed with the consensus and, in one
case, with themselves — see that episode's own status_note.

No titles hand-compiled — left for #73's automated backfill, same as
Dragon Ball Z/Super. Complete, gap-free, non-overlapping coverage of
1-170 confirmed before writing the file.

**Corrections, 2026-08-25 (same day, post-load):** Andreas independently
verified this session's four newly-compiled shows against his own
re-reads of the same sources and found two real corrections, applied via
`load_episodes.py --allow-corrections` (audit trail preserved, old
contribution rows untouched):

- **Black Clover** — this file's own disclosed "mixed" confidence gap
  (above) turned out to be a transcription gap, not a genuine source
  disagreement: a fuller, internally-consistent read of QuoteTheAnime's
  page (the same source already cited here) resolves it. Episodes 2, 8,
  9, 12, 30, 69 move from canon to mixed, and episode 149 moves from
  canon to filler (18 filler episodes total, not 17) — see each episode's
  own status_note for the full reasoning, including the one remaining
  real disagreement (CBR's arc-level count still stops at 148).
- **Fullmetal Alchemist: Brotherhood** — episode 1 moves from mixed to
  canon, for consistency: all three sources tag it "anime canon," which
  this project treats as canon everywhere else (confirmed by an
  independent, unrelated Dragon Ball Super check the same day) — the
  original "mixed" call here was a one-off inconsistency, not a real
  factual dispute.

Two other shows (**Dragon Ball Z**, **Dragon Ball Super**) were
independently checked the same way and confirmed to already match
exactly — no changes needed there. **Fullmetal Alchemist (2003)** was
also checked: its 28-episode "anime canon" block (the anime's own
original continuation once it outpaced the still-ongoing manga) was
deliberately kept as `filler` rather than moved to `canon` — a real
policy call, not a data error, since that block adapts nothing from
Arakawa's manga at all, unlike the smaller "anime canon" pockets in the
other shows. Andreas confirmed keeping it as-is.

## #104 — second batch: InuYasha, Rurouni Kenshin, Yuu☆Yuu☆Hakusho, Toriko, Hajime no Ippo, JoJo no Kimyou na Bouken (TV)

**Complete — all six series, 2026-08-25.** Picked from the 167 manami-project
candidates left unresearched after #5 closed (see `series-candidates.json`).
618 episodes total across the six shows.

- **InuYasha** (167/167: 115 canon / 35 filler / 17 mixed) — two
  independently-fetched sources (QuoteTheAnime, Entoin) agreed exactly, no
  disputed episodes. Scope deliberately capped at the original series (167
  episodes); *InuYasha: The Final Act* is a separate 26-episode continuation
  with its own AniList entry, not part of this catalog entry or this
  manami candidate.
- **Rurouni Kenshin: Meiji Kenkaku Romantan** (94/94: 51 canon / 38 filler /
  5 mixed) — both guides checked (QuoteTheAnime, FictionHorizon) claimed the
  series has 100 episodes, which is wrong: verified via Wikipedia and a
  direct AniList API check that the real broadcast run is 94 episodes (plus
  a 95th, unaired DVD-only bonus finale not in this project's catalog
  entry). Both guides' classifications beyond 94 were disregarded; within
  1-94 they agreed on everything except episodes 19-21, resolved as canon
  (2 sources vs 1) — see that range's own status_note.
- **Yuu☆Yuu☆Hakusho** (112/112: 106 canon / 4 filler / 2 mixed) — a
  genuinely low-filler show. Two sources (epicdope, QuoteTheAnime) agreed
  exactly on the 4 pure-filler episodes; episodes 11 and 13 are recorded as
  mixed on QuoteTheAnime's authority alone (epicdope's guide didn't call
  them out specifically). QuoteTheAnime's own stated total (114 episodes)
  doesn't match this project's 112-episode AniList catalog entry — the same
  kind of guide-site episode-count confusion hit with Rurouni Kenshin,
  disregarded the same way.
- **Toriko** (147/147: 127 canon / 20 filler, no mixed episodes found) —
  thinner guide coverage than this project's other shows (a less
  mainstream title). QuoteTheAnime's exhaustive 20-episode filler list is
  the primary source; the Toriko Fandom wiki's own filler category
  independently confirms 14 of those 20. The remaining 6 (episodes 1, 51,
  99, 136, 146-147) are single-source, flagged in their own status_notes.
- **Hajime no Ippo** (75/75: 73 canon / 2 filler) — an extremely low-filler
  show; only two clip/recap episodes (31, 52) are filler, agreed by two
  sources with no disputes. *Hajime no Ippo: Champion Road* (a compilation
  movie, separate manami candidate) is explicitly out of scope.
- **JoJo no Kimyou na Bouken (TV)** (26/26: all canon) — the original 2012
  David Production adaptation of Phantom Blood + Battle Tendency has zero
  filler or mixed episodes per two agreeing sources. Included deliberately
  as a low-filler data point, not assuming every manami-flagged candidate
  has substantial filler content.

No episode titles included in any of the six files — left for #73's
automated backfill pass (see #103, which tracks actually ensuring that
backfill runs for every loaded series, this batch included). 161 manami
candidates remain unresearched after this batch.

**Corrections, 2026-08-25 (same day, post-load):** Andreas independently
verified all six shows against his own re-reads of the same sources.
Four (InuYasha, Rurouni Kenshin) matched exactly, no changes. Two had
real corrections, applied via `load_episodes.py --allow-corrections`:

- **Yuu☆Yuu☆Hakusho** — episodes 107 and 108 move from filler to canon
  (QuoteTheAnime actually tags these "anime canon," which this project
  treats as canon everywhere else — this project's own fetch of the page
  had flattened that distinction into a plain filler list), and episodes
  109 and 111 move from filler to mixed (also flattened the same way).
  **The show now has zero pure-filler episodes** — every one of its
  non-canon episodes is mixed, not filler, which actually matches an
  alternate source found during initial research that claimed "no filler
  episodes at all."
- **Toriko** — episode 136 moves from filler to canon, episode 146 moves
  from filler to mixed. Both were among this file's own disclosed
  single-source, lower-confidence filler calls — resolved by Andreas's
  independent check rather than left as flagged uncertainty.

Same pattern as the Black Clover correction earlier this session: in
both cases, this project's own automated fetch of a cited source
flattened a more nuanced classification (a distinct "anime canon" or
"mixed" sub-category) into a blunt filler/canon split, and a careful
human re-read of the same already-cited page caught what the fetch
missed — not a new source, a better reading of an existing one.

## #105 — third batch: Kuroshitsuji, Ao no Exorcist, Nanatsu no Taizai, Noragami, Owari no Seraph, Shingeki no Kyojin

**Complete — all six series, 2026-08-26.** 110 episodes total across the
six shows, all first cours/first seasons only where a franchise has
multiple AniList entries (confirmed by direct API check before compiling
any of them, per #104's own lesson about guide-site episode-count
errors).

- **Kuroshitsuji** (24/24: 9 canon / 15 filler) — the manga author wanted
  more screen time for Sebastian than the source pacing allowed; the
  anime follows the manga through the Black/Red/Indian Butler arcs
  (1-6, 13-15) then diverges fully. Episode 1 is disputed between two
  sources calling it canon and one calling it filler — resolved canon.
- **Ao no Exorcist** (10 canon / 5 mixed / 10 filler) — episodes 18-25 are
  the anime's own original ending, produced once the anime outpaced the
  manga (a Satan confrontation the manga hadn't reached), later ignored
  entirely by the manga-faithful Kyoto Saga continuation. Classified
  filler under this project's manga-adaptation definition, same policy
  call as Fullmetal Alchemist (2003) earlier in this project.
- **Nanatsu no Taizai** (24/24, all canon) — zero filler in Season 1,
  confirmed by two sources; the "Signs of Holy War" bridging special
  some guides number as 25-28 is a separate production, out of this
  catalog entry's scope.
- **Noragami** (10 canon / 1 mixed / 1 filler) — genuinely lower
  confidence than this batch's other shows; every source checked
  disagreed with at least one other on episodes 10 and 12 specifically.
  Resolved by rough majority in each direction (mixed for 10, filler for
  12) — both flagged in their own status_notes as worth a second look.
- **Owari no Seraph** (12/12, all canon) — the first cour is fully manga
  canon; the franchise's one mixed episode belongs to the second cour, a
  separate catalog entry.
- **Shingeki no Kyojin** (24 canon / 1 mixed) — Season 1 is almost
  entirely canon; two sources agree episode 22 is the only mixed
  episode. Included deliberately as a low-filler data point, same
  reasoning as JoJo TV in #104.

**A repeat of #104's citation-combo bug caught before it reached the
loader this time**: Noragami's disputed episodes (10, 12) were initially
drafted citing both sources with a differing source_count, exactly the
mistake made (and caught by the loader) with Rurouni Kenshin/Yu Yu
Hakusho last batch — fixed in the generator script itself before ever
running the loader, by citing only the source that actually supports
each disputed episode's status.

No episode titles hand-compiled for any of the six — `load_episodes.py`'s
new auto-backfill (#103) picked up titles automatically during the load
itself (13/24 for Kuroshitsuji, 12/25 for Ao no Exorcist, 12/12 for
Noragami, 25/25 for Shingeki no Kyojin; Nanatsu no Taizai and Owari no
Seraph have no AniList streaming-episode data available at all, a known
limitation, not a bug). 155 manami candidates remain unresearched after
this batch.

**Corrections, 2026-08-26 (post-load):** Andreas independently verified
all six shows. Four matched exactly (Ao no Exorcist, Nanatsu no Taizai,
Owari no Seraph, Shingeki no Kyojin), applying the same continuous-
numbering-across-seasons scope check used for InuYasha/Rurouni Kenshin —
each correction source's numbering ran past this project's actual
per-show scope (a sequel season not in this catalog entry), and once
restricted to the real scope, matched exactly. Two real corrections
found, applied via `load_episodes.py --allow-corrections`:

- **Kuroshitsuji** — episode 1 moves from canon to mixed. This episode
  had already been disputed between two sources (canon vs filler);
  Andreas found a third classification (mixed) that reads as more
  precise than either — the episode genuinely blends real character-
  introduction content with anime-only framing.
- **Noragami** — episode 12 moves from filler back to canon, reversing
  this file's own earlier majority resolution (2 sources called it
  filler, 1 called it "anime canon"). Andreas's independent check
  confirmed the "anime canon" reading, which this project maps to plain
  canon everywhere else.

A real generator-script bug caught before touching production, same
class as #104's own citation-combo issue: Noragami's corrected episode
12 initially specified a `source_count` that conflicted with episode
10's already-established value for the identical single-source citation
combo — caught by `load_episodes.py`'s own conflict detection during
local testing, fixed before the production load.

## #109 — fourth batch: Yowamushi Pedal, Sword Art Online: Alicization, Shokugeki no Souma, Tokyo Ghoul:re, Rosario to Vampire, One Punch Man

**Complete — all six series, 2026-08-26.** 123 episodes total. Five of
the six turned out to be confirmed-clean (zero filler), a heavier skew
toward low-filler shows than any prior batch — not by design, just how
the research landed:

- **Yowamushi Pedal** (38/38, all canon) — the entire 137-episode,
  5-season franchise has zero reported filler.
- **Sword Art Online: Alicization** (24/24, all canon) — the entire
  47-episode Alicization arc (this cour + the separate "War of
  Underworld" continuation) is a faithful light-novel adaptation.
- **Shokugeki no Souma** (24/24, all canon) — the entire 86-episode,
  5-season franchise has zero filler episodes.
- **Tokyo Ghoul:re** (12/12, all canon) — confirmed via QuoteTheAnime,
  cross-checked informally against animefillerlist.com (not cited
  directly, per this project's guardrail). Worth noting: general
  commentary about this show's later seasons describes real
  adaptation/pacing changes from the manga, but no guide flags any
  specific episode in this cour as anime-original or filler.
- **One Punch Man** (12/12, all canon) — the entire 36-episode,
  3-season franchise has zero filler.
- **Rosario to Vampire** (7 canon / 5 mixed / 1 filler) — the one
  genuinely filler-heavy show in this batch, and also this batch's one
  lower-confidence file: only one directly-fetched source (QuoteTheAnime)
  provides a full episode-by-episode breakdown; a general aggregate
  search confirms the same overall scale but no second source with a
  matching per-episode table was found. Flagged on each affected
  episode's own status_note.

No episode titles hand-compiled for any of the six — `load_episodes.py`'s
auto-backfill (#103) picked up titles automatically during the load
itself where AniList had them (Sword Art Online: Alicization 24/24,
Shokugeki no Souma 12/24, Tokyo Ghoul:re 12/12, One Punch Man 12/12;
Yowamushi Pedal and Rosario to Vampire have no AniList streaming-episode
data available at all, a known limitation, not a bug). 149 manami
candidates remain unresearched after this batch.

## #110 — fifth batch: first batch sized at 10 (Andreas's request going forward)

**Complete — all ten series, 2026-08-26.** 349 episodes total.

- **Akame ga Kill!** (18 canon / 1 mixed / 5 filler) — episodes 20-24 are
  an anime-original ending once the anime outpaced the still-ongoing
  manga; classified filler under this project's manga-adaptation
  definition, same policy as Fullmetal Alchemist (2003)/Ao no Exorcist —
  both cross-referenced sources here independently draw that exact FMA
  (2003) comparison themselves.
- **Toaru Kagaku no Railgun** (17 canon / 1 mixed / 6 filler) — two
  sources agree on episodes 1-14 exactly but disagree on 15-24: one
  distinguishes an anime-original "Level 6 Shift" arc from plain filler
  (mapped to canon, matching this project's "anime canon" convention),
  the other calls the whole block filler with no distinction and has an
  internal inconsistency elsewhere on its own page. Resolved in favor of
  the more granular source, flagged per-episode.
- **Berserk** (2016, 12/12, all canon) — the entire season is a
  faithful manga adaptation.
- **Hikaru no Go** (71 canon / 2 mixed / 2 filler) — a genuinely
  low-filler show; two sources agree exactly on episodes 64/66 (filler)
  and 65/67 (mixed).
- **Magi: Sinbad no Bouken (TV)** (13/13, all canon) — this file has a
  real, disclosed sourcing gap: no single page could actually be
  fetched (several candidates 403'd or 404'd), so this rests on a
  consistent aggregate search result rather than a directly-fetched
  citation, flagged explicitly.
- **Kingdom** (38/38, all canon) — some manga arcs were skipped
  entirely in the adaptation rather than replaced with filler, which is
  a different thing from filler itself.
- **Slam Dunk** (86 canon / 2 mixed / 13 filler) — the most genuinely
  disputed file in this batch: two sources agree exactly on 8 pure-filler
  episodes and roughly agree on 2 more (labeled filler vs. mixed,
  resolved as mixed), but diverge entirely on 5 more episodes each
  source calls filler and the other doesn't mention at all — both kept
  as filler but flagged individually as single-source, lower-confidence
  calls.
- **Boku no Hero Academia** (season 1, 13/13, all canon) — the
  franchise's first filler episode doesn't appear until Season 2, a
  separate catalog entry.
- **Haikyuu!!** (season 1, 25/25, all canon) — the entire 85-episode
  franchise has zero filler.
- **Tensei shitara Slime Datta Ken** (22 canon / 1 mixed / 1 filler) —
  a genuinely low-filler show; episode 4 mixed, episode 24 a
  standalone filler side-story.

No episode titles hand-compiled for any of the ten — `load_episodes.py`'s
auto-backfill (#103) picked up titles automatically during each load
where AniList had them. 139 manami candidates remain unresearched after
this batch. Batch size moves from 6 to 10 series going forward, per
Andreas's request.

**Corrections, 2026-08-26 (post-load):** Andreas independently verified
all ten shows. Seven matched exactly (Toaru Kagaku no Railgun, Berserk,
Hikaru no Go, Magi: Sinbad no Bouken, Kingdom, Boku no Hero Academia,
Haikyuu!!, Tensei shitara Slime Datta Ken) — the Railgun and Magi
confirmations are worth noting specifically: Railgun confirmed the
"anime canon → canon" resolution chosen over a disagreeing second
source was correct, and Magi confirmed the aggregate-search-only
sourcing (no page could be directly fetched) landed on the right
answer despite the weaker citation. Two real corrections:

- **Akame ga Kill!** — episodes 20-24 move from filler to canon. This
  surfaced a real policy inconsistency: these episodes were classified
  filler under the same policy already applied to Fullmetal Alchemist
  (2003)/Ao no Exorcist's anime-original endings, but Andreas's own
  correction labels them "Anime Canon" — the same label his Railgun
  correction confirms maps to canon. Asked directly which this show
  should be; Andreas confirmed canon, treating this show's anime-
  original content as inserted/side material rather than a manga-
  replacing alternate ending the way FMA 2003's genuinely is. FMA
  2003 and Ao no Exorcist's own classifications are unaffected — this
  is a per-show judgment call, not a blanket policy reversal.
- **Slam Dunk** — episodes 31, 32, 36 move from canon to mixed;
  episode 90 moves from filler to mixed; episode 92 moves from mixed to
  filler. All five were previously flagged as single-source or
  disagreement-resolved calls in this file's own research_status —
  Andreas's independent check resolved them differently than the
  original two-source synthesis had.

## Sixth batch (#113, 2026-08-26): Sailor Moon, Sailor Moon Crystal, Death Note, Kimetsu no Yaiba, Monster, Ouran Koukou Host Club, Initial D First Stage, Project ARMS, Shugo Chara!, Edens Zero

10 shows, 388 episodes total: Bishoujo Senshi Sailor Moon (46/46: 18
canon / 28 filler), Bishoujo Senshi Sailor Moon Crystal (26/26, all
canon), Death Note (37/37: 33 canon / 4 mixed), Kimetsu no Yaiba season
1 (26/26, all canon), Monster (74/74, all canon), Ouran Koukou Host
Club (26/26: 24 canon / 2 filler), Initial D First Stage (26/26, all
canon), Project ARMS (26/26, all canon), Shugo Chara! (51/51: 32 canon
/ 9 mixed / 10 filler), Edens Zero season 1 (25/25, all canon).

**New this batch, per #111's air-date work and Andreas's request to
capture air dates/titles in the same pass rather than redo it later**:
every show in this batch launched with air dates AND episode titles
already populated at load time, sourced from Wikipedia's per-episode
tables (same validated scraper/methodology as the full-catalog
backfill), not left for a later pass or the weaker AniList
`streamingEpisodes` auto-backfill. All 10 shows hit 100% air-date and
100% title coverage on load — confirmed live.

**Two shows swapped out of the original candidate picks after real
sourcing problems, not force-fitted**: Urusei Yatsura (195 episodes per
AniList/Wikipedia) turned out to have every available fan-guide
aggregator (animefillerlist, otakukan, simkl) independently capping at
only 167 episodes with zero signal for the remaining ~28 — a real
episode-counting-scheme mismatch, not a gap worth guessing across, so
it was dropped rather than loaded with an unexplained tail of
unresearched episodes. Detective School Q / Tantei Gakuen Q and
Kinnikuman (1983) were dropped for the same reason: every fetchable
source either 404'd, returned content for a different show entirely
(one animefillerlist fetch returned Fairy Tail OVA data), or disagreed
with AniList's own episode count outright (animefillerlist reported 25
total episodes for a show AniList and Wikipedia both confirm has 45).
Replaced with Sailor Moon Crystal, Shugo Chara!, and Edens Zero, all
three cleanly sourced. All three dropped shows remain valid future
candidates if a better source ever turns up — not permanently ruled
out, just not force-fitted here.

**Ouran Koukou Host Club's episodes 25-26** are the one disputed
judgment call in this batch: an anime-original two-part finale
(confirmed directly via Anime News Network's own review) invented
because the manga — which continued for four years afterward — hadn't
reached an ending yet. Classified filler under this project's
established "anime invents an ending that replaces where the source
was headed" precedent (FMA 2003, Ao no Exorcist), rather than the
"inserted side material within an ongoing adaptation" pattern that
gets classified canon (Railgun, Akame ga Kill!) — a per-show judgment
call each time, not a fixed rule, consistent with how this project has
handled every prior case of this kind.

**Shugo Chara!'s episode 9** was genuinely ambiguous in the primary
source's own summarized fetch (silently missing from all three status
buckets) — resolved by fetching a second independent source
(The Filler List) which explicitly confirmed it as manga canon, rather
than guessing from neighboring episodes' pattern.

Loaded into production the same throwaway-container way as every prior
batch, air dates loaded in the same pass via a direct `series_episode_schedule`
upsert (additive, `ON CONFLICT DO NOTHING`). Verified live: all ten
series' episode/title/air-date coverage confirmed via the public API.

## Seventh batch (#115, 2026-08-26): Berserk (1997), Dr. Stone, Jujutsu Kaisen, Vinland Saga, Fire Force, Parasyte -the maxim-, Tokyo Revengers, Rurouni Kenshin (2023), Akatsuki no Yona, Nanatsu no Taizai: Mokushiroku no Yonkishi

10 shows, 241 episodes total: Kenpuu Denki Berserk / 1997 (25/25, all
canon), Dr. Stone (24/24, all canon), Jujutsu Kaisen season 1 (24/24,
all canon), Vinland Saga season 1 (24/24: 23 canon / 1 mixed — episode
6), Enen no Shouboutai / Fire Force season 1 (24/24, all canon),
Kiseijuu: Sei no Kakuritsu / Parasyte -the maxim- (24/24, all canon),
Tokyo Revengers season 1 (24/24, all canon), Rurouni Kenshin (2023)
season 1 (24/24, all canon), Akatsuki no Yona (24/24, all canon),
Nanatsu no Taizai: Mokushiroku no Yonkishi season 1 (24/24, all canon).
Heavily skewed toward zero-filler shows this batch — not by design,
just how the research came out (modern faithful adaptations and one
classic near-1:1 adaptation).

**This batch's extraction used a corrected scraper** (`wiki_scrape_v2.py`,
built the same day after a real bug was found — see the dated entry in
`CLAUDE.local.md` for the full incident). The original scraper's
per-row date/title search could silently consume forward into a
following episode's row whenever the current row's own data was
malformed, corrupting both the batch-6 title data and the full-catalog
title/air-date backfill already in production; both were audited and
corrected (1,649 title fixes, 65 date fixes) before this batch started.

**Three shows swapped out after real sourcing problems, not
force-fitted**: Urusei Yatsura (re-attempted from batch #113, same
167-vs-195-episode aggregator gap as before), Tantei Gakuen Q and
Kinnikuman (also re-attempted, same issues as #113 — every fetchable
source either 404'd, disagreed with AniList's confirmed count, or
returned wrong content). **A fourth show, Yashahime: Princess
Half-Demon, was dropped for a different reason discovered mid-research**:
its manga is a *later* adaptation of the anime (started 2021, by a
different author, after the anime), not a source the anime was adapted
from — the reverse of every other show in this catalog, and a genuine
scope mismatch with this project's whole "filler = anime content not
adapted from a preceding manga" premise. Treated the same as previously-
excluded original-anime shows (Code Geass, Evangelion, Samurai Champloo)
rather than force a filler/canon call onto a show with no source manga
to compare against. Replaced with Rurouni Kenshin (2023), Akatsuki no
Yona, and Nanatsu no Taizai: Mokushiroku no Yonkishi — all three
confirmed manga adaptations with clean, single-table Wikipedia pages
and consistent "0% filler" signal from at least one direct fetch.

Loaded into production the same throwaway-container way as every prior
batch, air dates loaded the same pass via the same validated
`series_episode_schedule` upsert. Verified live: all ten series'
episode/title/air-date coverage confirmed via the public API.

## Eighth batch (#118, 2026-08-26): Diamond no Ace: Act II, Shaman King (2021), Angel Heart, Ao Ashi, Blue Lock, Mahoutsukai no Yome, Undead Unluck, Ansatsu Kyoushitsu, Made in Abyss, Bleach: Sennen Kessen-hen

10 shows, 348 episodes total: Diamond no Ace: Act II (52/52: 49 canon
/ 2 mixed / 1 filler), Shaman King (2021) (52/52, all canon), Angel
Heart (50/50: 49 canon / 1 filler), Ao Ashi (24/24, all canon), Blue
Lock season 1 (24/24, all canon), Mahoutsukai no Yome season 1 (24/24,
all canon), Undead Unluck (24/24, all canon), Ansatsu Kyoushitsu
season 1 (22/22: 21 canon / 1 mixed), Made in Abyss season 1 (13/13,
all canon), Bleach: Sennen Kessen-hen cour 1 (13/13, all canon — a
stark contrast to the original Bleach already in this catalog, 163 of
366 episodes filler).

**Andreas asked that dropped candidates go into a durable bucket
instead of silently disappearing** — see `data/bootstrap/
needs-manual-research.json` (added this same session, tracked in
#117) for the full standing process. Checked first before picking
this batch's 10; Devilman (1972) was attempted and added to it after
this batch's own research: every filler-guide site's "Devilman"
results turned out to actually be for Devilman Crybaby (2018), an
unrelated adaptation, and no itemized per-episode source exists
anywhere for the real 1972 series. Replaced with Bleach: Sennen
Kessen-hen, which connects naturally to the already-loaded original
Bleach.

**Diamond no Ace: Act II required real numbering-scheme detective
work**: AniList's own dates for this specific catalog entry (2019-04-02
to 2020-03-31) didn't match what a naive offset assumption would have
produced from Wikipedia's combined "List of Ace of Diamond episodes"
page — the page actually bundles THREE distinct broadcast runs under
one continuous numbering (original series 1-75, a second season 76-126
not in this catalog at all, then Act II proper at 127-178, with a real
3-year broadcast gap between 126 and 127 confirming the boundary).
Verified against AniList's exact start/end dates before committing to
offset 126, rather than the more obvious-looking offset 75. Bleach:
Sennen Kessen-hen has a similar but simpler case — its Wikipedia page
continues the original Bleach's absolute numbering starting at 367,
confirmed via the exact same air-date cross-check technique used for
Bleach's own original air-date backfill earlier this session.

Loaded into production the same throwaway-container way as every prior
batch, air dates loaded the same pass via the same validated
`series_episode_schedule` upsert. Verified live: all ten series'
episode/title/air-date coverage confirmed via the public API.

## Ninth batch (#119, 2026-08-26): Beastars, Chainsaw Man, Dandadan, Dorohedoro, Golden Kamuy, Mob Psycho 100, Spy x Family, Bungou Stray Dogs, Komi-san wa Comyushou desu, Kaguya-sama wa Kokurasetai

10 shows, 120 episodes total, all season 1: Beastars, Chainsaw Man,
Dandadan, Dorohedoro, Golden Kamuy, Mob Psycho 100, Spy x Family,
Bungou Stray Dogs, Komi-san wa, Comyushou desu., Kaguya-sama wa
Kokurasetai — every single one 12/12 all canon, no filler. First
batch picked from the cleaned-up candidate pool: before this batch,
`needs-manual-research.json` gained 43 new permanent-exclusion entries
(12 movies with no per-episode concept, 30 non-manga-based shows —
light novel/visual novel/toy-game franchise/original-anime adaptations
that don't fit this project's premise, 1 single-episode highlight
special), narrowing the nominal 103 remaining candidates down to a
real 60. Andreas asked that dropped candidates always land in a
durable bucket rather than disappear silently — this cleanup pass is
that same principle applied retroactively to the whole remaining list
at once, not just future drops.

Loaded into production the same throwaway-container way as every prior
batch, air dates loaded the same pass via the same validated
`series_episode_schedule` upsert. Verified live: all ten series'
episode/title/air-date coverage confirmed via the public API. 50
candidates remain.

## Tenth batch (#120, 2026-08-26): Shokugeki no Souma seasons 2-5, Kaijuu 8-gou, Mashle, Jigokuraku, Zom 100, Houseki no Kuni, Sono Bisque Doll wa Koi wo Suru

10 shows, 124 episodes total: Shokugeki no Souma Ni no Sara (13/13),
San no Sara (12/12), Shin no Sara (12/12), Gou no Sara (13/13) — all
four all canon, no filler across the whole 5-season franchise now
that seasons 2-5 join the already-loaded season 1. Kaijuu 8-gou
(12/12, all canon), Jigokuraku (13/13, all canon), Zom 100 (12/12, all
canon), Houseki no Kuni (12/12, all canon), Sono Bisque Doll wa Koi wo
Suru (12/12, all canon), Mashle (12/12: 11 canon / 1 filler — episode
7, the one reported filler episode).

Goblin Slayer was picked initially, then dropped to
`needs-manual-research.json` mid-prep as scope_mismatch: it's a light
novel adaptation (the anime follows Kumo Kagyu's novels, not the
manga that runs alongside), same category as the already-excluded
Overlord/Konosuba. Replaced with Sono Bisque Doll wa Koi wo Suru.

**Real numbering-scheme work for the four Shokugeki sequels**:
Wikipedia's four "season N" articles use continuous absolute
numbering across the whole 86-episode franchise, but the season
boundaries don't line up 1:1 with this catalog's 4 separate AniList
entries the way a naive accumulation would suggest — verified each
entry's real offset directly against AniList's own exact start/end
air dates rather than assuming a clean running total (a 12-episode
gap between San no Sara and Shin no Sara's expected ranges turned out
to be non-catalog bridge/OVA content on the same Wikipedia page, not
a counting error). Confirmed offsets: Ni no Sara +24, San no Sara +37,
Shin no Sara +61, Gou no Sara +73 — each checked against the exact
AniList start-date match before trusting it.

Loaded into production the same throwaway-container way as every prior
batch, air dates loaded the same pass via the same validated
`series_episode_schedule` upsert. Verified live: all ten series'
episode/title/air-date coverage confirmed via the public API. 40
candidates remain.

## Eleventh batch (#121, 2026-08-26): Black Cat, Blue Period, Fumetsu no Anata e, Gachiakuta, Ijiranaide Nagatoro-san, Kamonohashi Ron no Kindan Suiri, Masamune-kun no Revenge, Ousama Ranking, Shadows House, Record of Ragnarok

10 shows, 165 episodes total: Black Cat (24/24: 20 canon / 4 filler —
episodes 21-24 are a wholly original anime-only arc extending past
the manga's ending, classified filler per this project's established
anime-original-ending precedent), Blue Period (12/12, all canon —
no Wikipedia episode-list page exists for this show, so air dates/
titles rely on AniList's own backfill instead), Fumetsu no Anata e
season 1 (20/20, all canon), Gachiakuta (24/24, all canon), Ijiranaide
Nagatoro-san season 1 (12/12, all canon), Kamonohashi Ron no Kindan
Suiri season 1 (13/13, all canon), Masamune-kun no Revenge season 1
(12/12, all canon), Ousama Ranking (23/23, all canon), Shadows House
season 1 (13/13: 10 canon / 1 mixed / 2 filler — an anime-original
bridge to season 2), Record of Ragnarok season 1 (12/12, all canon).

Two candidates dropped mid-research and added to
`needs-manual-research.json`: Lupin III (1971 original series) — no
itemized filler/canon guide found anywhere, and conceptually murkier
than a typical gap (multiple sources describe the classic-era show as
having no strict continuity between episodes, standalone stories
loosely riffing on the manga rather than a chapter-by-chapter
adaptation, similar to the Devilman case). Katsute Kami Datta
Kemono-tachi e was tried as a replacement and also dropped (niche
enough that no filler-guide site has compiled a breakdown at all).
Landed on Record of Ragnarok as the actual tenth show.

Loaded into production the same throwaway-container way as every prior
batch, air dates loaded the same pass via the same validated
`series_episode_schedule` upsert. Verified live: all ten series'
episode/title/air-date coverage confirmed via the public API (Blue
Period excepted, per its missing Wikipedia source above). 30
candidates remain.

## Twelfth batch (#122, 2026-08-26): Gin no Saji, Fairy Tail: 100-nen Quest, GANTZ, Shaman King: Flowers, Mugen no Juunin: Immortal, Vigilante: MHA Illegals, Toaru Kagaku no Accelerator, To LOVE-Ru Darkness, Kanojo mo Kanojo, Shoujo Shuumatsu Ryokou

10 shows, 147 episodes total: Gin no Saji (11/11: 10 canon / 1 mixed),
Fairy Tail: 100-nen Quest (25/25, all canon), GANTZ (13/13: 12 canon /
1 mixed — First Stage only; the franchise's real 5-episode filler run
is entirely in the separate Second Stage, outside this catalog
entry), Shaman King: Flowers (13/13, all canon), Mugen no Juunin:
Immortal (24/24, all canon), Vigilante: Boku no Hero Academia
Illegals season 1 (13/13, all canon), Toaru Kagaku no Accelerator
(12/12: 11 canon / 1 filler — episode 1), To LOVE-Ru Darkness (12/12,
all canon), Kanojo mo Kanojo season 1 (12/12, all canon — no
Wikipedia episode-list page exists, air dates/titles rely on
AniList's own backfill), Shoujo Shuumatsu Ryokou (12/12, all canon).

**GANTZ resolved a real, pre-existing data-quality gap**: its
`series-candidates.json` entry had no AniList id recorded at all and
an incorrect 26-episode count (the real total for the combined
First+Second Stage, not this catalog entry specifically). Resolved
the correct AniList id (384, First Stage, 13 episodes) directly and
updated the live `series` row's `anilist_id` column (previously NULL)
to match — a safe, additive correction (filling a null, not altering
existing data), not a schema change.

Seven more shows added to `needs-manual-research.json` while reviewing
the remaining pool for this batch: Charlotte, Dungeon ni Deai wo
Motomeru no wa Machigatteiru Darou ka, Hataraku Maou-sama!, Koutetsujou
no Kabaneri, and Yu-Gi-Oh! Arc-V (scope_mismatch — not manga-based),
plus Ranma 1/2 Nettou Hen and Shingeki no Kyojin OAD (sourcing_gap,
formalizing known problems from earlier in the session).

Loaded into production the same throwaway-container way as every prior
batch, air dates loaded the same pass via the same validated
`series_episode_schedule` upsert. Verified live: all ten series'
episode/title/air-date coverage confirmed via the public API (Kanojo
mo Kanojo excepted, per its missing Wikipedia source above). 17
candidates remain.

## Thirteenth and FINAL batch (#123, 2026-08-26): Cobra The Animation, Dragon Quest: Dai no Daibouken (2020), Eikoku Koi Monogatari Emma, Hellsing Ultimate, Excel Saga, JoJo no Kimyou na Bouken: Adventure, Kishibe Rohan wa Ugokanai, MF Ghost, Souten no Ken: Regenesis 2nd Season, Summertime Render

10 shows, 221 episodes total, closing out the entire manami-project
candidate list. Cobra The Animation (13/13, all canon), Dragon Quest:
Dai no Daibouken 2020 (100/100, all canon — a complete adaptation of
the full manga), Eikoku Koi Monogatari Emma season 1 (12/12, all
canon — see disclosed lower-confidence note below), Hellsing Ultimate
(10/10, all canon — a deliberate contrast to the original 2001 Hellsing
TV series' 46% filler), JoJo no Kimyou na Bouken: Adventure (7/7, all
canon), Kishibe Rohan wa Ugokanai (4/4, all canon), MF Ghost season 1
(12/12, all canon), Souten no Ken: Regenesis 2nd Season (12/12, all
canon), Summertime Render (25/25, all canon), and Heppoko Jikken
Animation Excel♥Saga (26/26, **all filler** — see below).

**Excel Saga is a genuine one-off case, unlike anything else in this
catalog**: the entire anime deliberately diverges from Rikdo Koshi's
manga throughout, at the publisher's own request and with the
creator's approval — not scattered padding around an otherwise-adapting
story the way every other filler-carrying show in this catalog works,
but a wholesale reimagining from episode 1. animefillerlist.com
independently confirms the identical 100% figure. Included (unlike
Yashahime or Devilman) because the manga genuinely existed first and
the divergence is fully documented, not because the classification is
ambiguous — every episode is confidently filler, just unusually all
of them.

**Eikoku Koi Monogatari Emma's season-1 canon classification is
disclosed as lower-confidence**: no itemized per-episode filler guide
could be found anywhere for this show. Classified canon on indirect
but consistent evidence instead — sources describe this season
covering only 2 of the manga's 7 volumes across 12 episodes (ample
source material, no compression pressure) and specifically attribute
the real filler content found in the separate, later season 2 to a
distinct compression problem (5 remaining volumes into 12 episodes)
that doesn't apply here.

Three shows (Hellsing Ultimate, Kishibe Rohan wa Ugokanai, Souten no
Ken: Regenesis 2nd Season) have no usable Wikipedia episode-list page
at all; their air dates/titles rely entirely on AniList's own
rolling-window backfill, which filled in reasonably well for two of
the three (Souten no Ken picked up all 12 titles from AniList
directly) but left Hellsing Ultimate and Kishibe Rohan with none.

Loaded into production the same throwaway-container way as every
prior batch, air dates loaded the same pass via the same validated
`series_episode_schedule` upsert. Verified live: all ten series'
episode/title/air-date coverage confirmed via the public API (per the
three exceptions noted above).

**This closes out every real candidate from the original
manami-project bootstrap list (`series-candidates.json`).** Of the
original 180 entries: 123 shows are now loaded across thirteen
batches (#104, #105, #109, #110, #113, #115, #118, #119, #120, #121,
#122, #123, plus the original seven from #5), and the remainder sit
in `data/bootstrap/needs-manual-research.json` for Andreas to review
by hand — some genuine sourcing gaps worth another look if a better
guide ever surfaces, some permanent scope exclusions (movies,
non-manga-based shows) that were never really candidates for this
project's premise to begin with.

## Post-audit review corrections and franchise completion (2026-08-27)

Andreas worked through the confidence-audit artifact (episode-data-audit)
and hand-compiled his own cross-referenced filler/canon breakdowns for
three shows, checking them directly against what was loaded:

- **Gintama** (369 eps) — his list matched the loaded data exactly, 0
  discrepancies across all 369 episodes. No data change; confirms this
  show's original single-source loading was correct.
- **GANTZ First Stage** (13 eps, already loaded) — also matched exactly.
  His list, however, was continuous numbering across First Stage *and*
  Second Stage (26 episodes total) — Second Stage had never been loaded
  as its own catalog entry. Added it: **GANTZ 2** (AniList id 395, 13
  eps: 7 canon / 1 mixed / 5 filler), confirming the 5-episode filler run
  the original GANTZ citation note had already flagged as belonging to
  Second Stage, just never itemized.
- **Bishoujo Senshi Sailor Moon** (46 eps, already loaded) — 6 real
  corrections (episodes 13, 14, 23, 24, 36, 42, canon→mixed), applied via
  `--allow-corrections`. His list was also continuous numbering, this
  time across the entire 200-episode original run (all five
  Sailor Moon seasons) — the other 154 episodes belonged to three
  sequel seasons never in this catalog at all. Added them as new,
  community-provenance entries (not part of the original manami-project
  snapshot, so `provenance = 'community'` rather than
  `manami_bootstrap`) after confirming the season boundaries two ways —
  the four seasons' real episode counts (46+43+38+39+34 = 200 exactly)
  and each season's AniList air-date range picking up within days of the
  previous one's end:
  - Bishoujo Senshi Sailor Moon R (AniList 740, 43 eps: 15/23/5)
  - Bishoujo Senshi Sailor Moon S (AniList 532, 38 eps: 17/15/6)
  - Bishoujo Senshi Sailor Moon SuperS (AniList 1239, 39 eps: 16/23/0)
  - Bishoujo Senshi Sailor Moon: Sailor Stars (AniList 996, 34 eps: 25/9/0)

  Sailor Moon Crystal (the 2014 reboot) needed no changes — Andreas
  independently confirmed it has no fillers, matching the already-loaded
  26/26 all-canon data.

All five new entries and the one correction cite Andreas's own manual
cross-reference review directly (no single external URL — same citation
model as a real moderator correction) rather than a fetched guide site.
Verified against local test-pg before touching production; loaded into
production via the same throwaway-container pattern as every prior
batch.

## More post-audit review corrections and franchise completion (2026-08-27, batch 2)

Andreas continued working through the confidence-audit artifact and sent
hand-compiled cross-referenced breakdowns for seven more shows in one
batch:

- **Rosario to Vampire, Shadows House, Shugo Chara!** — all three
  matched their already-loaded season-1 data exactly (0 discrepancies).
  Same pattern as GANTZ/Sailor Moon in the prior batch: his numbering
  was continuous across sequel seasons never loaded before. Added:
  - Rosario to Vampire Capu2 (AniList 4214, 13 eps: 3 canon / 3 mixed / 7 filler)
  - Shadows House 2nd Season (AniList 139093, 12 eps: 11 canon / 1 mixed / 0 filler)
  - Shugo Chara!! Doki (AniList 5262, 50 eps loaded, 1 skipped — see below)
  - Shugo Chara! Party! (AniList 7082, 25 eps)
- **Tennis no Oujisama** — previously in the manual-research queue
  (`needs-manual-research.json`) as a sourcing gap: the only fetchable
  guide covered just episodes 1-33. Andreas's list covers the full
  178-episode run (1 episode, #105, omitted rather than guessed — see
  below). **This fully resolves the prior sourcing-gap flag**, removed
  from the manual-research queue.
- **Urusei Yatsura** — also previously flagged: every aggregator caps
  out at episode 167 of a confirmed 194-195 total. Andreas's list also
  covers exactly 1-167 (same cap), so this **narrows but doesn't fully
  resolve** the gap — loaded what we have, updated the manual-research
  entry to flag only the remaining 168-195 as still unresearched.
- **Tantei Gakuen Q** — same pattern: previously flagged at a
  25-of-45-episode source gap, Andreas's list covers 1-26 (1 episode,
  #19, omitted — see below). Narrows the gap to 27-45 (19 eps),
  updated the manual-research entry accordingly.
- **Kinnikuman** — Andreas found only a general note ("a filler arc is
  added in the anime: the Poison Six Pack arc"), no episode numbers.
  Not enough to load per-episode data from directly; a follow-up
  research pass is needed to pin down the actual episode range before
  this can be loaded.

**Three single-episode gaps left unresolved, deliberately not guessed**:
Shugo Chara!! Doki's episode 73 (local ep 22), Tennis no Oujisama's
episode 105, and Tantei Gakuen Q's episode 19 were each missing from
Andreas's ranges with no explicit status given — each sits at a
plausible boundary (a status could reasonably continue from either
neighbor), so rather than infer one, they were left out of the loaded
episode set entirely (silently absent = unresearched, not a wrong
guess). Flagged back to Andreas directly to fill in the three single
values rather than silently choosing.

All new/loaded data cites Andreas's own manual cross-reference review
directly (no external URL), same citation model as the prior batch.
Verified against local test-pg (which needed its own series-catalog
backfill first — it was stuck on a stale partial import missing ~100
of the 187 real catalog rows, including several of these shows'
base entries; re-ran `load_series.py` against it to bring it back in
sync with production) before touching production.

## Kinnikuman resolved via research subagent (2026-08-27)

Andreas's original lead for Kinnikuman ("a filler arc is added in the
anime: the Poison Six Pack arc") turned out to belong to a completely
different, later show — **Kinnikuman Nisei / Ultimate Muscle: The
Kinnikuman Legacy (2002-2004)**, not this project's 137-episode 1983
series at all (same class of franchise-entry mixup already seen with
Yashahime and the animefillerlist.com/.tv confusion earlier in this
project's history). A dedicated research pass instead found the real
divergence point: the anime runs anime-original material for its final
18 episodes (120-137 — the Ultimate Choujin and Nefarious Choujin arcs),
confirmed directly against Wikipedia's own arc-by-arc episode listing,
after the manga had only been adapted through episode 119. Loaded as
119 canon / 18 filler, with the boundary treated as solid but the
anime-original characterization disclosed as a lower-confidence,
cross-referenced-but-not-primary-read call (the primary wiki source
couldn't be fetched directly). Removed from
`needs-manual-research.json` — 57 entries remain.

## Bleach: Thousand-Year Blood War Parts 2-3 added (2026-08-27)

Andreas flagged that Bleach: Sennen Kessen-hen (loaded as Part 1 only,
13 eps) was showing as FINISHED when the real show is still airing —
same "franchise split across multiple separate AniList catalog
entries" pattern already hit with Sailor Moon/GANTZ/Rosario to Vampire/
Shadows House/Shugo Chara!. Checked AniList directly: the real show is
split across FOUR cour-based entries. Part 1 "The Blood Warfare"
(already loaded) is correctly FINISHED on its own. Added:

- Part 2 "The Separation"/"Ketsubetsu-tan" (AniList 159322, 13 eps,
  all canon, adapts ch.542-609)
- Part 3 "The Conflict"/"Soukoku-tan" (AniList 169755, 14 eps, all
  canon, adapts ch.609-661)

Both confirmed 100% canon by two independently-fetched sources
agreeing exactly on episode count and chapter range. Anime-original
scenes are inserted within several otherwise-canon episodes (per
Sportskeeda's per-episode anime-vs-manga comparisons) but no source
flags any full episode as filler/mixed in either part.

**Part 4 "The Calamity"/"Kashin-tan" (AniList 185874, 10 eps total,
RELEASING since 2026-07-25) deliberately NOT added yet** — only 5 of
10 episodes have aired as of this writing, and no source has a
reliable per-episode filler/canon breakdown for it. Real signal that
Part 4 differs from Parts 1-3: two independent sources note it adapts
an unusually low chapters-per-episode ratio (~22 chapters across 10
episodes, vs. Parts 2-3's ~65-70 chapters across 13-14 episodes),
consistent with meaningfully more anime-original padding than the
earlier parts — likely to give the ending room to breathe after the
manga's own rushed finale. Revisit once the remaining episodes air and
a dedicated per-episode Part 4 guide exists.
