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
