from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import AdminRequired, CurrentUser
from app.auth.jwt import create_access_token, create_refresh_token, hash_password, verify_password
from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, TokenResponse, UserCreate, UserRead

router = APIRouter()
settings = get_settings()


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id, extra={"role": user.role, "email": user.email}),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser):
    return current_user


@router.post("/users", response_model=UserRead, dependencies=[AdminRequired])
def create_user(body: UserCreate, db: Annotated[Session, Depends(get_db)]):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    if body.role not in list(UserRole):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {body.role}")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
