"""
Wave 0 Database Models — Users, Roles, Sessions

Supports both MockAuthProvider (DEV) and EntraAuthProvider (UAT/PROD).
"""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, ForeignKey, Enum as SAEnum, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.models.base import Base, AuditMixin


class AuthProviderEnum(str, enum.Enum):
    mock = "mock"
    entra = "entra"


class RoleEnum(str, enum.Enum):
    ENGINEER = "ENGINEER"
    READ_ONLY = "READ_ONLY"
    # Future wave roles — not active in Wave 0
    BUSINESS_ANALYST = "BUSINESS_ANALYST"
    DATA_STEWARD = "DATA_STEWARD"
    OPERATIONS = "OPERATIONS"
    APPROVER = "APPROVER"
    ADMINISTRATOR = "ADMINISTRATOR"


class User(Base, AuditMixin):
    """Core user identity. Supports both mock and Entra auth providers."""
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_provider: Mapped[AuthProviderEnum] = mapped_column(
        SAEnum(AuthProviderEnum, name="auth_provider_enum", values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    # External ID from auth provider (Entra OID or mock ID)
    auth_provider_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    user_roles: Mapped[list["UserRole"]] = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_users_auth_provider_id_provider", "auth_provider_id", "auth_provider", unique=True),
    )

    def has_role(self, role: RoleEnum) -> bool:
        return any(ur.role == role for ur in self.user_roles)

    def get_roles(self) -> list[str]:
        return [ur.role.value for ur in self.user_roles]


class Role(Base, AuditMixin):
    """System role definitions."""
    __tablename__ = "roles"

    name: Mapped[RoleEnum] = mapped_column(
        SAEnum(RoleEnum, name="role_enum"), nullable=False, unique=True
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user_roles: Mapped[list["UserRole"]] = relationship("UserRole", back_populates="role_obj")


class UserRole(Base, AuditMixin):
    """Many-to-many: User <-> Role assignment."""
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[RoleEnum] = mapped_column(
        SAEnum(RoleEnum, name="role_enum"), nullable=False
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True
    )

    user: Mapped[User] = relationship("User", back_populates="user_roles")
    role_obj: Mapped[Role | None] = relationship("Role", back_populates="user_roles")

    __table_args__ = (
        Index("ix_user_roles_user_role", "user_id", "role", unique=True),
    )


class Session(Base, AuditMixin):
    """User session tracking."""
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jwt_jti: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="sessions")
