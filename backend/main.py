from fastapi import FastAPI

from core.version import API_VERSION
from routers import health

app = FastAPI(title="AniFillerPedia API", version=API_VERSION)

app.include_router(health.router, prefix="/api/v1")
