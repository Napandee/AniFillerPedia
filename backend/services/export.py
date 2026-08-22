from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.export as export_repo
from core.security import generate_api_key, hash_api_key
from schemas.export import (
    ExportAccessResponse,
    ExportEpisodeOut,
    ExportManifest,
    ExportOut,
    ExportSeriesOut,
)

# Bumped only if the license terms materially change — lets a stored
# acceptance record be checked against what the requester actually agreed
# to, per #22's acceptance criteria ("what terms version" queryable).
CURRENT_TERMS_VERSION = "cc-by-nc-sa-4.0-2026-08-21"


async def request_access(
    session: AsyncSession, *, email: str, license_accepted: bool
) -> ExportAccessResponse:
    if not license_accepted:
        raise HTTPException(
            status_code=400,
            detail="license_accepted must be true to receive an export API key",
        )
    key = generate_api_key()
    await export_repo.insert_api_key_request(
        session,
        email=email,
        license_accepted=license_accepted,
        terms_version=CURRENT_TERMS_VERSION,
        key_hash=hash_api_key(key),
    )
    await session.commit()
    return ExportAccessResponse(api_key=key)


async def validate_api_key(session: AsyncSession, key: str | None) -> None:
    if not key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    record = await export_repo.get_valid_key_record(session, hash_api_key(key))
    if record is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")


async def revoke_and_forget(session: AsyncSession, key: str | None) -> None:
    """Self-service counterpart to #29's account deletion, for the one
    other place this project stores an email: possessing the key is the
    only proof of identity needed, same as using it to call /export at
    all. Revoking an already-revoked key succeeds again (the caller's
    actual goal — key dead, email gone — is already true); only a key
    that never existed 404s.
    """
    if not key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    found = await export_repo.revoke_and_forget(session, hash_api_key(key))
    if not found:
        raise HTTPException(status_code=404, detail="Unknown API key")
    await session.commit()


async def build_export(session: AsyncSession) -> ExportOut:
    rows = await export_repo.fetch_full_dataset(session)

    series_by_id: dict[int, ExportSeriesOut] = {}
    for row in rows:
        series = series_by_id.get(row.series_id)
        if series is None:
            series = ExportSeriesOut(
                series_id=row.series_id,
                anilist_id=row.anilist_id,
                mal_id=row.mal_id,
                anidb_id=row.anidb_id,
                title=row.series_title,
                provenance=row.provenance,
                episodes=[],
            )
            series_by_id[row.series_id] = series
        if row.episode_id is not None:
            series.episodes.append(
                ExportEpisodeOut(
                    episode_id=row.episode_id,
                    episode_number=row.episode_number,
                    status=row.status,
                    status_note=row.status_note,
                    citation_url=row.citation_url,
                    citation_description=row.citation_description,
                )
            )

    return ExportOut(manifest=ExportManifest(), series=list(series_by_id.values()))
