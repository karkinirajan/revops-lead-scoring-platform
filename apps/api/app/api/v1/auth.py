from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import AdminRequired, CurrentUser
from app.auth.jwt import (
    REFRESH,
    TokenError,
    create_access_token,
    create_refresh_token,
    hash_password,
    spend_password_time,
    user_id_from_token,
    verify_password,
)
from app.config import get_settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserCreate, UserRead

router = APIRouter()
settings = get_settings()


def _tokens_for(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, extra={"role": user.role, "email": user.email}),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


def _user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()


@router.post("/login", response_model=TokenResponse)
@limiter.limit(f"{settings.rate_limit_login_per_minute}/minute")
def login(request: Request, body: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = _user_by_email(db, body.email)
    if user is None:
        spend_password_time()  # an unknown email must not answer faster than a wrong password
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    user.last_login_at = datetime.now(UTC)
    db.commit()
    return _tokens_for(user)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(f"{settings.rate_limit_login_per_minute}/minute")
def refresh(request: Request, body: RefreshRequest, db: Annotated[Session, Depends(get_db)]):
    """Exchange a refresh token for a new pair of tokens. Only a refresh token is accepted here (and only an access token anywhere else)."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token", headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        user_id = user_id_from_token(body.refresh_token, REFRESH)
    except TokenError:
        raise invalid from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise invalid
    return _tokens_for(user)


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser):
    return current_user


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, dependencies=[AdminRequired])
def create_user(body: UserCreate, db: Annotated[Session, Depends(get_db)]):
    email = body.email.strip().lower()
    if _user_by_email(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
