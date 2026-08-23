from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import services.series_proposals as series_proposals_service
import services.turnstile as turnstile_service
from core.db import get_session
from core.deps import get_current_user, get_current_user_optional, require_moderator
from schemas.moderation import BulkApproveRequest, BulkModerationResult, BulkRejectRequest
from schemas.series_proposals import (
    SeriesProposalCreate,
    SeriesProposalOut,
    SeriesProposalReject,
    SeriesProposalReviewOut,
)

router = APIRouter(tags=["series-proposals"])


@router.post("/series-proposals", response_model=SeriesProposalOut, status_code=201)
async def submit_series_proposal(
    payload: SeriesProposalCreate,
    current_user=Depends(get_current_user_optional),  # noqa: ANN001 - Row | None, anonymous allowed
    session: AsyncSession = Depends(get_session),
) -> SeriesProposalOut:
    if current_user is None:
        allowed = await turnstile_service.verify(payload.turnstile_token)
        if not allowed:
            raise HTTPException(status_code=422, detail="Turnstile verification failed")

    # Not a context-managed session.begin() — see the detailed comment in
    # routers/contributions.py's identical fix. Same root cause: the
    # get_current_user_optional dependency's SELECT autobegins a
    # transaction before this handler body runs.
    result = await series_proposals_service.submit_series_proposal(session, payload, current_user)
    await session.commit()
    return result


@router.get("/series-proposals/mine", response_model=list[SeriesProposalOut])
async def my_series_proposals(
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required
    session: AsyncSession = Depends(get_session),
) -> list[SeriesProposalOut]:
    return await series_proposals_service.list_my_series_proposals(session, current_user.id)


@router.get("/series-proposals", response_model=list[SeriesProposalOut])
async def list_pending_series_proposals(
    review_status: str = "pending",
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> list[SeriesProposalOut]:
    if review_status != "pending":
        raise HTTPException(status_code=404, detail="only review_status=pending is supported")
    return await series_proposals_service.list_pending_series_proposals(session)


@router.post("/series-proposals/bulk-approve", response_model=BulkModerationResult)
async def bulk_approve_series_proposals(
    payload: BulkApproveRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
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


@router.post("/series-proposals/bulk-reject", response_model=BulkModerationResult)
async def bulk_reject_series_proposals(
    payload: BulkRejectRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
    result = await series_proposals_service.bulk_reject_series_proposals(
        session, payload.ids, current_user.id, payload.review_note
    )
    await session.commit()
    return result


@router.post("/series-proposals/{series_proposal_id}/approve", response_model=SeriesProposalReviewOut)
async def approve_series_proposal(
    series_proposal_id: int,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> SeriesProposalReviewOut:
    result = await series_proposals_service.approve_series_proposal(
        session, series_proposal_id, current_user.id
    )
    await session.commit()
    return result


@router.post("/series-proposals/{series_proposal_id}/reject", response_model=SeriesProposalReviewOut)
async def reject_series_proposal(
    series_proposal_id: int,
    payload: SeriesProposalReject,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> SeriesProposalReviewOut:
    result = await series_proposals_service.reject_series_proposal(
        session, series_proposal_id, current_user.id, payload.review_note
    )
    await session.commit()
    return result
