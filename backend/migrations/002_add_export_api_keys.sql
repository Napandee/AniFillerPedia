-- Issue #22 — additive only (new table), fine per CLAUDE.md Guardrails
-- without needing to ask first. Run by hand against the live Postgres,
-- same as every migration in this project (see migrations/README.md).

CREATE TABLE export_api_keys (
    id                SERIAL PRIMARY KEY,
    key_hash          TEXT NOT NULL UNIQUE,
    email             TEXT NOT NULL,
    license_accepted  BOOLEAN NOT NULL,
    terms_version     TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at        TIMESTAMPTZ
);
