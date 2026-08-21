"""FastAPI dependencies shared across routers — currently just
"who is the logged-in user," read from the signed session cookie.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security import SESSION_COOKIE_NAME, verify_session_token
from repositories.users import find_by_id


async def get_current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Row:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user = await find_by_id(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user


async def get_current_user_optional(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Row | None:
    """Same lookup as get_current_user, but never raises — for endpoints
    that accept anonymous requests (#12) and only want to attribute a
    submission when the caller happens to be logged in, not require it.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    if user_id is None:
        return None
    return await find_by_id(session, user_id)


async def require_admin(current_user: Row = Depends(get_current_user)) -> Row:
    """#27: admin tier is strictly above moderator, not just "logged in"
    — a moderator hitting an admin-only route should get a real 403, not
    silently succeed because it only checked for authentication.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin access required")
    return current_user
