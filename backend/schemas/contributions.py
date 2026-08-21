from datetime import datetime

from pydantic import BaseModel, Field

from schemas.episodes import CitationOut


class CitationIn(BaseModel):
    url: str | None = None
    description: str = Field(min_length=1)


class ContributionCreate(BaseModel):
    series_id: int
    episode_number: int
    proposed_status: str = Field(pattern="^(canon|filler|mixed)$")
    proposed_note: str | None = None
    citation: CitationIn
    # Required true, not just present — #21: structural proof of agreement
    # on every submission, anonymous or not.
    license_accepted: bool
    # Structurally ready, not live-verified (no Turnstile site key
    # configured yet — see #25/CLAUDE.local.md). Optional for now so the
    # endpoint doesn't hard-fail before a real site key exists; becomes
    # required once services/turnstile.py's verify() has something real to
    # check against.
    turnstile_token: str | None = None


class ContributionOut(BaseModel):
    id: int
    series_id: int
    episode_number: int
    proposed_status: str
    proposed_note: str | None
    citation: CitationOut
    submitted_at: datetime
    review_status: str
    resolution_method: str | None
    reviewed_at: datetime | None
    review_note: str | None


class DuplicatePendingContributionDetail(BaseModel):
    message: str
    existing_contribution_id: int


class DuplicatePendingContribution(BaseModel):
    """409 response body when #20's one-pending-per-episode rule rejects a
    submission — points the caller at the existing pending contribution so
    a client can offer "endorse/dispute this instead" rather than a dead
    end. Nested under `detail` to match what FastAPI's HTTPException
    actually produces, not a guessed flat shape.
    """

    detail: DuplicatePendingContributionDetail


class UserRef(BaseModel):
    """Public identity — usernames visible per CLAUDE.md's decision to keep
    contribution history non-anonymized. Absent (None) covers both a
    genuinely anonymous submission and an anonymized-by-deletion account —
    those look identical on purpose (schema.sql: ON DELETE SET NULL exists
    specifically so deletion can't be told apart from anonymity after the
    fact).
    """

    id: int
    display_name: str | None
    github_id: str | None


class VoteOut(BaseModel):
    voter: UserRef | None
    vote: str
    weight_at_vote: int
    created_at: datetime


class ContributionHistoryEntry(BaseModel):
    id: int
    proposed_status: str
    proposed_note: str | None
    citation: CitationOut
    submitted_by: UserRef | None
    submitted_at: datetime
    review_status: str
    resolution_method: str | None
    reviewed_by: UserRef | None
    reviewed_at: datetime | None
    review_note: str | None
    votes: list[VoteOut]
