from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from jose import jwt
from backend.adapters.auth.base import AuthProvider
from backend.core.config import settings

MOCK_USERS = {
    "engineer": {
        "id": "mock-engineer-001",
        "email": "engineer@cinqflow.local",
        "full_name": "Dev Engineer",
        "roles": ["ENGINEER"],
        "password": "engineer123",
    },
    "readonly": {
        "id": "mock-readonly-001",
        "email": "readonly@cinqflow.local",
        "full_name": "Read Only User",
        "roles": ["READ_ONLY"],
        "password": "readonly123",
    },
    "analyst": {
        "id": "mock-analyst-001",
        "email": "analyst@cinqflow.local",
        "full_name": "Business Analyst",
        "roles": ["BUSINESS_ANALYST"],
        "password": "analyst123",
    },
    "engineer2": {
        "id": "mock-engineer-002",
        "email": "engineer2@cinqflow.local",
        "full_name": "Lead Reviewing Engineer",
        "roles": ["ENGINEER"],
        "password": "engineer123",
    },
    "steward": {
        "id": "mock-steward-001",
        "email": "steward@cinqflow.local",
        "full_name": "Data Steward",
        "roles": ["DATA_STEWARD"],
        "password": "steward123",
    },
}

class MockAuthProvider(AuthProvider):
    """Local development auth provider. No external dependencies.
    Accepts username:password credential.
    Supports ENGINEER and READ_ONLY roles.
    """
    
    def authenticate(self, credential: str, db: Session) -> Optional[dict]:
        # credential format: "username:password"
        try:
            username, password = credential.split(":", 1)
        except ValueError:
            return None
        
        user = MOCK_USERS.get(username)
        if not user or user["password"] != password:
            return None
        
        token_data = {
            "sub": user["id"],
            "email": user["email"],
            "roles": user["roles"],
            "provider": "mock",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRY_MINUTES),
        }
        token = jwt.encode(token_data, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": settings.JWT_EXPIRY_MINUTES * 60,
            "user_id": user["id"],
            "email": user["email"],
            "roles": user["roles"],
        }
    
    def get_provider_name(self) -> str:
        return "mock"