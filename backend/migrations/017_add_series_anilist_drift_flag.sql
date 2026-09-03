-- Issue #175 — additive only (two new nullable columns), fine per
-- CLAUDE.md Guardrails without needing to ask first. Run by hand against
-- the live Postgres, same as every migration in this project (see
-- migrations/README.md).
--
-- #49's daily sync worker permanently stops re-checking a series once
-- AniList first reports anilist_status = 'FINISHED' (see
-- repositories/series_episode_schedule.py's list_series_needing_sync) —
-- correct for the common case, but a real status change afterward (a
-- long-running shounen resuming from hiatus, more episodes added) is
-- never detected. This adds a third, weekly, lightweight worker loop
-- (services/anilist_sync.py's check_finished_series_drift) that re-checks
-- every FINISHED series' status + episode count and flags drift here.
--
-- anilist_drift_flagged_at is NULL for "no drift currently detected" —
-- the weekly loop clears it back to NULL if a later re-check finds the
-- series is no longer drifted (e.g. AniList briefly glitches then
-- reports FINISHED again), so this column always reflects the *current*
-- drift state, not a historical "was ever flagged" record. Consumed
-- later by #153's "needs research" queue, not this issue's scope.
--
-- anilist_drift_reason records *why*, so a future consumer doesn't need
-- to re-derive it: 'status_drift' (AniList's live status is no longer
-- FINISHED) or 'episode_count_drift' (AniList's live episode count now
-- exceeds what this project has recorded/researched).

ALTER TABLE series ADD COLUMN anilist_drift_flagged_at TIMESTAMPTZ;
ALTER TABLE series ADD COLUMN anilist_drift_reason TEXT
    CHECK (anilist_drift_reason IN ('status_drift', 'episode_count_drift'));
