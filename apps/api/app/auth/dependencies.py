from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.jwt import ACCESS, TokenError, user_id_from_token
from app.database import get_db
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


def _get_token(credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme)) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid Authorization header")
    return credentials.credentials


def get_current_user(
    token: Annotated[str, Depends(_get_token)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = user_id_from_token(token, ACCESS)
    except TokenError:
        raise credentials_exception from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole):
    """Return a dependency that enforces one of the specified roles."""

    def _check(current_user: CurrentUser) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return Depends(_check)


AdminRequired = require_role(UserRole.ADMIN)
AnalystRequired = require_role(UserRole.ADMIN, UserRole.ANALYST)
ViewerRequired = require_role(UserRole.ADMIN, UserRole.ANALYST, UserRole.VIEWER)
