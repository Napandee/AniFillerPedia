from datetime import datetime

from pydantic import BaseModel, Field

from schemas.contributions import CitationIn


class EpisodeDataIn(BaseModel):
    """#85: a contributor's optional episode-range data, attached to a
    series proposal in the same shape #80's bulk-submission endpoint
    already expects — held on the proposal row (see services/
    series_proposals.py) until approval, when it's turned into real
    citations + contributions targeting the newly-created series. No
    license_accepted/dry_run fields here, unlike BulkContributionCreate —
    the proposal's own top-level license_accepted covers this same
    submission event, and there's no series_id yet to preview a dry run
    against.
    """

    canon_ranges: str = ""
    mixed_ranges: str = ""
    filler_ranges: str = ""
    citation: CitationIn


class EpisodeDataOut(EpisodeDataIn):
    # #85: computed at read time (from the same validated ranges above) so
    # the moderation queue can show "220 episodes declared" without the
    # frontend re-parsing range strings itself. Never fails in practice —
    # the ranges were already validated at submission time — but defensive
    # rather than assumed; see services/series_proposals.py's _row_to_out.
    declared_count: int


class SeriesProposalCreate(BaseModel):
    title: str = Field(min_length=1)
    anilist_id: int | None = None
    mal_id: int | None = None
    anidb_id: int | None = None
    # #140: max_length 3000 — same "a couple thousand characters is plenty
    # for a real justification" ceiling as the other freeform fields in
    # this batch of fixes (schemas/contributions.py), bounding the
    # storage-bloat vector without risking rejecting any real submission.
    justification: str = Field(min_length=1, max_length=3000)
    license_accepted: bool
    # Same structurally-ready-not-live-verified note as ContributionCreate.
    turnstile_token: str | None = None
    # #85: optional — a proposal submitted without this works exactly as
    # it did before this issue existed.
    episode_data: EpisodeDataIn | None = None


class SimilarSeriesMatchOut(BaseModel):
    """#150: a single "this might already exist" hint against the live
    `series` catalog. Surfaced both in the submission response (frontend
    shows it to the submitter right after they submit) and in the
    moderation-queue listing (services/series_proposals.py's _row_to_out
    computes this fresh every time a proposal is serialized, so a
    moderator always sees it against the CURRENT catalog, not a stale
    snapshot from submission time) — never blocking, just a pointer.
    """

    id: int
    title: str
    slug: str | None = None


class SimilarSeriesCheckOut(BaseModel):
    """#150: response shape for the standalone, pre-submission
    GET /series-proposals/check-title lookup the frontend calls on
    Title-field blur — same matches list as SeriesProposalOut's own
    possible_duplicate_matches, just available before a submitter has
    committed to the rest of the form.
    """

    matches: list[SimilarSeriesMatchOut]


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
    episode_data: EpisodeDataOut | None = None
    # #150: computed at read time against the live series catalog — see
    # SimilarSeriesMatchOut's own docstring for why this is never stale.
    possible_duplicate_matches: list[SimilarSeriesMatchOut] = Field(default_factory=list)


class SeriesProposalReject(BaseModel):
    review_note: str = Field(min_length=1)


class SeriesProposalReviewOut(BaseModel):
    id: int
    review_status: str
    reviewed_at: datetime | None
    review_note: str | None
    # #85: None for a proposal with no attached episode data, or on
    # rejection (nothing was ever created to count). Set on approval of a
    # proposal that had episode_data — how many contributions the approval
    # actually created (may be less than declared_count if any collided
    # with something else already pending for that series/episode).
    episode_contributions_created: int | None = None
