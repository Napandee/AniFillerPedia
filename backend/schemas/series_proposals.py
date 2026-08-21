from datetime import datetime

from pydantic import BaseModel, Field


class SeriesProposalCreate(BaseModel):
    title: str = Field(min_length=1)
    anilist_id: int | None = None
    mal_id: int | None = None
    anidb_id: int | None = None
    justification: str = Field(min_length=1)
    license_accepted: bool
    # Same structurally-ready-not-live-verified note as ContributionCreate.
    turnstile_token: str | None = None


class SeriesProposalOut(BaseModel):
    id: int
    title: str
    anilist_id: int | None
    mal_id: int | None
    anidb_id: int | None
    justification: str
    submitted_at: datetime
    review_status: str
    reviewed_at: datetime | None
    review_note: str | None
