"""Raw SQL for the public contribution history. contributions targets
series_id + episode_number, not episodes.id (schema.sql's own comment:
the episode row may not exist yet at submission time) — so history for a
given episodes.id is looked up via that episode's (series_id,
episode_number) pair, not a direct FK join.

Public per CLAUDE.md ("keep public history non-anonymized") — submitter/
reviewer/voter identity is always included when present; NULL naturally
covers both anonymous submissions and anonymized-by-deletion accounts,
which look identical on purpose (deletion anonymizes rather than deletes
the row, precisely so it can't be told apart from a genuinely anonymous
submission after the fact).
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def find_pending_for_episode(
    session: AsyncSession, series_id: int, episode_number: int
) -> Row | None:
    """Existence check backing the #20 rule (at most one pending
    contribution per episode) — the *readable* half of the guarantee, an
    app-layer check so a duplicate submission gets a clean 409 pointing at
    the existing row. The partial unique index in schema.sql is the real,
    concurrency-safe backstop; this is what makes the common case a nice
    error message instead of a raw constraint violation.
    """
    result = await session.execute(
        text(
            """
            SELECT id FROM contributions
            WHERE series_id = :series_id
              AND episode_number = :episode_number
              AND review_status = 'pending'
            """
        ),
        {"series_id": series_id, "episode_number": episode_number},
    )
    return result.first()


async def create(
    session: AsyncSession,
    *,
    series_id: int,
    episode_number: int,
    proposed_status: str,
    proposed_note: str | None,
    citation_id: int,
    submitted_by: int | None,
    license_accepted: bool,
) -> Row:
    result = await session.execute(
        text(
            """
            INSERT INTO contributions
                (series_id, episode_number, proposed_status, proposed_note,
                 citation_id, submitted_by, license_accepted)
            VALUES
                (:series_id, :episode_number, :proposed_status, :proposed_note,
                 :citation_id, :submitted_by, :license_accepted)
            RETURNING *
            """
        ),
        {
            "series_id": series_id,
            "episode_number": episode_number,
            "proposed_status": proposed_status,
            "proposed_note": proposed_note,
            "citation_id": citation_id,
            "submitted_by": submitted_by,
            "license_accepted": license_accepted,
        },
    )
    return result.one()


async def list_mine(session: AsyncSession, user_id: int) -> list[Row]:
    result = await session.execute(
        text(
            """
            SELECT co.*, c.url AS citation_url, c.description AS citation_description
            FROM contributions co
            JOIN citations c ON c.id = co.citation_id
            WHERE co.submitted_by = :user_id
            ORDER BY co.submitted_at DESC
            """
        ),
        {"user_id": user_id},
    )
    return list(result.fetchall())


async def get_episode_series_and_number(
    session: AsyncSession, episode_id: int
) -> Row | None:
    result = await session.execute(
        text("SELECT series_id, episode_number FROM episodes WHERE id = :id"),
        {"id": episode_id},
    )
    return result.first()


async def list_for_episode(
    session: AsyncSession, series_id: int, episode_number: int
) -> list[Row]:
    result = await session.execute(
        text(
            """
            SELECT
                co.id, co.proposed_status, co.proposed_note,
                co.submitted_at, co.review_status, co.resolution_method,
                co.reviewed_at, co.review_note,
                c.id AS citation_id, c.url AS citation_url, c.description AS citation_description,
                submitter.id AS submitter_id, submitter.display_name AS submitter_display_name,
                submitter.github_id AS submitter_github_id,
                reviewer.id AS reviewer_id, reviewer.display_name AS reviewer_display_name,
                reviewer.github_id AS reviewer_github_id
            FROM contributions co
            JOIN citations c ON c.id = co.citation_id
            LEFT JOIN users submitter ON submitter.id = co.submitted_by
            LEFT JOIN users reviewer ON reviewer.id = co.reviewed_by
            WHERE co.series_id = :series_id AND co.episode_number = :episode_number
            ORDER BY co.submitted_at
            """
        ),
        {"series_id": series_id, "episode_number": episode_number},
    )
    return list(result.fetchall())


async def list_votes_for_contributions(
    session: AsyncSession, contribution_ids: list[int]
) -> list[Row]:
    if not contribution_ids:
        return []
    result = await session.execute(
        text(
            """
            SELECT
                v.contribution_id, v.vote, v.weight_at_vote, v.created_at,
                voter.id AS voter_id, voter.display_name AS voter_display_name,
                voter.github_id AS voter_github_id
            FROM contribution_votes v
            LEFT JOIN users voter ON voter.id = v.voter_id
            WHERE v.contribution_id = ANY(:ids)
            ORDER BY v.created_at
            """
        ),
        {"ids": contribution_ids},
    )
    return list(result.fetchall())
