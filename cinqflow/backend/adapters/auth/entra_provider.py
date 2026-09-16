from typing import Optional
from sqlalchemy.orm import Session
from backend.adapters.auth.base import AuthProvider

class EntraAuthProvider(AuthProvider):
    """Microsoft Entra ID authentication provider.
    
    Status: ADAPTER STUB — not connected to production Entra.
    See UNKNOWN_AND_INTEGRATION_REGISTER.md UNK-010.
    Required config: ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET
    """
    
    def authenticate(self, credential: str, db: Session) -> Optional[dict]:
        # TODO: Validate Entra JWT using MSAL
        # TODO: Extract roles from Entra security groups
        raise NotImplementedError(
            "EntraAuthProvider is not yet configured. "
            "Set AUTH_PROVIDER=mock for local development. "
            "See UNK-010 in UNKNOWN_AND_INTEGRATION_REGISTER.md."
        )
    
    def get_provider_name(self) -> str:
        return "entra"