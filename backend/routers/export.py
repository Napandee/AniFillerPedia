from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

import services.export as export_service
from core.db import get_session
from schemas.export import ExportAccessRequest, ExportAccessResponse, ExportOut

router = APIRouter(tags=["export"])


@router.post("/export/request-access", response_model=ExportAccessResponse)
async def request_export_access(
    body: ExportAccessRequest,
    session: AsyncSession = Depends(get_session),
) -> ExportAccessResponse:
    return await export_service.request_access(
        session, email=body.email, license_accepted=body.license_accepted
    )


@router.get("/export", response_model=ExportOut)
async def get_export(
    x_api_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ExportOut:
    await export_service.validate_api_key(session, x_api_key)
    return await export_service.build_export(session)
