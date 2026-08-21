from pydantic import BaseModel


class UserOut(BaseModel):
    id: int
    display_name: str | None
    avatar_url: str | None
    role: str
