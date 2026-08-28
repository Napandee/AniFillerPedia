from fastapi import APIRouter, Depends, Response
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.admin as admin_repo
import repositories.users as users_repo
from core.db import get_session
from core.deps import get_current_user
from core.security import SESSION_COOKIE_NAME
from schemas.auth import UserOut
from schemas.errors import ErrorDetail
from services.admin import compute_trust_score

router = APIRouter(tags=["users"])

_NOT_AUTHENTICATED = {401: {"model": ErrorDetail, "description": "Not authenticated"}}


@router.get("/users/me", response_model=UserOut, responses=_NOT_AUTHENTICATED)
async def read_current_user(
    current_user: Row = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    """The signed-in caller's own profile, including #43's `trust_score`
    (the same formula #14's community voting weights votes by) — not
    available for any other user via this endpoint; see
    `GET /admin/users` for the admin-only listing of everyone's.
    """
    # #43: same per-user stats query #14 already added for vote-weight
    # lookups (repositories/admin.py's get_user_stats) — reused here rather
    # than a second implementation of the same aggregate.
    stats = await admin_repo.get_user_stats(session, current_user.id)
    approved_count = stats.approved_count if stats else 0
    rejected_count = stats.rejected_count if stats else 0
    return UserOut(
        id=current_user.id,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
        role=current_user.role,
        approved_count=approved_count,
        rejected_count=rejected_count,
        trust_score=compute_trust_score(approved_count, rejected_count),
    )


@router.delete("/users/me", status_code=204, responses=_NOT_AUTHENTICATED)
async def delete_current_user(
    response: Response,
    current_user: Row = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """#29/#18: self-service account deletion, no admin approval gate.
    Every FK referencing users is ON DELETE SET NULL (schema.sql) — past
    contributions/votes/citations anonymize automatically, nothing else to
    clean up here. NOT `async with session.begin():` — get_current_user's
    SELECT already autobegan a transaction on this session (the same fix
    noted throughout this codebase, e.g. routers/contributions.py).
    """
    await users_repo.delete_user(session, current_user.id)
    await session.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
