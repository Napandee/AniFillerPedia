from datetime import datetime

from pydantic import BaseModel, Field

from schemas.episodes import CitationOut


class CitationIn(BaseModel):
    url: str | None = None
    description: str = Field(min_length=1)
    # #83: the field already exists on every citation row (#77) and is
    # already returned to every reader via CitationOut — withholding it
    # from public submissions would be an arbitrary asymmetry, not a
    # deliberate simplification, since the schema already treats every
    # citation identically regardless of who authored it. Optional, same
    # as proposed_note/status_note elsewhere in this form.
    methodology_note: str | None = None


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


class ContributionReject(BaseModel):
    # Required, not optional — #13/#3: a moderator must give a reason, so a
    # rejected contributor understands why rather than just that they were.
    review_note: str = Field(min_length=1)


class ContributionReviewOut(BaseModel):
    id: int
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


class VoteCreate(BaseModel):
    vote: str = Field(pattern="^(endorse|dispute)$")


class VoteCastOut(BaseModel):
    """Response for POST /contributions/{id}/vote — reports the outcome of
    THIS vote (weight_at_vote, the vote's own contribution to net_score) as
    well as the contribution's resulting state, which may reflect a
    different concurrent voter's promotion rather than this one (see
    repositories/contributions.py's promote_via_vote race note) — always
    re-read from the row after voting rather than assumed from this
    request alone.
    """

    contribution_id: int
    vote: str
    weight_at_vote: int
    net_score: int
    auto_approval_threshold: int
    review_status: str
    resolution_method: str | None


class MyVoteOut(BaseModel):
    """#30: one entry per vote the caller has cast, enough context
    (series title, episode, current resolution) to render without a
    follow-up request per row.
    """

    contribution_id: int
    series_id: int
    series_title: str
    episode_number: int
    proposed_status: str
    vote: str
    weight_at_vote: int
    review_status: str
    resolution_method: str | None
    created_at: datetime


class BulkContributionCreate(BaseModel):
    """#80: reuses the community's own existing range-notation shorthand
    ("1-44, 48-49, 52-53") rather than a new format contributors would
    have to learn — the exact style already used to hand-compile every
    dataset in data/bootstrap/. Any of the three may be empty (a
    submission doesn't need all three categories), but at least one
    episode must be declared across all three combined.
    """

    canon_ranges: str = ""
    mixed_ranges: str = ""
    filler_ranges: str = ""
    citation: CitationIn
    license_accepted: bool
    # When true, parses/validates (including the #20 pending-conflict
    # check) and reports exactly what WOULD happen, but writes nothing —
    # the frontend's "review before you submit" step reuses this same
    # endpoint rather than duplicating the parsing/validation logic in
    # two languages.
    dry_run: bool = False


class BulkCreatedEntry(BaseModel):
    episode_number: int
    # None only when dry_run=True — nothing has actually been created yet
    # to have a real id.
    contribution_id: int | None
    proposed_status: str


class BulkSkippedEntry(BaseModel):
    """#20's one-pending-per-episode rule, applied per episode within a
    batch rather than failing the whole submission — the rest of the
    batch still goes through; this just tells the submitter which numbers
    didn't, and points at the existing contribution so they can endorse/
    dispute it directly instead.
    """

    episode_number: int
    existing_contribution_id: int


class BulkContributionResult(BaseModel):
    dry_run: bool
    declared_count: int
    created: list[BulkCreatedEntry]
    skipped_conflicts: list[BulkSkippedEntry]


class BulkRangeError(BaseModel):
    """422 response body for a malformed/self-contradictory/oversized
    range submission — caught before any database write happens.
    """

    detail: dict


class BulkSubmissionRateLimited(BaseModel):
    """429 response body when #84's per-account rolling-window bulk-
    submission limit is exceeded. `detail` is a plain message (unlike
    DuplicatePendingContribution's structured detail) since there's no
    specific resource to point the caller at — just "wait" or "use
    dry_run."
    """

    detail: str


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
