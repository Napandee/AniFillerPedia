-- AniFillerPedia — Postgres schema
-- Fresh-install target schema (matching Napandee/AniDex's convention) — the
-- upgrade path for an already-running database lives in migrations/, not
-- here. This is the v1 schema; no migrations exist yet.
--
-- Design principles (see CLAUDE.md Decisions Made / Architecture for the
-- full reasoning behind each):
--   * The series catalog is community-grown, not auto-synced — bootstrapped
--     once from manami-project's archived snapshot, then extended only via
--     series_proposals. There is no "AniList-sourced, never hand-edit"
--     table the way AniDex has one, because there's no live upstream left
--     to treat as a system of record.
--   * A contribution is never live/authoritative without both a citation
--     and an approval — contributions.citation_id is NOT NULL, and
--     episodes rows only ever come from promoting an approved contribution.
--     This is a structural guarantee, not an app-layer policy.
--   * Every FK to users(id) is ON DELETE SET NULL, not CASCADE — deleting
--     an account anonymizes their past contributions/votes/citations
--     rather than destroying the audit trail those rows exist to preserve
--     (see issue #18, not yet fully resolved, but this is the documented
--     lean and getting it wrong now means a painful migration once real
--     user data exists). Where a column is NOT NULL by business rule today
--     (e.g. contribution_votes.voter_id — a vote needs a voter), it's still
--     made nullable here specifically so deletion can anonymize rather than
--     cascade-delete the row and rewrite resolved history.

-- =========================================================================
-- AUTH
-- =========================================================================

-- One row per person who has ever logged in. OAuth-only — no password
-- fields, since there's no reason to take on password-security surface
-- when GitHub/Discord (and later Google, see issue #24) cover the whole
-- target audience. A user may have any subset of the three provider ids
-- set; account linking across providers is explicit-only (never automatic
-- by email match — see CLAUDE.md), so linking logic lives in the app layer,
-- not enforced here beyond each id being unique when present.
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    github_id     TEXT UNIQUE,
    discord_id    TEXT UNIQUE,
    google_id     TEXT UNIQUE,   -- nullable, reserved for issue #24 (Google OAuth, post-launch, not yet implemented)
    email         TEXT,          -- from whichever provider supplied it; never the login key
    display_name  TEXT,
    avatar_url    TEXT,
    -- 'owner' is a distinct tier above 'admin' (decided 2026-08-21, see
    -- CLAUDE.md), not just a cosmetic label on the bootstrap identity: only
    -- the owner can grant/revoke the 'admin' role, and the owner's own row
    -- can never be changed via the role-promotion endpoint by anyone
    -- (including another admin) — see services/admin.py's update_role().
    -- 'owner' is deliberately excluded from repositories/admin.py's
    -- VALID_ROLES, so it is never assignable through the API at all; it is
    -- set once, at bootstrap (services/auth.py), by matching
    -- INITIAL_ADMIN_GITHUB_ID.
    role          TEXT NOT NULL DEFAULT 'contributor' CHECK (role IN ('contributor', 'moderator', 'admin', 'owner')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

-- =========================================================================
-- SERIES CATALOG (community-grown — see header note above)
-- =========================================================================

-- One row per anime series. Seeded once from manami-project's archived
-- snapshot (provenance='manami_bootstrap'), grown afterward only via
-- series_proposals (provenance='community') — never an unmoderated direct
-- write, matching the same approval-gated model episode contributions use.
CREATE TABLE series (
    id           SERIAL PRIMARY KEY,
    anilist_id   INTEGER UNIQUE,
    mal_id       INTEGER UNIQUE,
    anidb_id     INTEGER UNIQUE,
    title        TEXT NOT NULL,
    provenance   TEXT NOT NULL CHECK (provenance IN ('manami_bootstrap', 'community')),
    added_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- NULL for the one-time bootstrap import
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- #49: AniList's own Media.status (FINISHED, RELEASING, ...) — the
    -- cadence signal for services/anilist_sync.py. A FINISHED series
    -- doesn't need re-fetching on every sync cycle, only RELEASING (or
    -- NULL, never-synced) series do. anilist_episode_count (Media.episodes)
    -- is stored separately from series_episode_schedule's row count
    -- because AniList's airingSchedule field only retains a rolling window
    -- of nodes, not a full historical archive — confirmed live that a
    -- long-finished 500-episode show returns only its last 3 episodes'
    -- worth of schedule nodes, while the total count is reliably present
    -- regardless.
    anilist_status               TEXT,
    anilist_episode_count        INTEGER,
    episode_schedule_synced_at   TIMESTAMPTZ,
    -- #46 follow-up (2026-08-22): cover/banner art, synced here on the same
    -- cadence as the fields above rather than fetched live from AniList on
    -- every page load — a real AniList outage previously took down cover
    -- art site-wide since it was a synchronous per-request dependency.
    anilist_cover_url            TEXT,
    anilist_banner_url           TEXT,
    -- #116: slug-based series URLs (/series/berserk instead of /series/8).
    -- Nullable until backfilled (see migrations/011_backfill_series_slugs.py)
    -- — repositories/series.py's lookup falls back to id when a series has
    -- no slug yet. Generated from title via services/slugs.py; collisions
    -- disambiguated with the series' own numeric id.
    slug                         TEXT UNIQUE,
    -- #126: AniList's own synopsis + air-date range, synced by the same
    -- #49 worker/cadence as the fields above. anilist_description is
    -- cleaned (HTML tags stripped, entities unescaped) before storage —
    -- see services/anilist_sync.py's clean_anilist_description(). The two
    -- date columns are only ever set when AniList's {year, month, day} is
    -- fully complete; a still-airing show simply has a NULL end date.
    anilist_description          TEXT,
    anilist_start_date           DATE,
    anilist_end_date             DATE,
    -- #133: within-franchise watch-order position (e.g. Fairy Tail=1,
    -- Fairy Tail (2014)=2, Fairy Tail (2018)=3, ...). Nullable — most
    -- series are standalone or have no decided order yet; only backfilled
    -- for series already grouped via series_relations below.
    -- services/series.py's get_series() uses this to compute next_series/
    -- previous_series among the current series' own related-series group.
    sequence_order               INTEGER
);

-- Alternate/romanized/native-script titles, captured during the one-time
-- bootstrap import (issue #4) — the upstream manami-project dataset is
-- archived, so this is the only chance to capture this data; it cannot be
-- backfilled later the way a live-synced field could be. Also grows
-- organically afterward if a contributor adds a synonym for a
-- community-added series.
CREATE TABLE series_synonyms (
    id         SERIAL PRIMARY KEY,
    series_id  INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    synonym    TEXT NOT NULL,
    UNIQUE (series_id, synonym)
);

-- #148: a contributor's suggestion to add a synonym to an ALREADY-
-- catalogued series — series_synonyms above has no write path beyond the
-- one-time bootstrap import, so this is what lets it grow post-launch.
-- Deliberately a small, dedicated table rather than extending
-- series_proposals (scoped to "propose a NEW series") or reusing
-- contributions (episode-status-shaped) — see migrations/
-- 015_add_series_synonym_suggestions.sql for the full scope-decision
-- writeup and services/synonym_suggestions.py for the approval flow.
-- Moderator-only approval, not #14's trust-weighted voting — a
-- single-string suggestion is too small a unit to justify the
-- contribution_votes/weight-snapshot/auto-promotion machinery.
-- license_accepted mirrors contributions/series_proposals (CLAUDE.md,
-- issue #21) — structural proof of agreement on every submission.
CREATE TABLE series_synonym_suggestions (
    id            SERIAL PRIMARY KEY,
    series_id     INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    synonym       TEXT NOT NULL,
    note          TEXT,   -- optional context for the moderator, not a required citation
    submitted_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reviewed_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at   TIMESTAMPTZ,
    review_note   TEXT,
    license_accepted BOOLEAN NOT NULL
);

-- Same one-pending-per-target pattern as #20's
-- contributions_one_pending_per_episode below.
CREATE UNIQUE INDEX series_synonym_suggestions_one_pending_per_target
    ON series_synonym_suggestions (series_id, synonym)
    WHERE review_status = 'pending';

-- Lightweight "related series" links for shows split across multiple
-- AniList catalog entries (e.g. Fairy Tail / Fairy Tail (2014) /
-- Fairy Tail (2018)) — decided 2026-08-22 over a heavier "collection"
-- grouping construct; see migration 005's own comment for the full
-- reasoning. Directed pairs — linking two series means inserting both
-- directions, so a plain lookup on either side finds the relation.
CREATE TABLE series_relations (
    series_id         INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    related_series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    PRIMARY KEY (series_id, related_series_id),
    CHECK (series_id != related_series_id)
);

-- A proposal to add a new series to the catalog. Mirrors the episode
-- contributions/approval shape below, but for series-level identity rather
-- than episode-level status. submitted_by is nullable purely to support
-- ON DELETE SET NULL on account deletion (see header note) — whether
-- anonymous series proposals are accepted is an application-layer business
-- rule, not decided by this column's nullability.
CREATE TABLE series_proposals (
    id            SERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    anilist_id    INTEGER,
    mal_id        INTEGER,
    anidb_id      INTEGER,
    justification TEXT NOT NULL,   -- why this show belongs — the series-level equivalent of a citation
    submitted_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reviewed_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at   TIMESTAMPTZ,
    review_note   TEXT,
    -- CC BY-NC-SA structural proof of agreement (CLAUDE.md, issue #21) —
    -- every submission, not a one-time account flag; see the identical
    -- column on contributions below for the full reasoning.
    license_accepted BOOLEAN NOT NULL,
    -- #85: optional episode-range data attached at proposal time, in the
    -- same shape services/contributions.py's bulk-submission path expects
    -- (canon_ranges/mixed_ranges/filler_ranges/citation). NULL until the
    -- proposal is approved, at which point it's turned into real citations
    -- + contributions rows targeting the newly-created series. A rejected
    -- proposal just leaves this sitting here — nothing else references it.
    episode_data JSONB
);

-- =========================================================================
-- CITATIONS + CONTRIBUTIONS (the write surface AND the audit trail)
-- =========================================================================

-- A source backing a specific contribution. url is nullable (some sources
-- are a book/guide with no URL) but description is always required — a
-- bare URL isn't a citation on its own.
CREATE TABLE citations (
    id            SERIAL PRIMARY KEY,
    url           TEXT,
    description   TEXT NOT NULL,
    submitted_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- #74: how many independent sources were cross-referenced for this
    -- citation, backing the "N independent sources agree" badge. Authored
    -- explicitly per episode rather than derived from counting merged
    -- citation_ids — a combo can legitimately cite a source that was
    -- considered and then overridden, which isn't the same as agreement.
    source_count  INTEGER NOT NULL DEFAULT 1,
    -- #77: the full compiled research/methodology trail, split out of
    -- `description` — which stays short and reader-facing. Nullable; a
    -- citation with nothing more to say than its short description just
    -- omits this, no disclosure rendered.
    methodology_note TEXT
);

-- Every proposed episode status change, ever. This table IS the audit
-- trail — rows are never deleted or overwritten, only review_status/
-- resolution_method/reviewed_by/reviewed_at transition once. episodes
-- reflects only the current approved state; contributions reflects
-- everything anyone has ever proposed.
--
-- citation_id is NOT NULL — this is the structural guarantee, not an
-- app-layer check, that nothing becomes live/authoritative without a
-- source (see CLAUDE.md Guardrails).
--
-- submitted_by is nullable for two reasons: anonymous submission is an
-- explicit, decided feature (see CLAUDE.md — "Contribution model allows
-- anonymous submission"), and separately so deletion can anonymize rather
-- than cascade-delete (see header note).
--
-- targets series_id + episode_number rather than an episodes.id FK,
-- because the episode row may not exist yet (first-ever submission for
-- that episode number).
CREATE TABLE contributions (
    id                SERIAL PRIMARY KEY,
    series_id         INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    episode_number    INTEGER NOT NULL,
    proposed_status   TEXT NOT NULL CHECK (proposed_status IN ('canon', 'filler', 'mixed')),
    proposed_note     TEXT,
    citation_id       INTEGER NOT NULL REFERENCES citations(id),
    submitted_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    submitted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    review_status     TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    resolution_method TEXT CHECK (resolution_method IN ('moderator', 'community_vote')),   -- NULL until resolved
    reviewed_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at       TIMESTAMPTZ,
    review_note       TEXT,   -- moderator's reason, mainly for rejections
    -- CC BY-NC-SA structural proof of agreement (CLAUDE.md, issue #21) —
    -- every submission, not a one-time account-level flag: mirrors how
    -- citation_id NOT NULL above already enforces its own guardrail
    -- structurally rather than trusting app-layer discipline. Decided
    -- per-submission specifically because anonymous submission has no
    -- persistent identity to attach a one-time flag to anyway.
    license_accepted BOOLEAN NOT NULL
);

-- At most one pending contribution per episode (CLAUDE.md, issue #20) —
-- a new submission targeting an (series_id, episode_number) that already
-- has a pending contribution is rejected at the app layer and pointed at
-- the existing one instead of creating a competing row. Enforced
-- structurally here too, not just trusted to application code: a partial
-- unique index only applies to pending rows, so multiple *resolved*
-- (approved/rejected) contributions for the same episode over time — the
-- normal history — are unaffected.
CREATE UNIQUE INDEX contributions_one_pending_per_episode
    ON contributions (series_id, episode_number)
    WHERE review_status = 'pending';

-- Community trust-weighted votes on a *pending* contribution — the
-- alternative path to promotion alongside direct moderator approval (see
-- CLAUDE.md). voter_id and weight_at_vote are both nullable/preserved
-- carefully: weight_at_vote is a snapshot taken at vote time so a voter's
-- later trust-score changes never retroactively rewrite an already-
-- resolved contribution's history, and voter_id is nullable (ON DELETE SET
-- NULL) so an account deletion anonymizes the vote rather than deleting it
-- outright — deleting the row would itself rewrite resolved history, which
-- is exactly what weight_at_vote's snapshotting exists to prevent.
CREATE TABLE contribution_votes (
    id               SERIAL PRIMARY KEY,
    contribution_id  INTEGER NOT NULL REFERENCES contributions(id) ON DELETE CASCADE,
    voter_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    vote             TEXT NOT NULL CHECK (vote IN ('endorse', 'dispute')),
    weight_at_vote   INTEGER NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contribution_id, voter_id)
);

-- One row per POST /series/{id}/contributions/bulk call that actually wrote
-- something (dry_run calls never insert here — see issue #84). Backs a
-- per-account rolling-window rate limit on bulk-submission *frequency*,
-- separate from #80's own per-batch *size* cap. ON DELETE CASCADE
-- deliberately, unlike every users(id) FK above: this table has no
-- audit-trail purpose (see the file header's ON DELETE SET NULL rationale)
-- — it's transient rate-limiting bookkeeping only, so once an account is
-- gone its old events serve no purpose either.
CREATE TABLE bulk_submission_events (
    id            BIGSERIAL PRIMARY KEY,
    submitted_by  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX bulk_submission_events_by_user_and_time
    ON bulk_submission_events (submitted_by, submitted_at);

-- #139/#141: generic rate-limit bookkeeping for the anonymous-accessible
-- write endpoints that have no natural per-account row to count against
-- the way bulk_submission_events above does (an anonymous caller has no
-- user id). `identifier` is caller-supplied — a "user:<id>" string when
-- authenticated, an "ip:<address>" string otherwise; `scope` keeps each
-- endpoint's counters independent. No FK / no audit-trail purpose, same
-- transient-bookkeeping reasoning as bulk_submission_events.
CREATE TABLE rate_limit_events (
    id           BIGSERIAL PRIMARY KEY,
    scope        TEXT NOT NULL,
    identifier   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX rate_limit_events_by_scope_identifier_time
    ON rate_limit_events (scope, identifier, created_at);

-- =========================================================================
-- EPISODES (the live, authoritative community layer)
-- =========================================================================

-- One row per episode with an APPROVED status. No row here for an episode
-- nobody has researched yet — absence means "no data," not "canon by
-- default." Episode numbering is absolute (matches how filler guides
-- count, e.g. Naruto: Shippuden 1-500), not per-season. Only three status
-- values — a 'recap' value was considered and deliberately dropped (see
-- CLAUDE.md); structured (non-freeform) citation data for 'mixed' episodes
-- is deliberately deferred, tracked as issue #2.
CREATE TABLE episodes (
    id                        SERIAL PRIMARY KEY,
    series_id                 INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    episode_number             INTEGER NOT NULL,
    status                     TEXT NOT NULL CHECK (status IN ('canon', 'filler', 'mixed')),
    status_note                TEXT,   -- freeform for v1 regardless of issue #2's outcome
    -- #73: reopens #33's original "skip for v1" decision. Nullable — most
    -- episodes, including on researched shows, won't have one for a long
    -- time (AniList's own per-episode title data is itself partial, see
    -- data/bootstrap/backfill_episode_titles_from_anilist.py).
    title                      TEXT,
    citation_id                INTEGER NOT NULL REFERENCES citations(id),
    approved_contribution_id   INTEGER NOT NULL REFERENCES contributions(id),   -- the specific contribution that made this row live — full history lives in contributions, not duplicated here
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (series_id, episode_number)
);

-- =========================================================================
-- ASYNC SIDE-EFFECTS (transactional outbox — see CLAUDE.md Architecture)
-- =========================================================================

-- Written to in the same DB transaction as any state change other systems
-- care about (contribution submitted/approved/rejected, series proposal
-- submitted/approved). A separate worker process polls this table
-- (SELECT ... FOR UPDATE SKIP LOCKED) and dispatches side effects
-- (moderator Telegram notification, Cloudflare cache purge on approval).
-- Postgres is the broker — no Redis/Celery. Route handlers only ever write
-- rows here; they never call Telegram/Cloudflare directly.
CREATE TABLE outbox_events (
    id           BIGSERIAL PRIMARY KEY,
    event_type   TEXT NOT NULL,   -- 'contribution.submitted' | 'contribution.approved' | 'contribution.rejected' | 'series_proposal.submitted' | 'series_proposal.approved' | ...
    payload      JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ   -- NULL until a consumer has handled it
);

-- =========================================================================
-- EXPORT ACCESS (issue #22 — terms-acceptance + API key gate for /export)
-- =========================================================================

-- One row per acceptance record. No full contributor account required —
-- deliberately lighter-weight than #8's OAuth-based auth. Key is stored
-- hashed (sha256), never plaintext, same discipline as a password; the
-- plaintext value is shown to the requester exactly once, at issuance.
-- terms_version lets a future license-terms change be distinguished from
-- what an older key-holder actually agreed to.
CREATE TABLE export_api_keys (
    id                SERIAL PRIMARY KEY,
    key_hash          TEXT NOT NULL UNIQUE,
    email             TEXT NOT NULL,
    license_accepted  BOOLEAN NOT NULL,
    terms_version     TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at        TIMESTAMPTZ
);

-- =========================================================================
-- EPISODE SCHEDULE SYNC (issue #49 — repeatable AniList episode/air-date sync)
-- =========================================================================

-- One row per (series, episode) that AniList's own airing schedule reports
-- as existing, with its real-world air date. Deliberately separate from
-- `episodes` above: this table only ever answers "does episode N exist and
-- when did it air," entirely independent of any filler/canon research —
-- `episodes` still only gets a row once a contribution is approved. Lets a
-- contributor (or future UI) see a series' real episode count/schedule
-- even for a show nobody has researched a single episode of yet.
CREATE TABLE series_episode_schedule (
    series_id       INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    episode_number  INTEGER NOT NULL,
    aired_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (series_id, episode_number)
);
