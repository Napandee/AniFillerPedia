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


class SeriesListOut(BaseModel):
    items: list[SeriesOut]
    total: int
    limit: int
    offset: int
