from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

import services.admin as admin_service
from core.db import get_session
from core.deps import require_admin
from schemas.admin import AdminUserListOut, RoleUpdateIn, RoleUpdateOut
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
