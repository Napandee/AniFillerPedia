-- Combined migration for issues #184, #194, #195, #204 — bundled into one
-- migration file specifically to avoid a migration-number collision with
-- parallel work elsewhere (this repo has hit that exact collision before,
-- see CLAUDE.local.md's "Process lessons: parallel-agent batches" entry).
-- Every change below is purely additive (new CHECK constraint, new
-- columns, new indexes) — fine to apply without asking first per
-- CLAUDE.md's own migration guardrail, and applied to production BEFORE
-- the app-code PR merges (migrate-then-merge — this repo has had real
-- outages from getting that order backwards).
--
-- #204 (community submission source_count field) needs no schema change
-- at all — citations.source_count already exists (migration 007); #204
-- is a pure API-layer change letting real submissions populate it.
--
-- #205 (shared source_count consistency check) is also a pure code
-- change (repositories/citations.py, repositories/citation_consistency.py)
-- — no new column, no new constraint. A DB-level trigger enforcing the
-- same rule was considered (per #205's own scope note) and not built:
-- the combo-match this check depends on (same series + description + url
-- + methodology_note) isn't something a simple CHECK/trigger can express
-- cleanly without a fair amount of added complexity for a rule the shared
-- repository-level function (now used by every write path) already
-- enforces consistently — documented as an accepted v1 limitation, same
-- spirit as this project's other "no real demand yet to justify the extra
-- machinery" calls, revisit if the app-layer guarantee ever proves
-- insufficient in practice.

-- ---------------------------------------------------------------------
-- #184 — stored XSS via unvalidated citation URL scheme
-- ---------------------------------------------------------------------
-- Defense-in-depth alongside the Pydantic-layer scheme allowlist + cap
-- added to CitationIn (backend/schemas/contributions.py) — a DB-level
-- CHECK constraint means even a future write path that bypasses the
-- Pydantic layer entirely (a raw SQL script, a bug in some other
-- validator) still can't persist a non-http(s)-scheme URL. Case-
-- insensitive (~*) since a URL scheme is conventionally lowercase but not
-- enforced as such by any spec; NULL stays allowed — citations.url is
-- nullable by design (a source can be a book/guide with no URL, per
-- schema.sql's own header comment on the citations table).
--
-- #184's own acceptance criteria requires auditing existing data for any
-- already-stored non-http(s) URL before this constraint could safely be
-- applied — run as a read-only check against production immediately
-- before this migration:
--   SELECT id, url FROM citations WHERE url IS NOT NULL AND url !~* '^https?://';
-- Zero matching rows confirmed live before this ALTER TABLE ran (every
-- citation loaded so far — bootstrap imports included — was already a
-- real http(s) link or NULL); if a future re-run of this migration file
-- against a different environment ever finds rows, fix those rows first
-- rather than relaxing this constraint.
ALTER TABLE citations ADD CONSTRAINT citations_url_scheme_check
    CHECK (url IS NULL OR url ~* '^https?://');

-- ---------------------------------------------------------------------
-- #194 — missing indexes for real, frequently-run query patterns
-- ---------------------------------------------------------------------
-- (series_id, episode_number) on contributions: backs
-- repositories/contributions.py::list_for_episode (the public per-episode
-- contribution-history view, called on every episode-detail page load).
-- The existing contributions_one_pending_per_episode index only covers
-- review_status = 'pending' rows by design (#20), so once a query needs
-- resolved history too, this is what serves it.
CREATE INDEX contributions_by_series_and_episode
    ON contributions (series_id, episode_number);

-- (submitted_by) on contributions: backs list_mine() (a user's own
-- submission history, GET /contributions/mine).
CREATE INDEX contributions_by_submitted_by
    ON contributions (submitted_by);

-- (voter_id) on contribution_votes: backs list_votes_by_voter() (#30,
-- GET /contributions/mine/votes). The table's only existing index is
-- UNIQUE (contribution_id, voter_id), leading column contribution_id,
-- which doesn't serve a voter_id-only lookup.
CREATE INDEX contribution_votes_by_voter
    ON contribution_votes (voter_id);

-- (id) WHERE processed_at IS NULL on outbox_events: backs
-- repositories/outbox.py::fetch_unprocessed_batch, run every worker poll
-- cycle. Processed rows are never archived, so without this the query
-- degrades toward O(all rows ever written), not O(unprocessed rows).
CREATE INDEX outbox_events_unprocessed
    ON outbox_events (id) WHERE processed_at IS NULL;

-- ---------------------------------------------------------------------
-- #195 — outbox dead-letter / retry-limit handling
-- ---------------------------------------------------------------------
-- retry_count: bumped by repositories/outbox.py::increment_retry_count
-- each time a handler raises for a given event (see worker.py's
-- process_batch). failed_at: set by mark_dead_lettered once retry_count
-- crosses worker.py's MAX_RETRY_ATTEMPTS — fetch_unprocessed_batch
-- excludes failed_at IS NOT NULL rows from then on, so a permanently-
-- failing event stops being re-fetched (and therefore stops occupying a
-- slot in every poll's LIMIT) without ever being deleted — it stays in
-- the table, queryable via `WHERE failed_at IS NOT NULL`, satisfying
-- #195's "visible/discoverable, not silently dropped" acceptance
-- criterion.
ALTER TABLE outbox_events ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE outbox_events ADD COLUMN failed_at TIMESTAMPTZ;
