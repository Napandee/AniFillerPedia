from fastapi import FastAPI

from core.version import API_VERSION
from routers import admin, auth, contributions, episodes, export, health, legal, series, series_proposals, settings, users

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
