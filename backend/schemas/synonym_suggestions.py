from datetime import datetime

from pydantic import BaseModel, Field


class SynonymSuggestionCreate(BaseModel):
    series_id: int
    # #140-style bound (schemas/contributions.py's own precedent) — a
    # synonym is a title, not a paragraph; 200 chars comfortably covers
    # any real alternate/dub/native-script title while still bounding the
    # storage-bloat vector an unbounded anonymous field would otherwise be.
    synonym: str = Field(min_length=1, max_length=200)
    # Optional context for the moderator (e.g. "official English dub
    # title on Crunchyroll") — not a required citation, matching
    # migrations/015's own reasoning for why this is lower-stakes than an
    # episode filler/canon claim.
    note: str | None = Field(default=None, max_length=500)
    # Required true, not just present — #21: structural proof of
    # agreement on every submission, anonymous or not, same as
    # contributions/series_proposals.
    license_accepted: bool
    # Structurally ready, not live-verified — same not-yet-provisioned
    # Turnstile site key as every other anonymous-accessible write
    # endpoint (see #25/CLAUDE.local.md).
    turnstile_token: str | None = None


class SynonymSuggestionOut(BaseModel):
    id: int
    series_id: int
    # Joined in at read time (repositories/synonym_suggestions.py's
    # list_pending) — a bare series_id is meaningless to a moderator
    # reviewing a queue of alternate titles with no other identifying
    # detail on the row.
    series_title: str | None = None
    series_slug: str | None = None
    synonym: str
    note: str | None
    submitted_at: datetime
    review_status: str
    reviewed_at: datetime | None
    review_note: str | None


class SynonymSuggestionReject(BaseModel):
    review_note: str = Field(min_length=1)


class SynonymSuggestionReviewOut(BaseModel):
    id: int
    review_status: str
    reviewed_at: datetime | None
    review_note: str | None


class DuplicatePendingSynonymSuggestionDetail(BaseModel):
    message: str
    existing_suggestion_id: int


class DuplicatePendingSynonymSuggestion(BaseModel):
    """409 response body when the one-pending-per-(series_id, synonym)
    rule (migrations/015) rejects a submission — points the caller at the
    existing pending suggestion, same precedent as contributions'
    DuplicatePendingContribution.
    """

    detail: DuplicatePendingSynonymSuggestionDetail
