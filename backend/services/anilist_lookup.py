"""#165: live, single-ID AniList lookup + early duplicate detection for
the series-proposal submission form.

Deliberately checks our own `series` table FIRST, before ever calling out
to AniList — an id that's already catalogued needs no live AniList
round-trip at all, which both saves the request and means an already-
answered lookup never counts against AniList's own real-world rate limit
(see anilist_sync.py's own module docstring on that limit running lower
in practice than documented).
"""

from sqlalchemy.ext.asyncio import AsyncSession

import repositories.series as series_repo
from schemas.anilist_lookup import AniListLookupOut
from services.anilist_sync import fetch_anilist_media_summary


async def lookup_anilist_id(session: AsyncSession, anilist_id: int) -> AniListLookupOut:
    existing = await series_repo.get_by_anilist_id(session, anilist_id)
    if existing is not None:
        return AniListLookupOut(
            status="already_exists",
            anilist_id=anilist_id,
            title=existing.title,
            existing_series_id=existing.id,
            existing_series_slug=existing.slug,
        )

    summary = await fetch_anilist_media_summary(anilist_id)
    if summary is None:
        return AniListLookupOut(status="not_found", anilist_id=anilist_id)

    return AniListLookupOut(
        status="found",
        anilist_id=anilist_id,
        title=summary.title,
        format=summary.format,
        episode_count=summary.episode_count,
        cover_image_url=summary.cover_image_url,
    )
