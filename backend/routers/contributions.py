from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

import services.contributions as contributions_service
import services.turnstile as turnstile_service
from core.db import get_session
from core.deps import (
    get_current_user,
    get_current_user_optional,
    get_rate_limit_identifier,
    require_moderator,
)
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
from schemas.errors import ErrorDetail
from schemas.moderation import BulkApproveRequest, BulkModerationResult, BulkRejectRequest

router = APIRouter(tags=["contributions"])

_NOT_AUTHENTICATED = {401: {"model": ErrorDetail, "description": "Not authenticated"}}
_MODERATOR_ONLY = {
    **_NOT_AUTHENTICATED,
    403: {"model": ErrorDetail, "description": "Moderator, admin, or owner role required"},
}
_CONTRIBUTION_NOT_FOUND_OR_NOT_PENDING = {
    404: {"model": ErrorDetail, "description": "No contribution matches this id"},
    409: {"model": ErrorDetail, "description": "Contribution is not pending review"},
}


@router.post(
    "/contributions",
    response_model=ContributionOut,
    status_code=201,
    responses={
        409: {"model": DuplicatePendingContribution},
        429: {"model": BulkSubmissionRateLimited},
    },
)
async def submit_contribution(
    payload: ContributionCreate,
    request: Request,
    current_user=Depends(get_current_user_optional),  # noqa: ANN001 - Row | None, anonymous allowed
    session: AsyncSession = Depends(get_session),
) -> ContributionOut:
    """Propose a status (canon/filler/mixed) for one episode, with a
    citation. Anonymous submission is allowed by design (CLAUDE.md) — an
    anonymous caller needs a Turnstile token instead of login; an
    authenticated one skips Turnstile entirely. Rejected with 409 if the
    episode already has a pending contribution (#20's one-pending-per-
    episode rule) — endorse/dispute that one instead via
    `POST /contributions/{id}/vote`.
    """
    # Turnstile only gates the anonymous path (CLAUDE.md, decided
    # 2026-08-21) — an authenticated OAuth login is already a stronger
    # signal, checking it again here would be redundant.
    if current_user is None:
        allowed = await turnstile_service.verify(payload.turnstile_token)
        if not allowed:
            raise HTTPException(status_code=422, detail="Turnstile verification failed")

    # #139: identifies the caller for the rate-limit check below —
    # user id when authenticated, IP otherwise (core/deps.py).
    identifier = get_rate_limit_identifier(request, current_user)

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
    result = await contributions_service.submit_contribution(session, payload, current_user, identifier)
    await session.commit()
    return result


@router.post(
    "/series/{series_id}/contributions/bulk",
    response_model=BulkContributionResult,
    responses={
        **_NOT_AUTHENTICATED,
        404: {"model": ErrorDetail, "description": "No series matches this id"},
        429: {"model": BulkSubmissionRateLimited},
    },
)
async def submit_bulk_contributions(
    series_id: int,
    payload: BulkContributionCreate,
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required (#80, unlike single-episode submission)
    session: AsyncSession = Depends(get_session),
) -> BulkContributionResult:
    """#80: submit canon/filler/mixed episode RANGES for a series in one
    call (range notation, e.g. `"1-44, 48-49"`), sharing one citation
    across the whole batch — instead of one `POST /contributions` per
    episode. Requires login (unlike the single-episode path): one call
    here can create hundreds of pending contributions at once. Set
    `dry_run: true` to see exactly what would happen (parsed counts,
    which episodes would be skipped as already-pending) without writing
    anything.
    """
    result = await contributions_service.submit_bulk_contributions(session, series_id, payload, current_user)
    await session.commit()
    return result


@router.get("/contributions/mine", response_model=list[ContributionOut], responses=_NOT_AUTHENTICATED)
async def my_contributions(
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required
    session: AsyncSession = Depends(get_session),
) -> list[ContributionOut]:
    """Every contribution the CALLER has submitted, regardless of review
    status — requires login (an anonymous submission has no account to
    list this against).
    """
    return await contributions_service.list_my_contributions(session, current_user.id)


@router.get("/contributions/mine/votes", response_model=list[MyVoteOut], responses=_NOT_AUTHENTICATED)
async def my_votes(
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required
    session: AsyncSession = Depends(get_session),
) -> list[MyVoteOut]:
    """#30: votes-cast counterpart to `/contributions/mine` above — every
    endorse/dispute vote the caller has cast, with enough context (series
    title, episode, current resolution) to render without a follow-up
    request per row.
    """
    return await contributions_service.list_my_votes(session, current_user.id)


@router.get(
    "/contributions",
    response_model=list[ContributionOut],
    responses={
        **_MODERATOR_ONLY,
        404: {"model": ErrorDetail, "description": "review_status is anything other than 'pending'"},
    },
)
async def list_pending_contributions(
    review_status: str = "pending",
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> list[ContributionOut]:
    """#13: the moderation queue — every contribution currently pending
    review. Moderator/admin/owner only. `review_status` is accepted but
    only the default `pending` is meaningful right now; anything else
    404s rather than silently returning an empty list, so a caller finds
    out immediately if they typo'd it.
    """
    if review_status != "pending":
        raise HTTPException(status_code=404, detail="only review_status=pending is supported")
    return await contributions_service.list_pending_contributions(session)


@router.post(
    "/contributions/bulk-approve", response_model=BulkModerationResult, responses=_MODERATOR_ONLY
)
async def bulk_approve_contributions(
    payload: BulkApproveRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
    """#92: approve up to 500 pending contributions in one call. Moderator/
    admin/owner only. Never fails wholesale on one bad id — each id in
    `ids` gets its own `ok`/`detail` outcome in the result, same per-id
    error text `POST /contributions/{id}/approve` would give individually
    (e.g. "not found" or "not pending").
    """
    # #3: flat "bulk-approve" path (not /contributions/bulk/approve) is
    # deliberate — a 3-segment shape would structurally collide with
    # /contributions/{contribution_id}/approve below, since "bulk" would
    # attempt (and fail) int coercion as the id rather than falling
    # through to this route.
    result = await contributions_service.bulk_approve_contributions(session, payload.ids, current_user.id)
    await session.commit()
    return result


@router.post(
    "/contributions/bulk-reject", response_model=BulkModerationResult, responses=_MODERATOR_ONLY
)
async def bulk_reject_contributions(
    payload: BulkRejectRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
    """Same shape as `POST /contributions/bulk-approve`, but rejecting —
    with one shared `review_note` reason applied to every id in the batch
    rather than a per-item note. Moderator/admin/owner only.
    """
    result = await contributions_service.bulk_reject_contributions(
        session, payload.ids, current_user.id, payload.review_note
    )
    await session.commit()
    return result


@router.post(
    "/contributions/{contribution_id}/approve",
    response_model=ContributionReviewOut,
    responses={**_MODERATOR_ONLY, **_CONTRIBUTION_NOT_FOUND_OR_NOT_PENDING},
)
async def approve_contribution(
    contribution_id: int,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> ContributionReviewOut:
    """Directly approve a pending contribution — the moderator half of
    #13's two approval paths (the other being #14's community vote
    threshold below). Moderator/admin/owner only.
    """
    result = await contributions_service.approve_contribution(session, contribution_id, current_user.id)
    await session.commit()
    return result


@router.post(
    "/contributions/{contribution_id}/reject",
    response_model=ContributionReviewOut,
    responses={**_MODERATOR_ONLY, **_CONTRIBUTION_NOT_FOUND_OR_NOT_PENDING},
)
async def reject_contribution(
    contribution_id: int,
    payload: ContributionReject,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> ContributionReviewOut:
    """Directly reject a pending contribution, with a required
    `review_note` explaining why. Moderator/admin/owner only.
    """
    result = await contributions_service.reject_contribution(
        session, contribution_id, current_user.id, payload.review_note
    )
    await session.commit()
    return result


@router.post(
    "/contributions/{contribution_id}/vote",
    response_model=VoteCastOut,
    responses={
        **_NOT_AUTHENTICATED,
        403: {"model": ErrorDetail, "description": "Cannot vote on your own submitted contribution"},
        404: {"model": ErrorDetail, "description": "No contribution matches this id"},
        409: {
            "model": ErrorDetail,
            "description": "Contribution is not pending, or you have already voted on it",
        },
    },
)
async def vote_on_contribution(
    contribution_id: int,
    payload: VoteCreate,
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, any logged-in user (not moderator-gated)
    session: AsyncSession = Depends(get_session),
) -> VoteCastOut:
    """#14: the second approval path (CLAUDE.md) — endorse or dispute a
    pending contribution. Open to any logged-in user, not just
    moderators; anonymous voting is not offered, since a vote's value
    comes from being weighted by the voter's own accountable
    `trust_score`. A submitter cannot vote on their own contribution, and
    each account gets one vote per contribution. Once cumulative weighted
    endorsement crosses the auto-approval threshold, the contribution
    promotes automatically — no moderator click needed.
    """
    # Same non-session.begin() pattern as approve/reject above:
    # get_current_user already autobegan a transaction on this session.
    result = await contributions_service.cast_vote(session, contribution_id, current_user, payload.vote)
    await session.commit()
    return result
