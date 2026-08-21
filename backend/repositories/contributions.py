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


async def list_pending(session: AsyncSession) -> list[Row]:
    result = await session.execute(
        text(
            """
            SELECT co.*, c.url AS citation_url, c.description AS citation_description
            FROM contributions co
            JOIN citations c ON c.id = co.citation_id
            WHERE co.review_status = 'pending'
            ORDER BY co.submitted_at
            """
        )
    )
    return list(result.fetchall())


async def get_by_id(session: AsyncSession, contribution_id: int) -> Row | None:
    result = await session.execute(
        text("SELECT * FROM contributions WHERE id = :id"),
        {"id": contribution_id},
    )
    return result.first()


async def approve(session: AsyncSession, contribution_id: int, reviewed_by: int) -> Row | None:
    """#13: guarded UPDATE, not a separate lock-then-check — `WHERE
    review_status = 'pending'` is what makes the double-approval race safe.
    Postgres takes an implicit row lock on UPDATE; a second concurrent
    approve() on the same row blocks until the first commits, then
    re-evaluates this WHERE clause against the now-changed row and matches
    zero rows — RETURNING * then yields nothing, which the caller must
    treat as "already resolved," never as a second success.
    """
    result = await session.execute(
        text(
            """
            UPDATE contributions
            SET review_status = 'approved',
                resolution_method = 'moderator',
                reviewed_by = :reviewed_by,
                reviewed_at = now()
            WHERE id = :id AND review_status = 'pending'
            RETURNING *
            """
        ),
        {"id": contribution_id, "reviewed_by": reviewed_by},
    )
    return result.first()


async def reject(
    session: AsyncSession, contribution_id: int, reviewed_by: int, review_note: str
) -> Row | None:
    """Same guarded-UPDATE race protection as approve() above."""
    result = await session.execute(
        text(
            """
            UPDATE contributions
            SET review_status = 'rejected',
                resolution_method = 'moderator',
                reviewed_by = :reviewed_by,
                reviewed_at = now(),
                review_note = :review_note
            WHERE id = :id AND review_status = 'pending'
            RETURNING *
            """
        ),
        {"id": contribution_id, "reviewed_by": reviewed_by, "review_note": review_note},
    )
    return result.first()


async def insert_vote(
    session: AsyncSession, *, contribution_id: int, voter_id: int, vote: str, weight_at_vote: int
) -> Row:
    """The UNIQUE (contribution_id, voter_id) constraint in schema.sql is
    the real one-vote-per-user guarantee — this raises IntegrityError on a
    repeat vote, which the service layer converts to a clean 409 rather
    than a raw constraint error reaching the caller.
    """
    result = await session.execute(
        text(
            """
            INSERT INTO contribution_votes (contribution_id, voter_id, vote, weight_at_vote)
            VALUES (:contribution_id, :voter_id, :vote, :weight_at_vote)
            RETURNING *
            """
        ),
        {
            "contribution_id": contribution_id,
            "voter_id": voter_id,
            "vote": vote,
            "weight_at_vote": weight_at_vote,
        },
    )
    return result.one()


async def get_net_endorsement_score(session: AsyncSession, contribution_id: int) -> int:
    """Cumulative weighted endorsement minus weighted dispute (CLAUDE.md:
    "one sufficiently-trusted user's single vote can cross the threshold
    alone, or several lower-trust users' votes can combine to") — dispute
    votes count against the total rather than being ignored, so a
    contested-but-not-yet-rejected contribution can't be pushed through by
    endorsements alone while credible disputes pile up unweighed.
    """
    result = await session.execute(
        text(
            """
            SELECT COALESCE(
                SUM(CASE WHEN vote = 'endorse' THEN weight_at_vote ELSE -weight_at_vote END),
                0
            ) AS net_score
            FROM contribution_votes
            WHERE contribution_id = :contribution_id
            """
        ),
        {"contribution_id": contribution_id},
    )
    return result.scalar_one()


async def promote_via_vote(session: AsyncSession, contribution_id: int) -> Row | None:
    """Auto-promotion counterpart to approve() above — same guarded
    `WHERE review_status = 'pending'` race protection (concurrent votes
    that both compute a stale net_score crossing the threshold will only
    ever have one UPDATE actually match a row; the loser's vote is still
    recorded, it just doesn't trigger a second promotion). reviewed_by
    stays NULL — a community-vote promotion has no single reviewing
    moderator, only the votes themselves, which contribution_votes already
    records in full.
    """
    result = await session.execute(
        text(
            """
            UPDATE contributions
            SET review_status = 'approved',
                resolution_method = 'community_vote',
                reviewed_by = NULL,
                reviewed_at = now()
            WHERE id = :id AND review_status = 'pending'
            RETURNING *
            """
        ),
        {"id": contribution_id},
    )
    return result.first()


async def list_votes_by_voter(session: AsyncSession, voter_id: int) -> list[Row]:
    """#30: the votes-cast counterpart to list_mine() (a user's own
    submissions) — enough of the contribution's own shape (series title,
    episode, current status) joined in that a UI can render each row
    without a follow-up request per vote.
    """
    result = await session.execute(
        text(
            """
            SELECT
                v.vote, v.weight_at_vote, v.created_at,
                c.id AS contribution_id, c.series_id, c.episode_number,
                c.proposed_status, c.review_status, c.resolution_method,
                s.title AS series_title
            FROM contribution_votes v
            JOIN contributions c ON c.id = v.contribution_id
            JOIN series s ON s.id = c.series_id
            WHERE v.voter_id = :voter_id
            ORDER BY v.created_at DESC
            """
        ),
        {"voter_id": voter_id},
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
