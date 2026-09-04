"""Raw SQL data access for the users table — the only place that touches
it directly, per the layering convention (routers thin, services own
logic, repositories own the SQL).
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

PROVIDER_COLUMNS = {"github": "github_id", "discord": "discord_id", "google": "google_id"}


async def find_by_provider_id(
    session: AsyncSession, provider: str, provider_id: str
) -> Row | None:
    column = PROVIDER_COLUMNS[provider]
    result = await session.execute(
        text(f"SELECT * FROM users WHERE {column} = :provider_id"),  # noqa: S608 (column is from a fixed allowlist above, never user input)
        {"provider_id": provider_id},
    )
    return result.first()


async def find_by_id(session: AsyncSession, user_id: int) -> Row | None:
    result = await session.execute(
        text("SELECT * FROM users WHERE id = :id"), {"id": user_id}
    )
    return result.first()


async def create_user(
    session: AsyncSession,
    *,
    provider: str,
    provider_id: str,
    email: str | None,
    display_name: str | None,
    avatar_url: str | None,
    role: str,
) -> Row:
    column = PROVIDER_COLUMNS[provider]
    result = await session.execute(
        text(
            f"""
            INSERT INTO users ({column}, email, display_name, avatar_url, role, last_login_at)
            VALUES (:provider_id, :email, :display_name, :avatar_url, :role, now())
            RETURNING *
            """  # noqa: S608 (column is from a fixed allowlist above, never user input)
        ),
        {
            "provider_id": provider_id,
            "email": email,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "role": role,
        },
    )
    return result.one()


async def touch_last_login(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        text("UPDATE users SET last_login_at = now() WHERE id = :id"), {"id": user_id}
    )


async def delete_user(session: AsyncSession, user_id: int) -> None:
    """#29: self-service account deletion. Every FK referencing users is
    ON DELETE SET NULL (schema.sql) — this DELETE is the whole operation,
    anonymization of past contributions/votes/citations happens as a
    consequence of that FK behavior, not extra cleanup logic here.
    """
    await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


async def create_local_user(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    display_name: str,
    role: str,
) -> Row:
    result = await session.execute(
        text(
            """
            INSERT INTO users (email, password_hash, display_name, role, last_login_at)
            VALUES (:email, :password_hash, :display_name, :role, now())
            RETURNING *
            """
        ),
        {
            "email": email,
            "password_hash": password_hash,
            "display_name": display_name,
            "role": role,
        },
    )
    return result.one()


async def find_by_email_local(session: AsyncSession, email: str) -> Row | None:
    """Only ever matches a row with password_hash set — an OAuth-only
    row sharing this email (structurally possible, since OAuth emails
    were never unique) must never be treated as a local account."""
    result = await session.execute(
        text("SELECT * FROM users WHERE email = :email AND password_hash IS NOT NULL"),
        {"email": email},
    )
    return result.one_or_none()


async def owner_exists(session: AsyncSession) -> bool:
    """True when any row already holds role = 'owner'.

    Backs the email-keyed bootstrap-owner guard in services/auth.py: a
    local signup email is attacker-controlled free text (unlike a GitHub
    provider_id, which requires actually controlling that account), so
    the email bootstrap must only ever fire while no owner exists at all.
    """
    result = await session.execute(
        text("SELECT EXISTS (SELECT 1 FROM users WHERE role = 'owner')")
    )
    return bool(result.scalar())


async def link_provider(
    session: AsyncSession, *, user_id: int, provider: str, provider_id: str
) -> None:
    column = PROVIDER_COLUMNS[provider]
    await session.execute(
        text(f"UPDATE users SET {column} = :provider_id WHERE id = :user_id"),  # noqa: S608
        {"provider_id": provider_id, "user_id": user_id},
    )
