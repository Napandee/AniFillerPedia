from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import services.contributions as contributions_service
import services.turnstile as turnstile_service
from core.db import get_session
from core.deps import get_current_user, get_current_user_optional, require_moderator
from schemas.contributions import (
    BulkContributionCreate,
    BulkContributionResult,
    BulkSubmissionRateLimited,
    ContributionCreate,
    ContributionOut,
    ContributionReject,
    ContributionReviewOut,
    DuplicatePendingContribution,
    MyVoteOut,
    VoteCastOut,
    VoteCreate,
)
from schemas.moderation import BulkApproveRequest, BulkModerationResult, BulkRejectRequest

router = APIRouter(tags=["contributions"])


@router.post(
    "/contributions",
    response_model=ContributionOut,
    status_code=201,
    responses={409: {"model": DuplicatePendingContribution}},
)
async def submit_contribution(
    payload: ContributionCreate,
    current_user=Depends(get_current_user_optional),  # noqa: ANN001 - Row | None, anonymous allowed
    session: AsyncSession = Depends(get_session),
) -> ContributionOut:
    # Turnstile only gates the anonymous path (CLAUDE.md, decided
    # 2026-08-21) — an authenticated OAuth login is already a stronger
    # signal, checking it again here would be redundant.
    if current_user is None:
        allowed = await turnstile_service.verify(payload.turnstile_token)
        if not allowed:
            raise HTTPException(status_code=422, detail="Turnstile verification failed")

    # NOT `async with session.begin():` here — deliberately. When
    # current_user is resolved (get_current_user_optional runs a SELECT),
    # SQLAlchemy's AsyncSession autobegins a transaction on that first
    # execute(), and session.begin() then raises "a transaction is already
    # begun." Every prior get_session()-consuming handler in this codebase
    # only ever exercised ONE of {an auth dependency, an explicit begin()}
    # per request, never both, so this never surfaced before — caught by
    # actually testing the authenticated submission path, not the
    # anonymous one every earlier test happened to use. get_session()
    # still doesn't auto-commit (#8's own fix note, core/db.py), so the
    # explicit commit below is still required either way.
    result = await contributions_service.submit_contribution(session, payload, current_user)
    await session.commit()
    return result


@router.post(
    "/series/{series_id}/contributions/bulk",
    response_model=BulkContributionResult,
    responses={429: {"model": BulkSubmissionRateLimited}},
)
async def submit_bulk_contributions(
    series_id: int,
    payload: BulkContributionCreate,
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required (#80, unlike single-episode submission)
    session: AsyncSession = Depends(get_session),
) -> BulkContributionResult:
    result = await contributions_service.submit_bulk_contributions(session, series_id, payload, current_user)
    await session.commit()
    return result


@router.get("/contributions/mine", response_model=list[ContributionOut])
async def my_contributions(
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required
    session: AsyncSession = Depends(get_session),
) -> list[ContributionOut]:
    return await contributions_service.list_my_contributions(session, current_user.id)


@router.get("/contributions/mine/votes", response_model=list[MyVoteOut])
async def my_votes(
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required
    session: AsyncSession = Depends(get_session),
) -> list[MyVoteOut]:
    # #30: votes-cast counterpart to /contributions/mine (own submissions).
    return await contributions_service.list_my_votes(session, current_user.id)


@router.get("/contributions", response_model=list[ContributionOut])
async def list_pending_contributions(
    review_status: str = "pending",
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> list[ContributionOut]:
    # #13: the moderation queue. review_status is accepted but only
    # "pending" is meaningful right now — everything else 404s rather than
    # silently returning an empty list, so a caller finds out immediately
    # if they typo'd it rather than assuming the queue is empty.
    if review_status != "pending":
        raise HTTPException(status_code=404, detail="only review_status=pending is supported")
    return await contributions_service.list_pending_contributions(session)


@router.post("/contributions/bulk-approve", response_model=BulkModerationResult)
async def bulk_approve_contributions(
    payload: BulkApproveRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
    # #3: flat "bulk-approve" path (not /contributions/bulk/approve) is
    # deliberate — a 3-segment shape would structurally collide with
    # /contributions/{contribution_id}/approve below, since "bulk" would
    # attempt (and fail) int coercion as the id rather than falling
    # through to this route.
    result = await contributions_service.bulk_approve_contributions(session, payload.ids, current_user.id)
    await session.commit()
    return result


@router.post("/contributions/bulk-reject", response_model=BulkModerationResult)
async def bulk_reject_contributions(
    payload: BulkRejectRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
    result = await contributions_service.bulk_reject_contributions(
        session, payload.ids, current_user.id, payload.review_note
    )
    await session.commit()
    return result


@router.post("/contributions/{contribution_id}/approve", response_model=ContributionReviewOut)
async def approve_contribution(
    contribution_id: int,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> ContributionReviewOut:
    result = await contributions_service.approve_contribution(session, contribution_id, current_user.id)
    await session.commit()
    return result


@router.post("/contributions/{contribution_id}/reject", response_model=ContributionReviewOut)
async def reject_contribution(
    contribution_id: int,
    payload: ContributionReject,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> ContributionReviewOut:
    result = await contributions_service.reject_contribution(
        session, contribution_id, current_user.id, payload.review_note
    )
    await session.commit()
    return result


@router.post("/contributions/{contribution_id}/vote", response_model=VoteCastOut)
async def vote_on_contribution(
    contribution_id: int,
    payload: VoteCreate,
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, any logged-in user (not moderator-gated)
    session: AsyncSession = Depends(get_session),
) -> VoteCastOut:
    # #14: the second approval path (CLAUDE.md) — endorse/dispute is open
    # to any authenticated user, not just moderators; anonymous voting is
    # not offered (unlike submission) since a vote's whole value is being
    # weighted by an accountable trust_score. Same non-session.begin()
    # pattern as approve/reject above: get_current_user already autobegan
    # a transaction on this session.
    result = await contributions_service.cast_vote(session, contribution_id, current_user, payload.vote)
    await session.commit()
    return result
