from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SeriesOut(BaseModel):
    # Fields with a validation_alias otherwise only accept that alias as
    # input — populate_by_name lets **row._mapping (raw SQL column names)
    # and a plain keyword construction (e.g. in tests) both keep working.
    model_config = ConfigDict(populate_by_name=True)

    id: int
    anilist_id: int | None
    mal_id: int | None
    anidb_id: int | None
    title: str
    provenance: str
    created_at: datetime
    # #46 follow-up (2026-08-22): synced by #49's worker on a daily cadence,
    # not fetched live from AniList per-request — a real AniList outage
    # previously took down cover art site-wide since it used to be a
    # synchronous third-party dependency on every page load. Null until
    # the sync worker has reached this series at least once.
    cover_image_url: str | None = Field(validation_alias="anilist_cover_url")
    banner_image_url: str | None = Field(validation_alias="anilist_banner_url")
    # #111: AniList's own MediaStatus enum (FINISHED, RELEASING,
    # NOT_YET_RELEASED, CANCELLED, HIATUS), synced by #49's daily worker —
    # same null-until-first-sync convention as the cover/banner URLs above.
    # Surfaces whether a series is still airing, not yet aired, or done.
    airing_status: str | None = Field(validation_alias="anilist_status")


class SeriesDetailOut(SeriesOut):
    synonyms: list[str]
    # #49's AniList sync — the real total episode count, independent of how
    # many of them have actually been hand-researched (episodes.py's own
    # count). Null until #49's worker has synced this series at least once.
    anilist_episode_count: int | None
    # Lightweight links to other catalog entries covering the same show
    # split across multiple real AniList entries (e.g. Fairy Tail /
    # Fairy Tail (2014) / Fairy Tail (2018)) — see series_relations in
    # schema.sql. Empty for the vast majority of series.
    related_series: list[SeriesOut]


class SeriesListOut(BaseModel):
    items: list[SeriesOut]
    total: int
    limit: int
    offset: int
