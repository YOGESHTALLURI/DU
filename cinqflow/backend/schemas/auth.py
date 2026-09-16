from pydantic import BaseModel, EmailStr
from typing import List, Optional
from uuid import UUID

class LoginRequest(BaseModel):
    credential: str  # mock: username, entra: token
    
class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    roles: List[str]

class UserProfile(BaseModel):
    id: str
    email: str
    full_name: str
    roles: List[str]
    auth_provider: str