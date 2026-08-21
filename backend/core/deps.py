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
