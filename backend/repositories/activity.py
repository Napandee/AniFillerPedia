"""Raw SQL for #154's public activity feed — a read-only view over the
audit trail `contributions` and `series_proposals` already write on every
approve/reject/withdraw (`review_status`/`reviewed_at`/`reviewed_by` on
both tables). No new writes, no new table: this module only ever SELECTs.

The two source tables have different shapes (an episode-level contribution
vs. a series-level proposal), so a single UNION ALL projects both onto one
common column set rather than fetching each separately and merging in
Python — this keeps ORDER BY/LIMIT/OFFSET correct across the combined feed
in one round trip instead of over-fetching from each side and re-paginating
by hand.

Public per the same "keep public history non-anonymized" convention
repositories/contributions.py already documents — submitter/reviewer
identity is always included when present; NULL naturally covers both
anonymous submissions and accounts anonymized by deletion.
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_FEED_QUERY = """
    WITH feed AS (
        SELECT
            'contribution' AS event_type,
            co.id,
            co.review_status,
            co.resolution_method,
            co.reviewed_at,
            co.submitted_at,
            co.review_note,
            s.id AS series_id,
            s.title AS series_title,
            s.slug AS series_slug,
            co.episode_number,
            co.proposed_status,
            NULL::text AS proposal_title,
            c.description AS citation_description,
            submitter.id AS submitter_id,
            submitter.display_name AS submitter_display_name,
            submitter.github_id AS submitter_github_id,
            reviewer.id AS reviewer_id,
            reviewer.display_name AS reviewer_display_name,
            reviewer.github_id AS reviewer_github_id
        FROM contributions co
        JOIN series s ON s.id = co.series_id
        JOIN citations c ON c.id = co.citation_id
        LEFT JOIN users submitter ON submitter.id = co.submitted_by
        LEFT JOIN users reviewer ON reviewer.id = co.reviewed_by
        WHERE co.review_status IN ('approved', 'rejected', 'withdrawn')

        UNION ALL

        SELECT
            'series_proposal' AS event_type,
            sp.id,
            sp.review_status,
            NULL::text AS resolution_method,
            sp.reviewed_at,
            sp.submitted_at,
            sp.review_note,
            NULL::integer AS series_id,
            NULL::text AS series_title,
            NULL::text AS series_slug,
            NULL::integer AS episode_number,
            NULL::text AS proposed_status,
            sp.title AS proposal_title,
            NULL::text AS citation_description,
            submitter.id AS submitter_id,
            submitter.display_name AS submitter_display_name,
            submitter.github_id AS submitter_github_id,
            reviewer.id AS reviewer_id,
            reviewer.display_name AS reviewer_display_name,
            reviewer.github_id AS reviewer_github_id
        FROM series_proposals sp
        LEFT JOIN users submitter ON submitter.id = sp.submitted_by
        LEFT JOIN users reviewer ON reviewer.id = sp.reviewed_by
        WHERE sp.review_status IN ('approved', 'rejected')
    )
"""


async def list_recent_activity(session: AsyncSession, limit: int, offset: int) -> tuple[list[Row], int]:
    total = (
        await session.execute(text(f"{_FEED_QUERY} SELECT count(*) FROM feed"))
    ).scalar_one()

    rows = (
        await session.execute(
            text(
                f"""
                {_FEED_QUERY}
                SELECT * FROM feed
                ORDER BY reviewed_at DESC, id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        )
    ).fetchall()

    return list(rows), total
