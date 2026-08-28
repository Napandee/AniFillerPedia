"""Account-linking initiation — deliberately its own route, separate from
ordinary login (CLAUDE.md Guardrails), and authenticated-only. The shared
/auth/{provider}/callback route (routers/auth.py) tells linking apart from
login purely via the signed state's link_user_id, not a different path,
since the redirect back from the provider is identical either way.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.engine import Row

from core.deps import get_current_user
from routers.auth import _start_oauth_redirect
from schemas.errors import ErrorDetail

router = APIRouter(tags=["settings"])


@router.get(
    "/settings/link/{provider}",
    responses={
        401: {"model": ErrorDetail, "description": "Not authenticated"},
        404: {"model": ErrorDetail, "description": "Unknown provider (must be github or discord)"},
    },
)
async def start_link(
    provider: str, current_user: Row = Depends(get_current_user), next: str | None = Query(default=None)
) -> RedirectResponse:
    """Starts the same OAuth redirect as `GET /auth/{provider}/authorize`,
    but for linking an additional provider to the CALLER's already-
    signed-in account rather than logging in — requires auth. Never
    auto-links by email match; this explicit, authenticated route is the
    only way an account gains a second linked provider (CLAUDE.md).
    """
    return _start_oauth_redirect(provider, link_user_id=current_user.id, next=next)
