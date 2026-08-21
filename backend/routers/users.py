from fastapi import APIRouter, Depends
from sqlalchemy.engine import Row

from core.deps import get_current_user
from schemas.auth import UserOut

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=UserOut)
async def read_current_user(current_user: Row = Depends(get_current_user)) -> Row:
    return current_user
