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


async def require_moderator(current_user: Row = Depends(get_current_user)) -> Row:
    """#13: moderation endpoints (approve/reject) — moderator, admin, or
    owner. Each tier is a superset of the one below (CLAUDE.md/#27/owner
    tier decided 2026-08-21), so this single check covers all three rather
    than needing separate checks for anything moderation-shaped.
    """
    if current_user.role not in ("moderator", "admin", "owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="moderator, admin, or owner role required")
    return current_user


async def require_admin(current_user: Row = Depends(get_current_user)) -> Row:
    """#27: admin tier is strictly above moderator, not just "logged in"
    — a moderator hitting an admin-only route should get a real 403, not
    silently succeed because it only checked for authentication. Owner is
    a superset of admin (decided 2026-08-21) — an owner passes this check
    too; the one thing owner adds beyond plain admin (granting the admin
    role itself, and immunity from role changes) is enforced separately in
    services/admin.py's update_role(), not by a stricter version of this
    dependency.
    """
    if current_user.role not in ("admin", "owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin or owner access required")
    return current_user


def get_rate_limit_identifier(request: Request, current_user: Row | None) -> str:
    """#139/#141: identity to key a rate-limit counter against, for the
    anonymous-accessible write endpoints (POST /contributions,
    POST /series-proposals, POST /export/request-access) — the caller's
    own user id when authenticated (so a shared NAT/proxy IP never lumps
    distinct logged-in callers into one bucket), the remote IP otherwise.
    Relies on the Dockerfile's `--proxy-headers` uvicorn flag so
    `request.client.host` reflects the real client IP behind Caddy, not
    the proxy's own address. #185: the actual integrity of that value
    comes from the Caddyfile's `trusted_proxies` global option (which
    stops a client-supplied X-Forwarded-For from being trusted unless it
    genuinely arrived via a trusted upstream hop) plus this Dockerfile's
    `--forwarded-allow-ips` being scoped to the docker-compose network's
    private range rather than `*` — before that fix, a caller could set
    an arbitrary X-Forwarded-For and have it trusted verbatim here,
    trivially defeating every IP-keyed limit below. See repositories/
    rate_limits.py for what this identifier is actually counted against.
    """
    if current_user is not None:
        return f"user:{current_user.id}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


async def require_owner(current_user: Row = Depends(get_current_user)) -> Row:
    """Owner-only tier (decided 2026-08-21, CLAUDE.md) — strictly above
    admin, and structurally unreachable via the role-promotion endpoint
    (repositories/admin.py's VALID_ROLES excludes 'owner' entirely; it is
    set once at bootstrap, see services/auth.py). Not yet bound to any
    route of its own — added alongside require_moderator/require_admin as
    the same reusable primitive, for Phase 5's owner-only surfaces (and
    services/admin.py's inline admin-granting check) to depend on.
    """
    if current_user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner access required")
    return current_user
