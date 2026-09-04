"""#205: the ONE place that decides whether a proposed citation
source_count conflicts with an already-recorded one for the "same"
citation combo (matched, elsewhere, by series + description + url +
methodology_note — see repositories/citations.py::find_matching_for_series
and data/bootstrap/load_episodes.py::get_or_create_citation).

Deliberately zero external imports (stdlib only): both this backend's own
async SQLAlchemy repository layer (repositories/citations.py) AND
data/bootstrap/load_episodes.py — a standalone, sync psycopg2 script that
lives outside backend/'s async import graph on purpose (see that script's
own module docstring) — import this exact predicate, so the RULE itself
can never drift between the two write paths even though the DB-access code
around it necessarily differs (async SQLAlchemy session vs. a sync
psycopg2 cursor). This is the extracted core of the consistency check
load_episodes.py::get_or_create_citation already had, generalized so any
future write path (including #204's live community-submission path) can
reuse it instead of re-copying the comparison — see CLAUDE.local.md for
the 2-3 real recurrences of this exact bug class (Rurouni Kenshin/Yu Yu
Hakusho, Noragami, a live-data correction) this check exists to prevent.

Operational note for whoever next runs a production data load: for
load_episodes.py's import of this module to resolve inside the throwaway
loader container (see CLAUDE.local.md's documented load process), that
container needs the repo root bind-mounted (or at least backend/repositories/
citation_consistency.py specifically), not just data/bootstrap/ as it has
been mounted historically — this file has no dependency beyond the stdlib,
so nothing else about that container's setup needs to change.
"""


def source_count_conflicts(existing_source_count: int | None, proposed_source_count: int) -> bool:
    """True if a citation matching this same combo already exists on
    record with a DIFFERENT source_count than what's now being proposed
    for it — the exact drift that has already recurred multiple times
    across hand-compiled data batches (see CLAUDE.local.md). False when
    there's nothing to conflict with (existing_source_count is None, i.e.
    no matching citation exists yet) or the existing value already agrees.
    """
    return existing_source_count is not None and existing_source_count != proposed_source_count
