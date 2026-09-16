"""
Security middleware: JWT verification and role-based authorization.

Authorization is enforced SERVER-SIDE at the API layer.
Do NOT rely on hiding UI buttons for access control.

Roles (Wave 0):
  ENGINEER   — can create, update, publish Wave 0 configuration
  READ_ONLY  — can view, cannot create/update/execute privileged actions
"""
from typing import Optional, List
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from backend.core.config import settings
from backend.core.database import get_db

security = HTTPBearer(auto_error=False)


class CurrentUser:
    """Represents an authenticated user with their roles."""
    def __init__(self, user_id: str, email: str, roles: List[str], auth_provider: str):
        self.user_id = user_id
        self.email = email
        self.roles = roles
        self.auth_provider = auth_provider

    def is_engineer(self) -> bool:
        return "ENGINEER" in self.roles

    def is_business_analyst(self) -> bool:
        return "BUSINESS_ANALYST" in self.roles

    def is_data_steward(self) -> bool:
        return "DATA_STEWARD" in self.roles

    def is_read_only(self) -> bool:
        return "READ_ONLY" in self.roles and "ENGINEER" not in self.roles and "BUSINESS_ANALYST" not in self.roles

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def __repr__(self) -> str:
        return f"<CurrentUser email={self.email} roles={self.roles}>"


def _decode_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT. Returns None if invalid."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """
    FastAPI dependency: extract and validate current user from JWT.
    Raises HTTP 401 if token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(
        user_id=payload.get("sub", ""),
        email=payload.get("email", ""),
        roles=payload.get("roles", []),
        auth_provider=payload.get("provider", "unknown"),
    )


def require_engineer(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """
    Dependency: requires ENGINEER role.
    Used on any endpoint that creates, updates, or executes privileged actions.
    """
    if not current_user.is_engineer():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ENGINEER role required",
        )
    return current_user


def require_analyst_or_engineer(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """
    Dependency: requires BUSINESS_ANALYST or ENGINEER role.
    Used for sample uploads, profiling runs, and schema contract authoring.
    """
    if not (current_user.is_business_analyst() or current_user.is_engineer()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="BUSINESS_ANALYST or ENGINEER role required",
        )
    return current_user


def require_any_role(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """
    Dependency: requires any valid authenticated role (ENGINEER or READ_ONLY).
    Used on read endpoints.
    """
    if not current_user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No roles assigned to this user",
        )
    return current_user


def require_steward_or_engineer(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency: requires DATA_STEWARD or ENGINEER role."""
    if not (current_user.is_data_steward() or current_user.is_engineer()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="DATA_STEWARD or ENGINEER role required",
        )
    return current_user


def require_analyst_steward_or_engineer(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency: requires BUSINESS_ANALYST, DATA_STEWARD, or ENGINEER role."""
    if not (current_user.is_business_analyst() or current_user.is_data_steward() or current_user.is_engineer()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="BUSINESS_ANALYST, DATA_STEWARD, or ENGINEER role required",
        )
    return current_user


def require_steward(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency: requires DATA_STEWARD role."""
    if not current_user.is_data_steward():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="DATA_STEWARD role required",
        )
    return current_user
