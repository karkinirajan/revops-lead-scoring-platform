from pydantic import EmailStr, Field, field_validator

from app.auth.jwt import MAX_PASSWORD_BYTES
from app.models.user import UserRole
from app.schemas.common import OrmBase

MIN_PASSWORD_LENGTH = 12


class LoginRequest(OrmBase):
    email: str = Field(max_length=255)
    password: str = Field(max_length=256)


class RefreshRequest(OrmBase):
    refresh_token: str = Field(max_length=4096)


class TokenResponse(OrmBase):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


def validate_password(value: str) -> str:
    """The rules for a new password, shared by user creation and the command line."""
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(value.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes")
    return value


class UserCreate(OrmBase):
    email: EmailStr = Field(max_length=255)
    password: str
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = UserRole.VIEWER

    @field_validator("password")
    @classmethod
    def password_is_usable(cls, value: str) -> str:
        return validate_password(value)


class UserRead(OrmBase):
    id: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
