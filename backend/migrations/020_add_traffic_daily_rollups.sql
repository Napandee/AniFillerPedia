-- #221: daily Cloudflare zone-analytics rollup (implementation of #219's
-- decision to use Cloudflare's own passive zone analytics rather than a
-- client-side beacon — see #219's closing comment for the full reasoning).
-- Additive only — a brand-new table, no existing column touched.
--
-- One row per UTC calendar day the rollup loop actually ran, keyed by
-- rollup_date so a same-day rerun (e.g. a worker restart) safely
-- overwrites that day's row via ON CONFLICT rather than accumulating
-- duplicates (see repositories/traffic_analytics.py).
--
-- top_paths / status_breakdown / top_countries are JSONB rather than
-- their own normalized tables — this is a small, admin-only, read-mostly
-- rollup (not something ever joined/filtered on by sub-field), and this
-- project already has precedent for a JSONB payload column on a
-- moderation-facing row (series_proposals.episode_data, #85) rather than
-- normalizing every nested shape into its own table.
--
-- path_kind (frontend vs. api, split on whether a path starts with
-- "/api/v1/") lives inside each top_paths entry rather than as a
-- top-level column, since the split only ever matters at the
-- per-path granularity the issue asks for ("top N paths ... with a
-- path_kind discriminator").
CREATE TABLE traffic_daily_rollups (
    id                SERIAL PRIMARY KEY,
    rollup_date       DATE NOT NULL UNIQUE,
    total_requests    INTEGER NOT NULL,
    top_paths         JSONB NOT NULL,   -- [{"path": str, "path_kind": "frontend"|"api", "count": int}, ...]
    status_breakdown  JSONB NOT NULL,   -- [{"status": int, "count": int}, ...]
    top_countries     JSONB NOT NULL,   -- [{"country": str, "count": int}, ...]
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dashboard's own access pattern is "most recent N days, newest first" —
-- the UNIQUE constraint above already gives us an index on rollup_date,
-- but an explicit DESC index matches the actual query order rather than
-- relying on a backward index scan.
CREATE INDEX traffic_daily_rollups_rollup_date_desc ON traffic_daily_rollups (rollup_date DESC);
