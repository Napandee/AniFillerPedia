from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_oauth_state,
    create_session_token,
    verify_oauth_state,
)
from services.auth import AccountLinkConflict, Profile, link_provider_to_current_user, login_or_create_user
from services.oauth_providers import (
    exchange_code_for_token,
    fetch_provider_profile,
    get_provider_config,
    normalize_profile,
    redirect_uri_for,
)

router = APIRouter(tags=["auth"])

_VALID_PROVIDERS = {"github", "discord"}


def _require_valid_provider(provider: str) -> None:
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown provider")


def _safe_next_path(next: str | None) -> str | None:
    """Only ever a same-site relative path — never an open redirect. A
    bare "/" is fine; "//evil.com" and "https://evil.com" are not (both
    are browser-followed off-site redirects despite "starting with /").
    """
    if next and next.startswith("/") and not next.startswith("//"):
        return next
    return None


def _start_oauth_redirect(provider: str, *, link_user_id: int | None, next: str | None = None) -> RedirectResponse:
    _require_valid_provider(provider)
    config = get_provider_config(provider)
    state = create_oauth_state(link_user_id=link_user_id, next=_safe_next_path(next))
    redirect = RedirectResponse(
        url=(
            f"{config.authorize_url}"
            f"?client_id={config.client_id}"
            f"&redirect_uri={redirect_uri_for(provider)}"
            f"&scope={config.scope}"
            f"&state={state}"
            f"&response_type=code"
        )
    )
    # Bound to this browser, short-lived — the callback checks the state
    # query param against this cookie, not just that the state is validly
    # signed. Signature alone doesn't stop an attacker who legitimately
    # starts their own flow to obtain a validly-signed state, then tricks
    # a victim into completing it (session-fixation-style OAuth CSRF);
    # binding to a cookie the attacker can't set on the victim's browser
    # closes that gap.
    redirect.set_cookie(
        OAUTH_STATE_COOKIE_NAME, state, max_age=600, httponly=True, samesite="lax", secure=True
    )
    return redirect


@router.get("/auth/{provider}/authorize")
async def authorize(provider: str, next: str | None = Query(default=None)) -> RedirectResponse:
    return _start_oauth_redirect(provider, link_user_id=None, next=next)


@router.get("/auth/{provider}/callback", response_model=None)
async def callback(
    provider: str,
    response: Response,
    code: str = Query(...),
    state: str = Query(...),
    afp_oauth_state: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    session: AsyncSession = Depends(get_session),
) -> dict | RedirectResponse:
    _require_valid_provider(provider)

    # The state param must both (a) be validly signed by us and (b) match
    # the cookie set at /authorize time on THIS browser — see the comment
    # on _start_oauth_redirect for why the cookie check is load-bearing,
    # not redundant with the signature check.
    if afp_oauth_state is None or state != afp_oauth_state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="state mismatch")
    state_data = verify_oauth_state(state)
    if state_data is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired state")
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME)

    config = get_provider_config(provider)
    access_token = await exchange_code_for_token(config, code)
    raw_profile = await fetch_provider_profile(config, access_token)
    normalized = normalize_profile(provider, raw_profile)
    profile = Profile(**normalized)

    # get_session() doesn't auto-commit (core/db.py) — every write here
    # needs an explicit transaction or it silently rolls back when the
    # request's session closes. Real bug, caught by an actual end-to-end
    # test: the callback's own response looked correct because it read
    # the row back inside the same still-open transaction, but nothing
    # outside that one request would ever have seen it.
    # #37: when the frontend's login/link link included a `next` (a real
    # browser page to land on afterward), redirect there. When it's absent
    # — the original contract, still exercised by
    # test_full_login_round_trip_with_mocked_provider — keep returning the
    # plain JSON body exactly as before. Purely additive: nothing that
    # doesn't pass `next` observes any behavior change.
    next_path = state_data.get("next")

    link_user_id = state_data.get("link_user_id")
    if link_user_id is not None:
        try:
            async with session.begin():
                await link_provider_to_current_user(
                    session, current_user_id=link_user_id, provider=provider, profile=profile
                )
        except AccountLinkConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if next_path:
            return RedirectResponse(url=next_path, status_code=status.HTTP_303_SEE_OTHER)
        return {"linked": provider}

    async with session.begin():
        user = await login_or_create_user(session, provider, profile)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user.id),
        httponly=True,
        samesite="lax",
        secure=True,
        # Explicit, not relying on a library default: without it, a
        # cookie set from /api/v1/auth/github/callback risks being scoped
        # only to that path's "directory" per RFC 6265 (i.e. never sent
        # for /api/v1/users/me or anything else) rather than the whole
        # site. Caught by the real end-to-end test, not by inspection.
        path="/",
    )
    if next_path:
        return RedirectResponse(url=next_path, status_code=status.HTTP_303_SEE_OTHER)
    return {"id": user.id, "display_name": user.display_name, "role": user.role}


@router.post("/auth/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"logged_out": True}
