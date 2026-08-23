-- #73/#74: two independent additive fields, shipped together since both
-- came out of the same episode-row-enrichment design pass.
--
-- episodes.title (#73) — reopens #33's original "skip for v1" decision.
-- Nullable: most episodes across the not-yet-researched catalog will have
-- no title for a long time, and even researched shows only get partial
-- coverage (see the AniList streamingEpisodes backfill script — it's a
-- rolling/partial field on AniList's own side, not a full archive, the
-- same limitation #49 already documented for airingSchedule).
ALTER TABLE episodes ADD COLUMN title TEXT;

-- citations.source_count (#74) — how many independent sources were cross-
-- referenced for this citation, backing the "N independent sources agree"
-- badge on the episode detail panel. NOT NULL DEFAULT 1 rather than
-- nullable: every citation has at least the one source that produced it,
-- so 1 is a real, correct value for existing rows, not a placeholder.
-- Deliberately NOT derived from counting a citation's merged citation_ids
-- (load_episodes.py's multi-source combining) — a combo can legitimately
-- include a source that was cited and then overridden (e.g. Bleach episode
-- 227's citation cites both the winning Reddit sources and the dissenting
-- Radio Times guide for audit purposes), so "how many sources are cited"
-- and "how many sources agree with the final status" are different
-- numbers. source_count is authored explicitly per episode for exactly
-- this reason.
ALTER TABLE citations ADD COLUMN source_count INTEGER NOT NULL DEFAULT 1;
