from datetime import datetime

from pydantic import BaseModel

from schemas.episodes import CitationOut


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
