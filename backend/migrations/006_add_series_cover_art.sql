-- #46 follow-up, decided 2026-08-22: cover/banner art was originally
-- fetched live from AniList on every single page load (frontend calling
-- AniList's GraphQL API directly at request time) — reasonable-looking at
-- first, but a real AniList outage ("The AniList API has been temporarily
-- disabled due to severe stability issues", confirmed live) took down
-- cover art site-wide, on every card, simultaneously. Cover/banner URLs
-- are effectively static per series, so there's no good reason for this to
-- be a synchronous third-party dependency on every page render.
--
-- Folded into #49's existing sync worker instead (which already fetches
-- from AniList on a sensible cadence, already skips FINISHED shows) —
-- these two columns are populated there, and the frontend reads them from
-- our own API like anything else, no live AniList call at request time.
ALTER TABLE series ADD COLUMN anilist_cover_url TEXT;
ALTER TABLE series ADD COLUMN anilist_banner_url TEXT;
