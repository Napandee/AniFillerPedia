-- #49: additive columns + table for a repeatable, cadence-aware AniList
-- episode-count/air-date sync. No column dropped or altered, no existing
-- row touched.
--
-- series.anilist_status mirrors AniList's own Media.status (FINISHED,
-- RELEASING, etc.) — the sync cadence signal: a series already confirmed
-- FINISHED doesn't need re-fetching on every cycle, only RELEASING (or
-- never-synced, NULL) series do. episode_schedule_synced_at just records
-- when a series was last checked, for observability.
--
-- series_episode_schedule is deliberately separate from `episodes`: this
-- table only ever records "does episode N exist and when did it air,"
-- independent of any filler/canon research — `episodes` still only gets a
-- row once a contribution is actually approved (see schema.sql header).
--
-- anilist_episode_count is its own column, not left to be inferred from
-- series_episode_schedule's row count: AniList's airingSchedule field only
-- retains a rolling window of nodes (confirmed live 2026-08-22 — a
-- long-finished, 500-episode show like Naruto: Shippuden returns only its
-- last 3 episodes' worth of schedule nodes, not a full historical
-- archive), while Media.episodes (the total count) is reliably present
-- regardless. Without this column, an old finished show would look like
-- it only has 3 episodes rather than its real total.

ALTER TABLE series ADD COLUMN anilist_status TEXT;
ALTER TABLE series ADD COLUMN anilist_episode_count INTEGER;
ALTER TABLE series ADD COLUMN episode_schedule_synced_at TIMESTAMPTZ;

CREATE TABLE series_episode_schedule (
    series_id       INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    episode_number  INTEGER NOT NULL,
    aired_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (series_id, episode_number)
);
