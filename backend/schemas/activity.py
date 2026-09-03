from datetime import datetime

from pydantic import BaseModel


class ActivityFeedItem(BaseModel):
    """#154: one resolved event in the public activity feed —
    either a `contribution` (an episode-level status proposal) or a
    `series_proposal` (a proposal to add a new series). Only ever a
    *resolved* row (approved/rejected/withdrawn) — a still-pending
    submission belongs to the moderation queue (`GET /contributions`,
    moderator-only), not this public read view.
    """

    event_type: str  # 'contribution' | 'series_proposal'
    id: int
    review_status: str  # approved | rejected | withdrawn (contributions only)
    resolution_method: str | None  # contributions only: moderator | community_vote | withdrawn_by_submitter
    reviewed_at: datetime
    submitted_at: datetime
    review_note: str | None
    # contribution events only
    series_id: int | None
    series_title: str | None
    series_slug: str | None
    episode_number: int | None
    proposed_status: str | None
    citation_description: str | None
    # series_proposal events only
    proposal_title: str | None
    # Present on either event type. NULL covers both an anonymous
    # submission and an account anonymized by deletion — the two are
    # indistinguishable on purpose (repositories/contributions.py's own
    # convention).
    submitter_display_name: str | None
    submitter_github_id: str | None
    reviewer_display_name: str | None
    reviewer_github_id: str | None


class ActivityFeedOut(BaseModel):
    items: list[ActivityFeedItem]
    total: int
    limit: int
    offset: int
