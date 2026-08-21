from datetime import datetime

from pydantic import BaseModel


class CitationOut(BaseModel):
    id: int
    url: str | None
    description: str


class EpisodeOut(BaseModel):
    id: int
    series_id: int
    episode_number: int
    status: str
    status_note: str | None
    citation: CitationOut
    updated_at: datetime
