from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.rate_limits as rate_limits_repo
import services.anilist_lookup as anilist_lookup_service
from core.db import get_session
from core.deps import get_current_user_optional, get_rate_limit_identifier
from schemas.anilist_lookup import AniListLookupOut

router = APIRouter(tags=["anilist-lookup"])

# #165: this endpoint proxies a real, single-request call to AniList's own
# public GraphQL API on behalf of an anonymous browser (blur-triggered, so
# in normal use it fires at most once per distinct id a submitter types) —
# without a throttle, it's an open door for someone to hammer AniList far
# past its own real-world rate ceiling on our behalf (see anilist_sync.py's
# module docstring — AniList's real limit runs lower in practice than
# documented under load). Reuses the same generic rate_limit_events
# mechanism as every other anonymous-accessible write/proxy endpoint
# (repositories/rate_limits.py) rather than inventing a bespoke one.
ANILIST_LOOKUP_RATE_LIMIT = 30
ANILIST_LOOKUP_RATE_LIMIT_WINDOW_SECONDS = 60 * 60


@router.get("/anilist-lookup/{anilist_id}", response_model=AniListLookupOut)
async def anilist_lookup(
    request: Request,
    anilist_id: int = Path(gt=0),
    current_user=Depends(get_current_user_optional),  # noqa: ANN001 - Row | None, anonymous allowed
    session: AsyncSession = Depends(get_session),
) -> AniListLookupOut:
    identifier = get_rate_limit_identifier(request, current_user)
    recent_count = await rate_limits_repo.count_recent(
        session,
        scope="anilist_lookup",
        identifier=identifier,
        window_seconds=ANILIST_LOOKUP_RATE_LIMIT_WINDOW_SECONDS,
    )
    if recent_count >= ANILIST_LOOKUP_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many AniList lookups ({recent_count} in the last hour, limit "
                f"{ANILIST_LOOKUP_RATE_LIMIT}). Try again later."
            ),
        )

    # Not a context-managed session.begin() — same reasoning as
    # routers/contributions.py's submit_contribution: get_current_user_optional
    # already autobegins a transaction via its own SELECT before this
    # handler body runs.
    await rate_limits_repo.record(session, scope="anilist_lookup", identifier=identifier)
    result = await anilist_lookup_service.lookup_anilist_id(session, anilist_id)
    await session.commit()
    return result
