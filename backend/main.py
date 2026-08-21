from fastapi import FastAPI

from core.version import API_VERSION
from routers import auth, episodes, health, legal, series, settings, users

app = FastAPI(title="AniFillerPedia API", version=API_VERSION)

app.include_router(health.router, prefix="/api/v1")
app.include_router(series.router, prefix="/api/v1")
app.include_router(episodes.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(legal.router, prefix="/api/v1")
