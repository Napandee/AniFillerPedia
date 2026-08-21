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
