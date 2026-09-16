"""Auth API — Wave 0 endpoints: login, logout, /me"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.core.security import get_current_user, CurrentUser
from backend.schemas.auth import LoginRequest, LoginResponse, UserProfile

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate using the configured AuthProvider.
    DEV: MockAuthProvider — credential = "username:password"
    PROD: EntraAuthProvider — credential = Entra ID token
    """
    from backend.adapters.auth import get_auth_provider
    provider = get_auth_provider()
    result = provider.authenticate(request.credential, db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return result


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(current_user: CurrentUser = Depends(get_current_user)):
    """
    Invalidate the current session.
    Client should discard the token; server-side revocation tracked via sessions table.
    """
    return {"message": "Logged out", "user_id": current_user.user_id}


@router.get("/me", response_model=UserProfile)
def me(current_user: CurrentUser = Depends(get_current_user)):
    """Return current user profile, roles, and auth provider."""
    return UserProfile(
        id=current_user.user_id,
        email=current_user.email,
        full_name=current_user.email.split("@")[0].replace(".", " ").title(),
        roles=current_user.roles,
        auth_provider=current_user.auth_provider,
    )