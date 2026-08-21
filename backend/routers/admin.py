from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

import services.admin as admin_service
from core.db import get_session
from core.deps import require_admin
from schemas.admin import AdminUserListOut, RoleUpdateIn

router = APIRouter(tags=["admin"])


@router.get("/admin/users", response_model=AdminUserListOut)
async def list_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(require_admin),  # noqa: ANN001 - Row, admin-only
    session: AsyncSession = Depends(get_session),
) -> AdminUserListOut:
    return await admin_service.list_users(session, limit, offset)


@router.patch("/admin/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    payload: RoleUpdateIn,
    current_user=Depends(require_admin),  # noqa: ANN001 - Row, admin-only
    session: AsyncSession = Depends(get_session),
) -> dict:
    # NOT session.begin() at this level either — require_admin's
    # get_current_user already autobegan a transaction on this session
    # (see services/admin.py's own note on the same fix). Commit
    # explicitly after the service's writes, same pattern as #12/#13.
    result = await admin_service.update_role(
        session, target_user_id=user_id, new_role=payload.role, changed_by_user_id=current_user.id
    )
    await session.commit()
    return result
