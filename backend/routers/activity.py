from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

import services.activity as activity_service
from core.db import get_session
from schemas.activity import ActivityFeedOut

router = APIRouter(tags=["activity"])


@router.get("/activity", response_model=ActivityFeedOut)
async def list_activity(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ActivityFeedOut:
    """#154: public, read-only "recent changes" feed — every resolved
    (approved/rejected/withdrawn) episode contribution and series
    proposal, newest first. Sourced entirely from the existing
    `contributions`/`series_proposals` audit trail (`reviewed_at`); no new
    writes, no new table. Public/unauthenticated, same trust level as
    `GET /series`'s own browse — this is read-only history, not the
    moderation queue (`GET /contributions`, moderator-only, pending-only).
    """
    return await activity_service.list_recent_activity(session, limit, offset)


@router.get("/activity/rss")
async def activity_rss(
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """RSS 2.0 rendering of the same feed above (Wikipedia "Recent
    changes" / OpenStreetMap changesets precedent, per #154's own issue
    text) — cheap to add given `list_activity` already returns exactly
    the rows an RSS item needs. No `offset`: an RSS reader always wants
    the newest window, not a specific page.
    """
    feed = await activity_service.list_recent_activity(session, limit, 0)
    return Response(content=activity_service.render_rss(feed), media_type="application/rss+xml")
