from pydantic import BaseModel


class ExportAccessRequest(BaseModel):
    email: str
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
