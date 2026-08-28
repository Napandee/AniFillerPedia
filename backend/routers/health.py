from fastapi import APIRouter

from core.version import API_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness check — no auth, no database dependency. Used by the
    deploy pipeline's post-deploy smoke test (pr-validate.yml) and by
    anything else that just needs to know the API process is up.
    """
    return {"status": "ok"}


@router.get("/version")
async def version() -> dict[str, str]:
    """The currently-deployed API version string."""
    return {"version": API_VERSION}
