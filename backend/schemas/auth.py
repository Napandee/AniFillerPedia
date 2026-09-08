from pydantic import BaseModel, EmailStr, Field

from schemas.contributions import ContributionOut, MyVoteOut
from schemas.series_proposals import SeriesProposalOut
from schemas.synonym_suggestions import SynonymSuggestionOut


class UserOut(BaseModel):
    id: int
    # #208 (GDPR Article 15, right of access): the privacy policy
    # discloses email is collected, but it was never actually returned
    # anywhere before this — added here rather than only on a separate
    # export-only model, since "what does the API say we hold" should
    # include it on the caller's own ordinary profile read too.
    email: str | None
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


class UserExportOut(BaseModel):
    """#208: GDPR Article 15 bundle — the caller's full profile plus
    everything they've submitted/voted on, in one response. Reuses the
    exact same repository/service queries each `/mine`-scoped endpoint
    already exposes separately (services/contributions.py's
    list_my_contributions/list_my_votes, services/series_proposals.py's
    list_my_series_proposals, services/synonym_suggestions.py's
    list_my_synonym_suggestions) rather than reimplementing any of them —
    see routers/users.py's export_current_user_data.
    """

    profile: UserOut
    contributions: list[ContributionOut]
    votes: list[MyVoteOut]
    series_proposals: list[SeriesProposalOut]
    synonym_suggestions: list[SynonymSuggestionOut]


class LocalSignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)


class LocalLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
