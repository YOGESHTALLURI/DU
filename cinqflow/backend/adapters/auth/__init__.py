from backend.core.config import settings
from backend.adapters.auth.base import AuthProvider
from backend.adapters.auth.mock_provider import MockAuthProvider
from backend.adapters.auth.entra_provider import EntraAuthProvider

def get_auth_provider() -> AuthProvider:
    if settings.AUTH_PROVIDER == "mock":
        return MockAuthProvider()
    elif settings.AUTH_PROVIDER == "entra":
        return EntraAuthProvider()
    else:
        raise ValueError(f"Unknown auth provider: {settings.AUTH_PROVIDER}")