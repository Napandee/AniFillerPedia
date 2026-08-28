from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

import services.episodes as episodes_service
import services.series as series_service
from core.conditional import apply_conditional_headers, not_modified
from core.db import get_session
from schemas.episodes import EpisodeOut
from schemas.errors import ErrorDetail
from schemas.series import SeriesDetailOut, SeriesListOut

router = APIRouter(tags=["series"])

_SERIES_NOT_FOUND = {404: {"model": ErrorDetail, "description": "No series matches this id or slug"}}


@router.get("/series", response_model=SeriesListOut)
async def list_series(
    q: str | None = Query(default=None, description="Title or synonym search"),
    anilist_id: int | None = None,
    mal_id: int | None = None,
    anidb_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort: str | None = Query(default=None, pattern="^(recently_updated)$"),
    session: AsyncSession = Depends(get_session),
) -> SeriesListOut:
    """Search/list the series catalog. Public, unauthenticated.

    `q` matches title and known synonyms (alternate/romanized/native-script
    titles). A plain call with no `q` and no external id (`anilist_id`/
    `mal_id`/`anidb_id`) excludes series with zero researched episodes —
    see docs/API.md for why. Pass `sort=recently_updated` to order by which
    series had an episode's status most recently approved instead of the
    default insertion order.
    """
    return await series_service.search_series(
        session, q, anilist_id, mal_id, anidb_id, limit, offset, sort
    )


@router.get("/series/{id_or_slug}", response_model=SeriesDetailOut, responses=_SERIES_NOT_FOUND)
async def get_series(
    id_or_slug: str,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> SeriesDetailOut | Response:
    """#116: accepts either a numeric series id (legacy URLs — the
    frontend 301-redirects these to the canonical slug URL, but the API
    itself keeps resolving both indefinitely, since it's a public contract
    other consumers may already depend on) or a slug.

    #155: conditional-request support — a caller sending a matching
    If-None-Match/If-Modified-Since gets a bare 304 instead of the full
    body; everyone else gets ETag/Last-Modified on the normal 200 so a
    later poll can do the same. See services.series.get_series_conditional
    for what the timestamp/ETag are derived from.
    """
    body, last_modified, etag = await series_service.get_series_conditional(session, id_or_slug)
    if not_modified(request, etag=etag, last_modified=last_modified):
        not_modified_response = Response(status_code=304)
        apply_conditional_headers(not_modified_response, etag=etag, last_modified=last_modified)
        return not_modified_response
    apply_conditional_headers(response, etag=etag, last_modified=last_modified)
    return body


@router.get(
    "/series/{series_id}/episodes",
    response_model=list[EpisodeOut],
    responses=_SERIES_NOT_FOUND,
)
async def list_series_episodes(
    series_id: int,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> list[EpisodeOut] | Response:
    """#155: same conditional-request support as GET /series/{id} above,
    derived from MAX(episodes.updated_at) for this series instead — see
    services.episodes.list_episodes_for_series_conditional.
    """
    body, last_modified, etag = await episodes_service.list_episodes_for_series_conditional(
        session, series_id
    )
    if not_modified(request, etag=etag, last_modified=last_modified):
        not_modified_response = Response(status_code=304)
        apply_conditional_headers(not_modified_response, etag=etag, last_modified=last_modified)
        return not_modified_response
    apply_conditional_headers(response, etag=etag, last_modified=last_modified)
    return body
