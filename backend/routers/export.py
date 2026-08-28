from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

import services.export as export_service
from core.db import get_session
from core.deps import get_rate_limit_identifier
from schemas.contributions import BulkSubmissionRateLimited
from schemas.errors import ErrorDetail
from schemas.export import ExportAccessRequest, ExportAccessResponse, ExportOut

router = APIRouter(tags=["export"])

_MISSING_OR_INVALID_KEY = {
    401: {"model": ErrorDetail, "description": "Missing or invalid/revoked X-API-Key header"}
}


@router.post(
    "/export/request-access",
    response_model=ExportAccessResponse,
    responses={
        400: {"model": ErrorDetail, "description": "license_accepted was not true"},
        429: {"model": BulkSubmissionRateLimited},
    },
)
async def request_export_access(
    body: ExportAccessRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ExportAccessResponse:
    """Issues a new `/export` API key. No auth of its own — this is how
    anyone first gets a key — so it's rate-limited purely by IP rather than
    by an account. `license_accepted` must be true; the returned key is
    shown exactly once and can't be retrieved again (see the response's
    own `note` field).
    """
    # #141: no auth exists on this endpoint by design (it's how anyone
    # first gets a key) — rate-limited purely by IP, there's no logged-in
    # caller concept here the way get_rate_limit_identifier's user-id
    # branch would apply.
    identifier = get_rate_limit_identifier(request, None)
    return await export_service.request_access(
        session,
        email=body.email,
        license_accepted=body.license_accepted,
        identifier=identifier,
    )


@router.get("/export", response_model=ExportOut, responses=_MISSING_OR_INVALID_KEY)
async def get_export(
    x_api_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ExportOut:
    """The one non-public endpoint in the read API — a full dataset dump
    (every series and episode) plus an embedded attribution manifest, since
    a downloaded file is disconnected from these live docs. Requires the
    `X-API-Key` header, obtained from `POST /export/request-access`.
    """
    await export_service.validate_api_key(session, x_api_key)
    return await export_service.build_export(session)


@router.post(
    "/export/revoke",
    status_code=204,
    responses={
        401: {"model": ErrorDetail, "description": "Missing X-API-Key header"},
        404: {"model": ErrorDetail, "description": "Unknown API key"},
    },
)
async def revoke_export_access(
    x_api_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Self-service revoke-and-forget for the email collected at
    /export/request-access — see services/export.py for why possessing
    the key is sufficient identity to act on this record.
    """
    await export_service.revoke_and_forget(session, x_api_key)
