-- #250: bot/human traffic classification (userAgent-derived, see
-- services/traffic_analytics.py's classify_bot()) and hourly rollups
-- alongside the existing unlimited-history daily ones. Additive only.
--
-- bot_breakdown on traffic_daily_rollups: existing rows get '[]' via the
-- column default — the dashboard already treats an empty breakdown list
-- as "no data recorded," so pre-migration days simply show no bot split,
-- not an error.
--
-- traffic_hourly_rollups mirrors traffic_daily_rollups' shape exactly,
-- but serves a different purpose (recent-detail investigation, not
-- long-term trend) and so gets its own 7-day retention, pruned by
-- services/traffic_analytics.py's run_hourly_traffic_rollup() after each
-- cycle — not a set-and-forget table like its daily sibling.
ALTER TABLE traffic_daily_rollups
    ADD COLUMN bot_breakdown JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE traffic_hourly_rollups (
    id                SERIAL PRIMARY KEY,
    rollup_hour       TIMESTAMPTZ NOT NULL UNIQUE,
    total_requests    INTEGER NOT NULL,
    top_paths         JSONB NOT NULL,
    status_breakdown  JSONB NOT NULL,
    top_countries     JSONB NOT NULL,
    bot_breakdown     JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX traffic_hourly_rollups_rollup_hour_desc ON traffic_hourly_rollups (rollup_hour DESC);
