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


class SeriesListOut(BaseModel):
    items: list[SeriesOut]
    total: int
    limit: int
    offset: int
