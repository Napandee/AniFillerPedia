from fastapi import FastAPI

from core.version import API_VERSION
from routers import episodes, health, series

app = FastAPI(title="AniFillerPedia API", version=API_VERSION)

app.include_router(health.router, prefix="/api/v1")
app.include_router(series.router, prefix="/api/v1")
app.include_router(episodes.router, prefix="/api/v1")
