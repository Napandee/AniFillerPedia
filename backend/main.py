import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.version import API_VERSION
from routers import admin, auth, contributions, episodes, export, health, legal, series, series_proposals, settings, users
from services.alerting import alert_unhandled_exception

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AniFillerPedia API",
    version=API_VERSION,
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
