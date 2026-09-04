from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

import services.series_proposals as series_proposals_service
import services.turnstile as turnstile_service
from core.db import get_session
from core.deps import (
    ensure_not_suspended,
    get_current_user,
    get_current_user_optional,
    get_rate_limit_identifier,
    require_moderator,
)
from schemas.contributions import BulkSubmissionRateLimited
from schemas.errors import ErrorDetail
from schemas.moderation import BulkApproveRequest, BulkModerationResult, BulkRejectRequest
from schemas.series_proposals import (
    SeriesProposalCreate,
    SeriesProposalOut,
    SeriesProposalReject,
    SeriesProposalReviewOut,
    SimilarSeriesCheckOut,
)

router = APIRouter(tags=["series-proposals"])

_NOT_AUTHENTICATED = {401: {"model": ErrorDetail, "description": "Not authenticated"}}
_MODERATOR_ONLY = {
    **_NOT_AUTHENTICATED,
    403: {"model": ErrorDetail, "description": "Moderator, admin, or owner role required"},
}
_PROPOSAL_NOT_FOUND_OR_NOT_PENDING = {
    404: {"model": ErrorDetail, "description": "No series proposal matches this id"},
    409: {"model": ErrorDetail, "description": "Series proposal is not pending review"},
}


@router.get("/series-proposals/check-title", response_model=SimilarSeriesCheckOut)
async def check_title_for_duplicates(
    title: str = Query(default="", max_length=300),
    session: AsyncSession = Depends(get_session),
) -> SimilarSeriesCheckOut:
    """#150: pre-submission duplicate hint — the propose-series form calls
    this on Title-field blur, same "possible match" pattern #165's
    anilist-lookup endpoint uses for the ID-present path. Public/
    unauthenticated (a plain read against our own catalog, same trust
    level as GET /series's own search) and never errors on an empty/
    unmatched title — an empty result is a completely normal outcome, not
    a client mistake.
    """
    if not title.strip():
        return SimilarSeriesCheckOut(matches=[])
    return await series_proposals_service.check_similar_series_by_title(session, title)


@router.post(
    "/series-proposals",
    response_model=SeriesProposalOut,
    status_code=201,
    responses={429: {"model": BulkSubmissionRateLimited}},
)
async def submit_series_proposal(
    payload: SeriesProposalCreate,
    request: Request,
    current_user=Depends(get_current_user_optional),  # noqa: ANN001 - Row | None, anonymous allowed
    session: AsyncSession = Depends(get_session),
) -> SeriesProposalOut:
    """Propose a series that isn't in the catalog yet. Anonymous
    submission is allowed (needs a Turnstile token instead of login,
    same as `POST /contributions`). Optionally carries `episode_data`
    (#85) — the same canon/mixed/filler-range shorthand as
    `POST /series/{id}/contributions/bulk` — held on the proposal until a
    moderator approves it, at which point the series row and the real
    bulk contributions are created together in one transaction; rejecting
    the proposal discards the attached data.
    """
    # #209: blocks a logged-in-but-suspended caller before Turnstile runs;
    # no-op for an anonymous caller (current_user is None).
    ensure_not_suspended(current_user)

    if current_user is None:
        allowed = await turnstile_service.verify(payload.turnstile_token)
        if not allowed:
            raise HTTPException(status_code=422, detail="Turnstile verification failed")

    # #139: identifies the caller for the episode_data rate-limit check
    # (services/series_proposals.py) — user id when authenticated, IP
    # otherwise.
    identifier = get_rate_limit_identifier(request, current_user)

    # Not a context-managed session.begin() — see the detailed comment in
    # routers/contributions.py's identical fix. Same root cause: the
    # get_current_user_optional dependency's SELECT autobegins a
    # transaction before this handler body runs.
    result = await series_proposals_service.submit_series_proposal(
        session, payload, current_user, identifier
    )
    await session.commit()
    return result


@router.get(
    "/series-proposals/mine", response_model=list[SeriesProposalOut], responses=_NOT_AUTHENTICATED
)
async def my_series_proposals(
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required
    session: AsyncSession = Depends(get_session),
) -> list[SeriesProposalOut]:
    """Every series proposal the CALLER has submitted, regardless of
    review status. Requires login.
    """
    return await series_proposals_service.list_my_series_proposals(session, current_user.id)


@router.get(
    "/series-proposals",
    response_model=list[SeriesProposalOut],
    responses={
        **_MODERATOR_ONLY,
        404: {"model": ErrorDetail, "description": "review_status is anything other than 'pending'"},
    },
)
async def list_pending_series_proposals(
    review_status: str = "pending",
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> list[SeriesProposalOut]:
    """The moderation queue for series proposals — mirrors
    `GET /contributions`'s own review_status behavior exactly. Moderator/
    admin/owner only.
    """
    if review_status != "pending":
        raise HTTPException(status_code=404, detail="only review_status=pending is supported")
    return await series_proposals_service.list_pending_series_proposals(session)


@router.post(
    "/series-proposals/bulk-approve", response_model=BulkModerationResult, responses=_MODERATOR_ONLY
)
async def bulk_approve_series_proposals(
    payload: BulkApproveRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
    """Same shape as `POST /contributions/bulk-approve`, for series
    proposals instead. Moderator/admin/owner only.
    """
    # #3: flat "bulk-approve" path (not /series-proposals/bulk/approve) is
    # deliberate — a 3-segment shape would structurally collide with
    # /series-proposals/{series_proposal_id}/approve below, since "bulk"
    # would attempt (and fail) int coercion as the id rather than falling
    # through to this route.
    result = await series_proposals_service.bulk_approve_series_proposals(
        session, payload.ids, current_user.id
    )
    await session.commit()
    return result


@router.post(
    "/series-proposals/bulk-reject", response_model=BulkModerationResult, responses=_MODERATOR_ONLY
)
async def bulk_reject_series_proposals(
    payload: BulkRejectRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
    """Same shape as `POST /contributions/bulk-reject`, for series
    proposals instead. Moderator/admin/owner only.
    """
    result = await series_proposals_service.bulk_reject_series_proposals(
        session, payload.ids, current_user.id, payload.review_note
    )
    await session.commit()
    return result


@router.post(
    "/series-proposals/{series_proposal_id}/approve",
    response_model=SeriesProposalReviewOut,
    responses={
        **_MODERATOR_ONLY,
        **_PROPOSAL_NOT_FOUND_OR_NOT_PENDING,
        409: {
            "model": ErrorDetail,
            "description": "Not pending review, or a series with one of this proposal's "
            "external IDs (anilist_id/mal_id/anidb_id) already exists in the catalog",
        },
    },
)
async def approve_series_proposal(
    series_proposal_id: int,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> SeriesProposalReviewOut:
    """Approves the proposal and creates the real `series` catalog row.
    #85: if the proposal carried attached `episode_data`, this also
    creates the real bulk contributions against the new series in the
    same transaction — see `POST /series-proposals` for how that data
    gets attached. Moderator/admin/owner only.
    """
    result = await series_proposals_service.approve_series_proposal(
        session, series_proposal_id, current_user.id
    )
    await session.commit()
    return result


@router.post(
    "/series-proposals/{series_proposal_id}/reject",
    response_model=SeriesProposalReviewOut,
    responses={**_MODERATOR_ONLY, **_PROPOSAL_NOT_FOUND_OR_NOT_PENDING},
)
async def reject_series_proposal(
    series_proposal_id: int,
    payload: SeriesProposalReject,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> SeriesProposalReviewOut:
    """Rejects the proposal, with a required `review_note` explaining
    why. Any attached `episode_data` is discarded for free — it never
    became more than JSON on the now-rejected row. Moderator/admin/owner
    only.
    """
    result = await series_proposals_service.reject_series_proposal(
        session, series_proposal_id, current_user.id, payload.review_note
    )
    await session.commit()
    return result
