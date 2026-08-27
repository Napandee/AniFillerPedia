from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.export as export_repo
import repositories.rate_limits as rate_limits_repo
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

# #141: this endpoint has no auth of its own (by design — it's how anyone
# first gets an export API key) and nothing verifies the submitted email
# is actually reachable, so nothing previously stopped mass key generation.
# 5 per rolling hour per caller comfortably covers a real person retrying
# a typo'd email a couple of times, while bounding automated key-farming.
# Not a tuned number — same "no real abuse data yet" stance as #84/#139's
# other new limits.
EXPORT_ACCESS_RATE_LIMIT = 5
EXPORT_ACCESS_RATE_LIMIT_WINDOW_SECONDS = 60 * 60
EXPORT_ACCESS_RATE_LIMIT_SCOPE = "export_request_access"


async def request_access(
    session: AsyncSession, *, email: str, license_accepted: bool, identifier: str
) -> ExportAccessResponse:
    if not license_accepted:
        raise HTTPException(
            status_code=400,
            detail="license_accepted must be true to receive an export API key",
        )

    recent_count = await rate_limits_repo.count_recent(
        session,
        scope=EXPORT_ACCESS_RATE_LIMIT_SCOPE,
        identifier=identifier,
        window_seconds=EXPORT_ACCESS_RATE_LIMIT_WINDOW_SECONDS,
    )
    if recent_count >= EXPORT_ACCESS_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've requested {recent_count} export API keys in the last hour "
                f"(limit {EXPORT_ACCESS_RATE_LIMIT}). Try again later."
            ),
        )

    key = generate_api_key()
    await export_repo.insert_api_key_request(
        session,
        email=email,
        license_accepted=license_accepted,
        terms_version=CURRENT_TERMS_VERSION,
        key_hash=hash_api_key(key),
    )
    await rate_limits_repo.record(session, scope=EXPORT_ACCESS_RATE_LIMIT_SCOPE, identifier=identifier)
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
