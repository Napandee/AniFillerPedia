"""Raw SQL data access for the admin tier — user listing with computed
stats, role updates. Kept separate from repositories/users.py (auth-layer
lookups by id/provider id) since this is a different access pattern:
admin-only, aggregate, paginated.
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

VALID_ROLES = ("contributor", "moderator", "admin")


async def list_users_with_stats(session: AsyncSession, limit: int, offset: int) -> tuple[list[Row], int]:
    total = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    u.id, u.role, u.github_id, u.discord_id, u.google_id,
                    u.display_name, u.created_at,
                    count(*) FILTER (WHERE c.review_status = 'approved') AS approved_count,
                    count(*) FILTER (WHERE c.review_status = 'rejected') AS rejected_count
                FROM users u
                LEFT JOIN contributions c ON c.submitted_by = u.id
                GROUP BY u.id
                ORDER BY u.id
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        )
    ).fetchall()
    return list(rows), total


async def get_user_stats(session: AsyncSession, user_id: int) -> Row | None:
    """Single-user version of list_users_with_stats's aggregate — #14 needs
    just one voter's approved/rejected counts at vote-cast time, not a full
    paginated listing. Returns None only if user_id doesn't exist (LEFT JOIN
    means a user with zero contributions still returns a row with counts of
    0, which is the common case for a brand-new voter).
    """
    result = await session.execute(
        text(
            """
            SELECT
                u.id,
                count(*) FILTER (WHERE c.review_status = 'approved') AS approved_count,
                count(*) FILTER (WHERE c.review_status = 'rejected') AS rejected_count
            FROM users u
            LEFT JOIN contributions c ON c.submitted_by = u.id
            WHERE u.id = :user_id
            GROUP BY u.id
            """
        ),
        {"user_id": user_id},
    )
    return result.first()


async def update_user_role(session: AsyncSession, user_id: int, new_role: str) -> Row | None:
    result = await session.execute(
        text("UPDATE users SET role = :role WHERE id = :id RETURNING id, role"),
        {"role": new_role, "id": user_id},
    )
    return result.fetchone()


async def get_user_role(session: AsyncSession, user_id: int) -> str | None:
    result = await session.execute(text("SELECT role FROM users WHERE id = :id"), {"id": user_id})
    row = result.fetchone()
    return row.role if row else None


async def set_user_suspension(
    session: AsyncSession, user_id: int, *, suspended: bool, reason: str | None
) -> Row | None:
    """#209: sets or clears suspended_at/suspended_reason. suspended_at is
    the single source of truth (NULL = active) — `suspended` here is just
    the caller's intent, not stored as its own column. Clearing a
    suspension always clears suspended_reason too, regardless of what
    `reason` was passed, since a reason with no suspended_at would be a
    stale, misleading note.
    """
    if suspended:
        result = await session.execute(
            text(
                """
                UPDATE users
                SET suspended_at = now(), suspended_reason = :reason
                WHERE id = :id
                RETURNING id, suspended_at, suspended_reason
                """
            ),
            {"id": user_id, "reason": reason},
        )
    else:
        result = await session.execute(
            text(
                """
                UPDATE users
                SET suspended_at = NULL, suspended_reason = NULL
                WHERE id = :id
                RETURNING id, suspended_at, suspended_reason
                """
            ),
            {"id": user_id},
        )
    return result.fetchone()


async def find_reciprocal_endorsement_pairs(
    session: AsyncSession, min_reciprocal_count: int, limit: int
) -> list[Row]:
    """#203: the Sybil-monitoring tripwire named in CLAUDE.md's #14
    decision record ("revisit once real abuse data exists") — this makes
    that data actually observable, so the "revisit" trigger can fire.
    Deliberately no new history table: contribution_votes already carries
    voter_id/weight_at_vote/created_at, and contributions.submitted_by
    ties a vote to who it was cast FOR — everything a first-pass
    clustering report needs already exists, so this derives it with a
    query instead of duplicating it into a parallel table.

    Surfaces pairs of accounts that have repeatedly endorsed EACH OTHER's
    pending contributions (both directions, each at least
    `min_reciprocal_count` times) — one of the cheapest-to-compute, most
    concrete signals of the two-colluding-accounts pattern #203 describes
    (each account clears a little real moderator-approved trust, then the
    pair combines weight to auto-approve each other's future submissions).
    Not anomaly detection or blocking — a moderator runs this periodically
    and reviews the flagged pairs by hand, same "manual is fine for v1"
    spirit as #23's canary/log-review approach.
    """
    result = await session.execute(
        text(
            """
            WITH endorsements AS (
                SELECT
                    cv.voter_id,
                    c.submitted_by AS submitter_id,
                    count(*) AS endorse_count,
                    max(cv.created_at) AS last_endorsed_at
                FROM contribution_votes cv
                JOIN contributions c ON c.id = cv.contribution_id
                WHERE cv.vote = 'endorse'
                  AND cv.voter_id IS NOT NULL
                  AND c.submitted_by IS NOT NULL
                  AND cv.voter_id != c.submitted_by
                GROUP BY cv.voter_id, c.submitted_by
            )
            SELECT
                a.voter_id AS user_a_id,
                ua.display_name AS user_a_display_name,
                a.submitter_id AS user_b_id,
                ub.display_name AS user_b_display_name,
                a.endorse_count AS a_endorsed_b_count,
                b.endorse_count AS b_endorsed_a_count,
                (a.endorse_count + b.endorse_count) AS combined_endorsement_count,
                GREATEST(a.last_endorsed_at, b.last_endorsed_at) AS last_activity_at
            FROM endorsements a
            JOIN endorsements b
                ON a.voter_id = b.submitter_id AND a.submitter_id = b.voter_id
            JOIN users ua ON ua.id = a.voter_id
            JOIN users ub ON ub.id = a.submitter_id
            WHERE a.voter_id < a.submitter_id
              AND a.endorse_count >= :min_reciprocal_count
              AND b.endorse_count >= :min_reciprocal_count
            ORDER BY combined_endorsement_count DESC, last_activity_at DESC
            LIMIT :limit
            """
        ),
        {"min_reciprocal_count": min_reciprocal_count, "limit": limit},
    )
    return list(result.fetchall())
