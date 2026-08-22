from datetime import datetime

from pydantic import BaseModel


class SeriesOut(BaseModel):
    id: int
    anilist_id: int | None
    mal_id: int | None
    anidb_id: int | None
    title: str
    provenance: str
    created_at: datetime


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
