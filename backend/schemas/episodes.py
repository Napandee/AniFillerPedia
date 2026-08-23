from datetime import datetime

from pydantic import BaseModel


class CitationOut(BaseModel):
    id: int
    url: str | None
    description: str
    # #74: how many independent sources agree with this citation's status —
    # defaulted rather than required so the existing call sites that build
    # a fresh single-source citation (contribution submission, pending/
    # history views) don't need touching; only the episode endpoints below
    # populate the real value from the `citations` row.
    source_count: int = 1


class EpisodeOut(BaseModel):
    id: int
    series_id: int
    episode_number: int
    status: str
    status_note: str | None
    # #73: reopens #33's "skip for v1" decision — nullable, most episodes
    # won't have one for a long time. Render "Episode #N" when null, never
    # blank.
    title: str | None
    citation: CitationOut
    updated_at: datetime
    # #49's AniList sync (series_episode_schedule) — null whenever that
    # sync hasn't covered this episode yet, which is common for an already-
    # finished long-running show (AniList's own schedule data only retains
    # a rolling window, not a full historical archive — see #49). Frontend
    # must render this as "unknown," never assume it's always present.
    aired_at: datetime | None
