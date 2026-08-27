from pydantic import BaseModel, EmailStr


class ExportAccessRequest(BaseModel):
    # #141: was a bare `str` — nothing stopped a junk string or someone
    # else's real address from being recorded as having "agreed" to the
    # license terms. EmailStr (via the `email-validator` dependency)
    # rejects anything that isn't a real email shape; it can't verify the
    # address is actually reachable/owned by the requester, which is fine
    # — the key is returned directly in the response, never emailed (see
    # ExportAccessResponse's own note), so this is about data-quality on
    # export_api_keys.email, not proving inbox ownership.
    email: EmailStr
    license_accepted: bool


class ExportAccessResponse(BaseModel):
    api_key: str
    note: str = (
        "This key is shown once and cannot be retrieved again. "
        "Store it securely; request a new one via /export/request-access "
        "if lost."
    )


class ExportEpisodeOut(BaseModel):
    episode_id: int | None
    episode_number: int | None
    status: str | None
    status_note: str | None
    citation_url: str | None
    citation_description: str | None


class ExportSeriesOut(BaseModel):
    series_id: int
    anilist_id: int | None
    mal_id: int | None
    anidb_id: int | None
    title: str
    provenance: str
    episodes: list[ExportEpisodeOut]


class ExportManifest(BaseModel):
    license: str = "CC BY-NC-SA 4.0"
    attribution_notice: str = (
        "Contains information from AniFillerPedia, which is made available "
        "here under CC BY-NC-SA 4.0 (non-commercial use; contact us for a "
        "commercial license)."
    )
    commercial_licensing_contact: str = (
        "See https://github.com/Napandee/AniFillerPedia DATA_LICENSE for "
        "the current commercial-licensing contact channel."
    )
    dataset_license_url: str = (
        "https://github.com/Napandee/AniFillerPedia/blob/master/DATA_LICENSE"
    )


class ExportOut(BaseModel):
    manifest: ExportManifest
    series: list[ExportSeriesOut]
