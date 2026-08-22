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
    # #49's AniList sync (series_episode_schedule) — null whenever that
    # sync hasn't covered this episode yet, which is common for an already-
    # finished long-running show (AniList's own schedule data only retains
    # a rolling window, not a full historical archive — see #49). Frontend
    # must render this as "unknown," never assume it's always present.
    aired_at: datetime | None
