from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

import services.synonym_suggestions as synonym_suggestions_service
import services.turnstile as turnstile_service
from core.db import get_session
from core.deps import (
    get_current_user,
    get_current_user_optional,
    get_rate_limit_identifier,
    require_moderator,
)
from schemas.errors import ErrorDetail
from schemas.moderation import BulkApproveRequest, BulkModerationResult, BulkRejectRequest
from schemas.synonym_suggestions import (
    DuplicatePendingSynonymSuggestion,
    SynonymSuggestionCreate,
    SynonymSuggestionOut,
    SynonymSuggestionReject,
    SynonymSuggestionReviewOut,
)

router = APIRouter(tags=["synonym-suggestions"])

_NOT_AUTHENTICATED = {401: {"model": ErrorDetail, "description": "Not authenticated"}}
_MODERATOR_ONLY = {
    **_NOT_AUTHENTICATED,
    403: {"model": ErrorDetail, "description": "Moderator, admin, or owner role required"},
}
_SUGGESTION_NOT_FOUND_OR_NOT_PENDING = {
    404: {"model": ErrorDetail, "description": "No synonym suggestion matches this id"},
    409: {"model": ErrorDetail, "description": "Synonym suggestion is not pending review"},
}


@router.post(
    "/synonym-suggestions",
    response_model=SynonymSuggestionOut,
    status_code=201,
    responses={
        404: {"model": ErrorDetail, "description": "No series matches series_id"},
        409: {"model": DuplicatePendingSynonymSuggestion},
        429: {"model": ErrorDetail, "description": "Rate limit exceeded"},
    },
)
async def submit_synonym_suggestion(
    payload: SynonymSuggestionCreate,
    request: Request,
    current_user=Depends(get_current_user_optional),  # noqa: ANN001 - Row | None, anonymous allowed
    session: AsyncSession = Depends(get_session),
) -> SynonymSuggestionOut:
    """#148: suggest an alternate/dub/regional title for an already-
    catalogued series. Anonymous submission is allowed (needs a Turnstile
    token instead of login, same as `POST /contributions` and
    `POST /series-proposals`) — moderator approval is what promotes it
    into the live `series_synonyms` table, never a direct write.
    """
    if current_user is None:
        allowed = await turnstile_service.verify(payload.turnstile_token)
        if not allowed:
            raise HTTPException(status_code=422, detail="Turnstile verification failed")

    identifier = get_rate_limit_identifier(request, current_user)

    # Not a context-managed session.begin() — same fix as routers/
    # contributions.py and routers/series_proposals.py: the
    # get_current_user_optional dependency's SELECT autobegins a
    # transaction before this handler body runs.
    result = await synonym_suggestions_service.submit_synonym_suggestion(
        session, payload, current_user, identifier
    )
    await session.commit()
    return result


@router.get(
    "/synonym-suggestions/mine",
    response_model=list[SynonymSuggestionOut],
    responses=_NOT_AUTHENTICATED,
)
async def my_synonym_suggestions(
    current_user=Depends(get_current_user),  # noqa: ANN001 - Row, auth required
    session: AsyncSession = Depends(get_session),
) -> list[SynonymSuggestionOut]:
    """Every synonym suggestion the CALLER has submitted, regardless of
    review status. Requires login (mirrors GET /series-proposals/mine).
    """
    return await synonym_suggestions_service.list_my_synonym_suggestions(session, current_user.id)


@router.get(
    "/synonym-suggestions",
    response_model=list[SynonymSuggestionOut],
    responses={
        **_MODERATOR_ONLY,
        404: {"model": ErrorDetail, "description": "review_status is anything other than 'pending'"},
    },
)
async def list_pending_synonym_suggestions(
    review_status: str = "pending",
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> list[SynonymSuggestionOut]:
    """The moderation queue for synonym suggestions — mirrors
    `GET /contributions`/`GET /series-proposals`'s own review_status
    behavior exactly. Moderator/admin/owner only.
    """
    if review_status != "pending":
        raise HTTPException(status_code=404, detail="only review_status=pending is supported")
    return await synonym_suggestions_service.list_pending_synonym_suggestions(session)


@router.post(
    "/synonym-suggestions/bulk-approve", response_model=BulkModerationResult, responses=_MODERATOR_ONLY
)
async def bulk_approve_synonym_suggestions(
    payload: BulkApproveRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
    """Same shape as the contributions/series-proposals bulk-approve
    endpoints. Moderator/admin/owner only.
    """
    result = await synonym_suggestions_service.bulk_approve_synonym_suggestions(
        session, payload.ids, current_user.id
    )
    await session.commit()
    return result


@router.post(
    "/synonym-suggestions/bulk-reject", response_model=BulkModerationResult, responses=_MODERATOR_ONLY
)
async def bulk_reject_synonym_suggestions(
    payload: BulkRejectRequest,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> BulkModerationResult:
    result = await synonym_suggestions_service.bulk_reject_synonym_suggestions(
        session, payload.ids, current_user.id, payload.review_note
    )
    await session.commit()
    return result


@router.post(
    "/synonym-suggestions/{suggestion_id}/approve",
    response_model=SynonymSuggestionReviewOut,
    responses={
        **_MODERATOR_ONLY,
        **_SUGGESTION_NOT_FOUND_OR_NOT_PENDING,
        409: {
            "model": ErrorDetail,
            "description": "Not pending review, or this series already has that exact synonym recorded",
        },
    },
)
async def approve_synonym_suggestion(
    suggestion_id: int,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> SynonymSuggestionReviewOut:
    """Approves the suggestion and inserts the real row into
    `series_synonyms`. Moderator/admin/owner only.
    """
    result = await synonym_suggestions_service.approve_synonym_suggestion(
        session, suggestion_id, current_user.id
    )
    await session.commit()
    return result


@router.post(
    "/synonym-suggestions/{suggestion_id}/reject",
    response_model=SynonymSuggestionReviewOut,
    responses={**_MODERATOR_ONLY, **_SUGGESTION_NOT_FOUND_OR_NOT_PENDING},
)
async def reject_synonym_suggestion(
    suggestion_id: int,
    payload: SynonymSuggestionReject,
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin only
    session: AsyncSession = Depends(get_session),
) -> SynonymSuggestionReviewOut:
    """Rejects the suggestion, with a required `review_note`. Moderator/
    admin/owner only.
    """
    result = await synonym_suggestions_service.reject_synonym_suggestion(
        session, suggestion_id, current_user.id, payload.review_note
    )
    await session.commit()
    return result
