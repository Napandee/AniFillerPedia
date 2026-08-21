"""Raw SQL for issue #22 (export access) and the full-dataset dump itself.

The dataset query is intentionally the same shape as episodes.py's
per-series query, just unfiltered — live-computed per request, not cached.
No object-storage credentials exist yet to cache this via (see CLAUDE.md's
stay-stateless Guardrail); a live query persists nothing to local disk, so
it's already compliant without needing them. Caching via object storage
is a real future optimization once traffic justifies it, not a v1
correctness requirement.
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def insert_api_key_request(
    session: AsyncSession,
    *,
    email: str,
    license_accepted: bool,
    terms_version: str,
    key_hash: str,
) -> int:
    result = await session.execute(
        text(
            """
            INSERT INTO export_api_keys (email, license_accepted, terms_version, key_hash)
            VALUES (:email, :license_accepted, :terms_version, :key_hash)
            RETURNING id
            """
        ),
        {
            "email": email,
            "license_accepted": license_accepted,
            "terms_version": terms_version,
            "key_hash": key_hash,
        },
    )
    return result.scalar_one()


async def get_valid_key_record(session: AsyncSession, key_hash: str) -> Row | None:
    result = await session.execute(
        text(
            "SELECT id, email FROM export_api_keys "
            "WHERE key_hash = :key_hash AND revoked_at IS NULL"
        ),
        {"key_hash": key_hash},
    )
    return result.first()


async def fetch_full_dataset(session: AsyncSession) -> list[Row]:
    """All series + their episodes + citations, one row per episode. A
    series with zero approved episodes yet still needs representing (per
    CLAUDE.md: absence of an episode row means "no data," not the series
    itself being absent from the catalog) — LEFT JOIN, not INNER.
    """
    result = await session.execute(
        text(
            """
            SELECT s.id AS series_id, s.anilist_id, s.mal_id, s.anidb_id,
                   s.title AS series_title, s.provenance,
                   e.id AS episode_id, e.episode_number, e.status,
                   e.status_note, e.updated_at AS episode_updated_at,
                   c.url AS citation_url, c.description AS citation_description
            FROM series s
            LEFT JOIN episodes e ON e.series_id = s.id
            LEFT JOIN citations c ON c.id = e.citation_id
            ORDER BY s.id, e.episode_number
            """
        )
    )
    return list(result.fetchall())
