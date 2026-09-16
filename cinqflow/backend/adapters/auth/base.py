from abc import ABC, abstractmethod
from typing import Optional
from sqlalchemy.orm import Session

class AuthProvider(ABC):
    """Interface for authentication providers.
    
    DEV: MockAuthProvider — no external dependencies.
    UAT/PROD: EntraAuthProvider — Microsoft Entra ID.
    """
    
    @abstractmethod
    def authenticate(self, credential: str, db: Session) -> Optional[dict]:
        """Validate credential and return session info, or None if invalid."""
        ...
    
    @abstractmethod
    def get_provider_name(self) -> str:
        ...