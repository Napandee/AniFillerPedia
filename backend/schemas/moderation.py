"""#3: shared request/response shapes for bulk moderation actions —
identical shape needed by both contributions and series-proposals, so
defined once here rather than duplicated in schemas/contributions.py and
schemas/series_proposals.py.
"""

from pydantic import BaseModel, Field

# Same spirit as #80's MAX_BATCH_SIZE — a defensive bound, not a real
# expected queue depth. Lower than #80's 2000: each item here does more
# work per id (approve promotes into episodes/series + writes an outbox
# event), not a single INSERT.
MAX_BULK_MODERATION_SIZE = 500


class BulkApproveRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_BULK_MODERATION_SIZE)


class BulkRejectRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_BULK_MODERATION_SIZE)
    # One shared reason for the whole batch — Overseerr/Ombi's own bulk-
    # decline pattern (CLAUDE.md/#3 research), not a per-item note. A
    # moderator bulk-rejecting a pile of near-identical bad submissions
    # (e.g. all uncited) doesn't need to retype the same reason per row.
    review_note: str = Field(min_length=1)


class BulkModerationEntry(BaseModel):
    id: int
    ok: bool
    # Populated only when ok is False — e.g. "not found" or "not pending
    # (current status: rejected)". A batch never fails wholesale on one
    # bad id; every id gets its own real outcome reported back.
    detail: str | None = None


class BulkModerationResult(BaseModel):
    results: list[BulkModerationEntry]
