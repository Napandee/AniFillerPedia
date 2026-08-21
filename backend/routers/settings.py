"""Account-linking initiation — deliberately its own route, separate from
ordinary login (CLAUDE.md Guardrails), and authenticated-only. The shared
/auth/{provider}/callback route (routers/auth.py) tells linking apart from
login purely via the signed state's link_user_id, not a different path,
since the redirect back from the provider is identical either way.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.engine import Row

from core.deps import get_current_user
from routers.auth import _start_oauth_redirect

router = APIRouter(tags=["settings"])


@router.get("/settings/link/{provider}")
async def start_link(provider: str, current_user: Row = Depends(get_current_user)) -> RedirectResponse:
    return _start_oauth_redirect(provider, link_user_id=current_user.id)
