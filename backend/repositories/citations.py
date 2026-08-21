"""Raw SQL for citations. Only a create is needed here — reads happen via
JOINs from contributions/episodes repositories, there's no standalone
"list citations" concept.
"""

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def create(
    session: AsyncSession, *, url: str | None, description: str, submitted_by: int | None
) -> Row:
    result = await session.execute(
        text(
            """
            INSERT INTO citations (url, description, submitted_by)
            VALUES (:url, :description, :submitted_by)
            RETURNING *
            """
        ),
        {"url": url, "description": description, "submitted_by": submitted_by},
    )
    return result.one()
