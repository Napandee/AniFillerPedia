-- Issue #148 — additive only (new table), fine per CLAUDE.md Guardrails
-- without needing to ask first. Run by hand against the live Postgres,
-- same as every migration in this project (see migrations/README.md).
--
-- MUST be applied to production BEFORE the dependent app-code merge lands
-- (CLAUDE.local.md's migrate-then-merge lesson, hit three times already
-- with the opposite ordering) — the new routers/services below
-- unconditionally query this table.
--
-- A contributor's suggestion to add an alternate/dub/regional title to an
-- ALREADY-catalogued series — series_synonyms itself (schema.sql) has no
-- write path beyond the one-time bootstrap import, so there was no way to
-- grow it post-launch. Deliberately a small, dedicated table rather than
-- extending series_proposals (which is scoped to "propose a NEW series" —
-- adding a target_series_id branch there would mean new conditional logic
-- in the already-more-complex approve_series_proposal, which already
-- juggles #85's attached episode data and #150's duplicate detection) or
-- reusing contributions (episode-status-shaped, no natural fit for a
-- series-level string). See services/synonym_suggestions.py's module
-- docstring for the full scope-decision writeup.
--
-- Moderator-only approval, NOT #14's trust-weighted voting — a synonym
-- suggestion is a single low-blast-radius string (doesn't touch episode
-- status/citations), and the full contribution_votes/weight-snapshot/
-- auto-promotion machinery is disproportionate for something this small.
-- A moderator reviewing the queue can make this call in seconds; voting
-- exists for episode-status disputes with real evidentiary weight to
-- adjudicate, which this isn't.
--
-- license_accepted mirrors contributions.license_accepted /
-- series_proposals.license_accepted (CLAUDE.md, issue #21) — structural
-- proof of agreement on every submission, not a one-time account flag,
-- kept uniform across every write path in this project rather than
-- special-cased away for "just a title string."
--
-- Same one-pending-per-target partial unique index pattern as #20's
-- contributions_one_pending_per_episode — a second suggestion for the
-- same (series_id, synonym) while one is already pending is rejected at
-- the app layer (409) and pointed at the existing pending suggestion,
-- rather than allowed to coexist and split moderator attention.

CREATE TABLE series_synonym_suggestions (
    id            SERIAL PRIMARY KEY,
    series_id     INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    synonym       TEXT NOT NULL,
    -- Optional context for the moderator (e.g. "official English dub
    -- title on Crunchyroll") — NOT a citation.description-shaped required
    -- field; an alternate title is lower-stakes than a filler/canon claim,
    -- so this stays optional rather than forcing a full CitationIn object.
    note          TEXT,
    submitted_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reviewed_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at   TIMESTAMPTZ,
    review_note   TEXT,
    license_accepted BOOLEAN NOT NULL
);

CREATE UNIQUE INDEX series_synonym_suggestions_one_pending_per_target
    ON series_synonym_suggestions (series_id, synonym)
    WHERE review_status = 'pending';
