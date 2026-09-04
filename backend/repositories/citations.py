"""Raw SQL for citations. Reads happen mostly via JOINs from contributions/
episodes repositories — find_matching_for_series below is the one
standalone read, added for #205's consistency check.
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.citation_consistency import source_count_conflicts


class SourceCountConflict(Exception):
    """#205: raised by get_or_create() below when a citation matching the
    proposed (series, description, url, methodology_note) combo already
    exists on record with a DIFFERENT source_count than what's now being
    submitted for it — the same bug class documented repeatedly in
    CLAUDE.local.md, now caught structurally for every write path rather
    than only inside the bootstrap loader script.
    """

    def __init__(self, *, existing_source_count: int, proposed_source_count: int):
        self.existing_source_count = existing_source_count
        self.proposed_source_count = proposed_source_count
        super().__init__(
            f"citation source_count conflict: an existing citation for this same "
            f"source combination already has source_count={existing_source_count}, "
            f"but {proposed_source_count} was proposed"
        )


async def create(
    session: AsyncSession,
    *,
    url: str | None,
    description: str,
    submitted_by: int | None,
    methodology_note: str | None = None,
    source_count: int = 1,
) -> Row:
    result = await session.execute(
        text(
            """
            INSERT INTO citations (url, description, submitted_by, methodology_note, source_count)
            VALUES (:url, :description, :submitted_by, :methodology_note, :source_count)
            RETURNING *
            """
        ),
        {
            "url": url,
            "description": description,
            "submitted_by": submitted_by,
            "methodology_note": methodology_note,
            "source_count": source_count,
        },
    )
    return result.one()


async def find_matching_for_series(
    session: AsyncSession,
    *,
    series_id: int,
    description: str,
    url: str | None,
    methodology_note: str | None,
) -> Row | None:
    """#205: does a citation already exist for THIS series with the exact
    same (description, url, methodology_note) combo? Mirrors data/bootstrap/
    load_episodes.py::get_or_create_citation's own matching query — a
    citation isn't directly linked to a series (only via the contributions
    that cite it), so this joins through contributions the same way the
    script does. IS NOT DISTINCT FROM for a NULL-safe match on url/
    methodology_note (both legitimately NULL for many citations).
    """
    result = await session.execute(
        text(
            """
            SELECT DISTINCT c.*
            FROM citations c
            JOIN contributions co ON co.citation_id = c.id
            WHERE co.series_id = :series_id
              AND c.description = :description
              AND c.url IS NOT DISTINCT FROM :url
              AND c.methodology_note IS NOT DISTINCT FROM :methodology_note
            LIMIT 1
            """
        ),
        {
            "series_id": series_id,
            "description": description,
            "url": url,
            "methodology_note": methodology_note,
        },
    )
    return result.first()


async def get_or_create(
    session: AsyncSession,
    *,
    series_id: int,
    url: str | None,
    description: str,
    submitted_by: int | None,
    methodology_note: str | None = None,
    source_count: int = 1,
) -> Row:
    """#205: the shared, repository-level version of load_episodes.py's own
    get_or_create_citation — every live write path that creates a citation
    (single-episode submission, bulk submission, series-proposal-attached
    episode data — see services/contributions.py) calls this instead of
    reimplementing the combo-match/conflict-check logic. If a citation
    matching this exact combo already exists for this series, it's reused
    (never duplicated) as long as its source_count agrees; a genuine
    disagreement raises SourceCountConflict rather than silently writing a
    second, inconsistent citation row for what's supposed to be the same
    source combination.
    """
    existing = await find_matching_for_series(
        session,
        series_id=series_id,
        description=description,
        url=url,
        methodology_note=methodology_note,
    )
    if existing is not None:
        if source_count_conflicts(existing.source_count, source_count):
            raise SourceCountConflict(
                existing_source_count=existing.source_count,
                proposed_source_count=source_count,
            )
        return existing

    return await create(
        session,
        url=url,
        description=description,
        submitted_by=submitted_by,
        methodology_note=methodology_note,
        source_count=source_count,
    )
