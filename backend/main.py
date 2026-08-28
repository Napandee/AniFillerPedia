import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.version import API_VERSION
from routers import (
    admin,
    anilist_lookup,
    auth,
    contributions,
    episodes,
    export,
    health,
    legal,
    series,
    series_proposals,
    settings,
    synonym_suggestions,
    users,
)
from services.alerting import alert_unhandled_exception

logger = logging.getLogger(__name__)

# #138: route grouping for /docs — one entry per router module, in the
# same order routers are mounted below, plus health/legal/settings/
# anilist-lookup which don't get their own subsection elsewhere in this
# file. Descriptions are deliberately short (a sentence or two); the real
# depth lives in each route's own docstring, docs/API.md, and
# CONTRIBUTING.md, not duplicated here.
openapi_tags = [
    {
        "name": "series",
        "description": "Public, unauthenticated reads of the series catalog — search, "
        "detail (by id or slug), and per-series episode lists. See docs/API.md.",
    },
    {
        "name": "episodes",
        "description": "Public, unauthenticated reads of a single episode and its full "
        "contribution/review history.",
    },
    {
        "name": "contributions",
        "description": "Submit and review per-episode filler/canon/mixed corrections — "
        "single-episode and bulk-range submission, moderator approve/reject, and "
        "community trust-weighted voting. See CONTRIBUTING.md.",
    },
    {
        "name": "series-proposals",
        "description": "Propose a series that isn't in the catalog yet (optionally with "
        "attached bulk episode data), and the moderator approve/reject flow for it. "
        "Mirrors the contributions workflow above.",
    },
    {
        "name": "synonym-suggestions",
        "description": "Suggest an alternate/dub/regional title for an already-catalogued "
        "series, and the moderator approve/reject flow for it (#148). Moderator-only "
        "approval, not community voting — see services/synonym_suggestions.py for why.",
    },
    {
        "name": "admin",
        "description": "Admin/owner-only user and role management. Not moderation — see "
        "the contributions/series-proposals routers for the approval queue.",
    },
    {
        "name": "auth",
        "description": "Cookie-based OAuth login (GitHub, Discord) — the redirect-based "
        "flow a browser drives. See docs/API.md's Authentication section for what a "
        "non-browser (server-to-server) caller can and can't do here.",
    },
    {
        "name": "settings",
        "description": "Authenticated account settings — currently just linking an "
        "additional OAuth provider to an already-signed-in account.",
    },
    {
        "name": "users",
        "description": "The signed-in caller's own account — profile/trust-score read, "
        "self-service GDPR deletion.",
    },
    {
        "name": "export",
        "description": "The bulk dataset dump — the one part of this API that isn't "
        "fully open, since a silent anonymous bulk download has weaker license-"
        "agreement standing than a click-through API-key request does.",
    },
    {
        "name": "legal",
        "description": "Static/structured legal pages — privacy policy and the dataset's "
        "CC BY-NC-SA license + attribution/commercial-contact details.",
    },
    {
        "name": "anilist-lookup",
        "description": "A thin, rate-limited proxy to AniList's own public GraphQL API, "
        "used by submission forms to pre-fill a title from an AniList id.",
    },
    {
        "name": "health",
        "description": "Liveness/version check — no auth, no dependencies.",
    },
]

app = FastAPI(
    title="AniFillerPedia API",
    version=API_VERSION,
    description=(
        "Public read API for AniFillerPedia, a community-editable database of "
        "anime filler/canon/mixed episode data. Every read endpoint (series, "
        "episodes, citations, contribution history) is public and unauthenticated "
        "— no account, no API key, no rate-limit wall for reasonable use. Only "
        "the bulk `/export` dump requires an API key, and only write endpoints "
        "that need an accountable identity (voting, bulk submission, moderation, "
        "admin) require login.\n\n"
        "Auth is cookie-based OAuth (GitHub/Discord) with no bearer-token "
        "alternative today — see the Authentication section of "
        "[docs/API.md](https://github.com/Napandee/AniFillerPedia/blob/master/docs/API.md#authentication) "
        "before building a non-browser client against a login-gated endpoint.\n\n"
        "See [docs/API.md](https://github.com/Napandee/AniFillerPedia/blob/master/docs/API.md) "
        "for a narrative guide with real example requests, and "
        "[CONTRIBUTING.md](https://github.com/Napandee/AniFillerPedia/blob/master/CONTRIBUTING.md) "
        "for how the submission/review/voting workflow fits together."
    ),
    openapi_tags=openapi_tags,
    # #21: code is MIT, but the DATASET this API serves is CC BY-NC-SA
    # 4.0 with a non-commercial restriction — a plain "MIT" here would be
    # actively misleading about what a consumer may do with the data
    # returned by these endpoints. See GET /api/v1/license for the full,
    # structured version of this same fact.
    license_info={
        "name": "Code: MIT — Dataset: CC BY-NC-SA 4.0 (see GET /api/v1/license)",
        "url": "https://github.com/Napandee/AniFillerPedia/blob/master/DATA_LICENSE",
    },
)

# #142: no CORSMiddleware here — a deliberate decision to leave CORS
# unconfigured for now, not an oversight. Nothing today needs it: the
# Astro frontend calls this API same-origin (Caddy splits /api/v1/* to
# this container on the same domain, never a browser-JS cross-origin
# call), auth is cookie-based session tokens (samesite=lax, httpOnly) —
# which wouldn't usefully support cross-origin browser calls without
# further work anyway — and the one speculative future consumer named in
# CLAUDE.md (a possible AniDex integration) would most plausibly be
# server-to-server, which CORS doesn't gate at all (it's a browser-
# enforced restriction; a server calling this API directly is unaffected
# either way). Revisit if a real browser-based third-party client shows
# up wanting cross-origin reads — see CLAUDE.md's Decisions Made for the
# full reasoning and what would justify reopening this.
app.include_router(health.router, prefix="/api/v1")
app.include_router(series.router, prefix="/api/v1")
app.include_router(episodes.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")
app.include_router(contributions.router, prefix="/api/v1")
app.include_router(series_proposals.router, prefix="/api/v1")
app.include_router(synonym_suggestions.router, prefix="/api/v1")
app.include_router(anilist_lookup.router, prefix="/api/v1")
app.include_router(legal.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


# #17: a genuine unhandled exception (a real 500) alerts via Telegram.
# Registering a handler for the bare `Exception` type only intercepts
# Starlette's ServerErrorMiddleware (the outermost layer, for anything
# that reaches it unhandled) — it does NOT shadow FastAPI's own default
# handlers for HTTPException/RequestValidationError (those are matched
# more specifically first), so intentional 404s/403s/422s the app already
# raises deliberately are completely unaffected by this.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception handling %s %s", request.method, request.url.path)
    # Fire-and-forget (asyncio.create_task, not awaited): a slow/failing
    # Telegram call must never turn one application error into a hung
    # response. See services/alerting.py's own docstring.
    asyncio.create_task(alert_unhandled_exception(f"{request.method} {request.url.path}", exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
