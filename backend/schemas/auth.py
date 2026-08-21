from pydantic import BaseModel


class UserOut(BaseModel):
    id: int
    display_name: str | None
    avatar_url: str | None
    role: str
    # #43: the caller's own trust_score — GET /admin/users already computed
    # this per-user but is admin-only; this is the same computation
    # (services/admin.py's compute_trust_score, public since #14) applied
    # to the logged-in caller specifically.
    approved_count: int
    rejected_count: int
    trust_score: int
