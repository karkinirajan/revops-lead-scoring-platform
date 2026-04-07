from app.schemas.common import OrmBase


class LoginRequest(OrmBase):
    email: str
    password: str


class TokenResponse(OrmBase):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserCreate(OrmBase):
    email: str
    password: str
    full_name: str | None = None
    role: str = "viewer"


class UserRead(OrmBase):
    id: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
