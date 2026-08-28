"""Raw SQL for series_synonym_suggestions (#148) — a contributor's
suggestion to add a synonym to an already-catalogued series. Mirrors
repositories/series_proposals.py's shape closely (create/list_mine/
list_pending/get_by_id/approve/reject), since this is the same
"submission -> moderator review -> resolved" lifecycle just for a
different target. No community-vote path here (see the module's schema
migration for why) — only a moderator ever resolves one of these rows.
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def create(
    session: AsyncSession,
    *,
    series_id: int,
    synonym: str,
    note: str | None,
    submitted_by: int | None,
    license_accepted: bool,
) -> Row:
    result = await session.execute(
        text(
            """
            INSERT INTO series_synonym_suggestions
                (series_id, synonym, note, submitted_by, license_accepted)
            VALUES
                (:series_id, :synonym, :note, :submitted_by, :license_accepted)
            RETURNING *
            """
        ),
        {
            "series_id": series_id,
            "synonym": synonym,
            "note": note,
            "submitted_by": submitted_by,
            "license_accepted": license_accepted,
        },
    )
    return result.one()


async def find_pending_for_target(session: AsyncSession, series_id: int, synonym: str) -> Row | None:
    """#20-style duplicate check, applied here to synonym suggestions —
    checked before INSERT (a race window remains between this SELECT and
    the INSERT below, closed the same way submit_contribution's own
    equivalent check is: a SAVEPOINT around the insert + catching the
    partial unique index's IntegrityError, see services/
    synonym_suggestions.py)."""
    result = await session.execute(
        text(
            """
            SELECT * FROM series_synonym_suggestions
            WHERE series_id = :series_id AND synonym = :synonym AND review_status = 'pending'
            """
        ),
        {"series_id": series_id, "synonym": synonym},
    )
    return result.first()


async def list_mine(session: AsyncSession, user_id: int) -> list[Row]:
    result = await session.execute(
        text(
            """
            SELECT * FROM series_synonym_suggestions
            WHERE submitted_by = :user_id
            ORDER BY submitted_at DESC
            """
        ),
        {"user_id": user_id},
    )
    return list(result.fetchall())


async def list_pending(session: AsyncSession) -> list[Row]:
    """Joins series.title in, unlike ContributionOut's own bare series_id
    — a synonym suggestion is meaningless to a moderator without knowing
    which series it targets, and unlike an episode contribution there's
    no other identifying detail (episode number, proposed status) on the
    row to anchor the card to.
    """
    result = await session.execute(
        text(
            """
            SELECT ss.*, s.title AS series_title, s.slug AS series_slug
            FROM series_synonym_suggestions ss
            JOIN series s ON s.id = ss.series_id
            WHERE ss.review_status = 'pending'
            ORDER BY ss.submitted_at
            """
        )
    )
    return list(result.fetchall())


async def get_by_id(session: AsyncSession, suggestion_id: int) -> Row | None:
    result = await session.execute(
        text("SELECT * FROM series_synonym_suggestions WHERE id = :id"),
        {"id": suggestion_id},
    )
    return result.first()


async def approve(session: AsyncSession, suggestion_id: int, reviewed_by: int) -> Row | None:
    """Guarded UPDATE ... WHERE review_status = 'pending' — same race
    protection as contributions.approve()/series_proposals.approve(): two
    concurrent approve calls on the same suggestion can never both
    succeed, the loser gets None back and the caller turns that into a
    409."""
    result = await session.execute(
        text(
            """
            UPDATE series_synonym_suggestions
            SET review_status = 'approved', reviewed_by = :reviewed_by, reviewed_at = now()
            WHERE id = :id AND review_status = 'pending'
            RETURNING *
            """
        ),
        {"id": suggestion_id, "reviewed_by": reviewed_by},
    )
    return result.first()


async def reject(
    session: AsyncSession, suggestion_id: int, reviewed_by: int, review_note: str
) -> Row | None:
    result = await session.execute(
        text(
            """
            UPDATE series_synonym_suggestions
            SET review_status = 'rejected', reviewed_by = :reviewed_by,
                reviewed_at = now(), review_note = :review_note
            WHERE id = :id AND review_status = 'pending'
            RETURNING *
            """
        ),
        {"id": suggestion_id, "reviewed_by": reviewed_by, "review_note": review_note},
    )
    return result.first()
