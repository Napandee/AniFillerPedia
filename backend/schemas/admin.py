from pydantic import BaseModel, Field


class AdminUserOut(BaseModel):
    id: int
    role: str
    github_id: str | None
    discord_id: str | None
    google_id: str | None
    display_name: str | None
    approved_count: int
    rejected_count: int
    trust_score: int
    created_at: str


class AdminUserListOut(BaseModel):
    items: list[AdminUserOut]
    total: int
    limit: int
    offset: int


class RoleUpdateIn(BaseModel):
    role: str = Field(
        description=(
            "One of: contributor, moderator, admin. 'owner' is deliberately "
            "not a valid value here — it is set once at bootstrap and is "
            "never assignable through this endpoint. Setting 'admin' "
            "requires the caller to be the owner."
        )
    )


class RoleUpdateOut(BaseModel):
    """#138: PATCH /admin/users/{id}/role previously had no response_model
    at all (returned a bare dict) — this documents the real shape.
    """

    id: int
    role: str


class SuspensionUpdateIn(BaseModel):
    """#209: body for PATCH /admin/users/{id}/suspension."""

    suspended: bool
    reason: str | None = Field(
        default=None,
        description=(
            "Moderator-facing note explaining the suspension. Ignored "
            "(cleared) when suspended=false."
        ),
    )


class SuspensionUpdateOut(BaseModel):
    id: int
    suspended: bool
    suspended_at: str | None
    suspended_reason: str | None


class VoteClusteringPairOut(BaseModel):
    """#203: one reciprocal-endorsement pair surfaced by the Sybil-
    monitoring report — see services/admin.py's get_vote_clustering_report.
    """

    user_a_id: int
    user_a_display_name: str | None
    user_b_id: int
    user_b_display_name: str | None
    a_endorsed_b_count: int
    b_endorsed_a_count: int
    combined_endorsement_count: int
    last_activity_at: str


class VoteClusteringReportOut(BaseModel):
    items: list[VoteClusteringPairOut]
    min_reciprocal_count: int
