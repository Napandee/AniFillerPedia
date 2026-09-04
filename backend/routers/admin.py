from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

import services.admin as admin_service
from core.db import get_session
from core.deps import require_admin, require_moderator
from schemas.admin import (
    AdminUserListOut,
    RoleUpdateIn,
    RoleUpdateOut,
    SuspensionUpdateIn,
    SuspensionUpdateOut,
    VoteClusteringReportOut,
)
from schemas.errors import ErrorDetail

router = APIRouter(tags=["admin"])

_ADMIN_ONLY = {
    401: {"model": ErrorDetail, "description": "Not authenticated"},
    403: {"model": ErrorDetail, "description": "Admin or owner access required"},
}


@router.get("/admin/users", response_model=AdminUserListOut, responses=_ADMIN_ONLY)
async def list_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(require_admin),  # noqa: ANN001 - Row, admin-only
    session: AsyncSession = Depends(get_session),
) -> AdminUserListOut:
    """Every user account, with each one's computed `trust_score` and
    approved/rejected contribution counts. Admin (or owner) only — see
    `GET /users/me` for a caller's own equivalent, available to everyone.
    """
    return await admin_service.list_users(session, limit, offset)


@router.patch(
    "/admin/users/{user_id}/role",
    response_model=RoleUpdateOut,
    responses={
        **_ADMIN_ONLY,
        403: {
            "model": ErrorDetail,
            "description": "Admin/owner access required, OR the target is the owner "
            "(role immutable), OR only the owner may grant the admin role",
        },
        404: {"model": ErrorDetail, "description": "No user matches this id"},
        422: {"model": ErrorDetail, "description": "role is not one of the valid values"},
    },
)
async def update_user_role(
    user_id: int,
    payload: RoleUpdateIn,
    current_user=Depends(require_admin),  # noqa: ANN001 - Row, admin-only
    session: AsyncSession = Depends(get_session),
) -> RoleUpdateOut:
    """Promotes/demotes a user between `contributor`/`moderator`/`admin`.
    Admin (or owner) only, with two further owner-tier restrictions
    enforced by the service layer regardless of caller role (#28,
    CLAUDE.md): the owner's own row can never be changed through this
    endpoint by anyone, and only the owner can grant the `admin` role
    itself (a plain admin can still promote/demote between `contributor`
    and `moderator`). `role` deliberately excludes `'owner'` as a valid
    value — it is set once at bootstrap and never assignable here.
    """
    # NOT session.begin() at this level either — require_admin's
    # get_current_user already autobegan a transaction on this session
    # (see services/admin.py's own note on the same fix). Commit
    # explicitly after the service's writes, same pattern as #12/#13.
    result = await admin_service.update_role(
        session,
        target_user_id=user_id,
        new_role=payload.role,
        changed_by_user_id=current_user.id,
        changed_by_role=current_user.role,
    )
    await session.commit()
    return result


@router.patch(
    "/admin/users/{user_id}/suspension",
    response_model=SuspensionUpdateOut,
    responses={
        **_ADMIN_ONLY,
        403: {
            "model": ErrorDetail,
            "description": "Admin/owner access required, OR the target is the owner (immune to suspension)",
        },
        404: {"model": ErrorDetail, "description": "No user matches this id"},
    },
)
async def update_user_suspension(
    user_id: int,
    payload: SuspensionUpdateIn,
    current_user=Depends(require_admin),  # noqa: ANN001 - Row, admin-only
    session: AsyncSession = Depends(get_session),
) -> SuspensionUpdateOut:
    """#209: admin/owner-only account suspension — the enforcement half of
    the ToS (the other half is the `/tos` policy page itself). A suspended
    account is blocked from submitting contributions/series-proposals/
    synonym-suggestions and from voting (core/deps.py's
    ensure_not_suspended/require_active_user), but NOT from reading or
    from exercising GDPR rights on their own account (GET /users/me,
    GET /users/me/export, DELETE /users/me all stay unaffected — this is
    account-conduct enforcement, not a way to strip someone's own data
    rights). The owner's own row is immune, same as role changes.
    """
    result = await admin_service.update_suspension(
        session, target_user_id=user_id, suspended=payload.suspended, reason=payload.reason
    )
    await session.commit()
    return result


@router.get(
    "/admin/vote-clustering-report",
    response_model=VoteClusteringReportOut,
    responses={
        401: {"model": ErrorDetail, "description": "Not authenticated"},
        403: {"model": ErrorDetail, "description": "Moderator, admin, or owner role required"},
    },
)
async def vote_clustering_report(
    min_reciprocal_count: int = Query(default=2, ge=1, le=100),
    limit: int = Query(default=50, ge=1, le=200),
    current_user=Depends(require_moderator),  # noqa: ANN001 - Row, moderator/admin/owner
    session: AsyncSession = Depends(get_session),
) -> VoteClusteringReportOut:
    """#203: the Sybil-monitoring tripwire named as an explicit open item
    in CLAUDE.md's #14 decision record — surfaces pairs of accounts that
    have repeatedly endorsed EACH OTHER's pending contributions, the
    cheapest concrete signal of two colluding accounts combining
    `trust_score` weight to auto-approve each other with no moderator
    click needed. Not automated anomaly detection or blocking — still
    explicitly deferred per the #14 decision, unchanged here — a
    moderator (or admin/owner) runs this periodically and reviews the
    flagged pairs by hand, same "manual is fine for v1" pattern as #23's
    canary/log-review approach. Moderator-accessible (not admin-only, the
    only endpoint on this router that isn't) since moderators are this
    project's day-to-day abuse-watchers. `min_reciprocal_count` (default
    2) is a starting heuristic, not tuned against real abuse data — a
    single mutual endorsement is common and innocuous in a small
    community; repeated mutual endorsement is the actual signal worth a
    human look.
    """
    return await admin_service.get_vote_clustering_report(session, min_reciprocal_count, limit)
