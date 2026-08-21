from fastapi import FastAPI

from routers import health

app = FastAPI(title="AniFillerPedia API", version="0.1.0")

app.include_router(health.router, prefix="/api/v1")
