"""
Database Seed Script for CINQFLOW Wave 0.

Creates initial realistic baseline data:
- Roles: ENGINEER, READ_ONLY
- Users: Dev Engineer, Read-Only User
- Contract Register Entry & Unknown
- Sample Feed Registry definition with published FeedVersion (generic metadata, no hardcoding)
- Initial audit logs
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.core.database import SessionLocal, engine
from backend.models.user import User, Role, UserRole, AuthProviderEnum, RoleEnum
from backend.models.contract import (
    ContractRegisterEntry,
    ContractUnknown,
    ContractStatusEnum,
    UnknownStatusEnum,
    RiskLevelEnum,
)
from backend.models.feed import (
    Feed,
    FeedVersion,
    FeedFormatEnum,
    FeedStatusEnum,
    FeedVersionStatusEnum,
)
from backend.models.audit import AuditEvent, AuditActionEnum


def seed_database(db: Session) -> dict:
    """Idempotently seed the database."""
    summary = {}

    # 1. Seed Roles
    roles = {}
    for role_enum in [RoleEnum.ENGINEER, RoleEnum.READ_ONLY]:
        r = db.query(Role).filter(Role.name == role_enum).first()
        if not r:
            r = Role(
                id=uuid.uuid4(),
                name=role_enum,
                description=f"System role: {role_enum.value}",
                created_by="system",
                updated_by="system",
            )
            db.add(r)
            db.flush()
        roles[role_enum] = r
    summary["roles"] = len(roles)

    # 2. Seed Users
    # Engineer
    engineer_user = db.query(User).filter(User.email == "engineer@cinqflow.local").first()
    if not engineer_user:
        engineer_user = User(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            email="engineer@cinqflow.local",
            full_name="Dev Engineer",
            auth_provider=AuthProviderEnum.mock,
            auth_provider_id="mock-engineer-001",
            is_active=True,
            created_by="system",
            updated_by="system",
        )
        db.add(engineer_user)
        db.flush()
        ur = UserRole(
            id=uuid.uuid4(),
            user_id=engineer_user.id,
            role=RoleEnum.ENGINEER,
            role_id=roles[RoleEnum.ENGINEER].id,
            created_by="system",
            updated_by="system",
        )
        db.add(ur)

    # Read-Only User
    readonly_user = db.query(User).filter(User.email == "readonly@cinqflow.local").first()
    if not readonly_user:
        readonly_user = User(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            email="readonly@cinqflow.local",
            full_name="Read Only Analyst",
            auth_provider=AuthProviderEnum.mock,
            auth_provider_id="mock-readonly-001",
            is_active=True,
            created_by="system",
            updated_by="system",
        )
        db.add(readonly_user)
        db.flush()
        ur = UserRole(
            id=uuid.uuid4(),
            user_id=readonly_user.id,
            role=RoleEnum.READ_ONLY,
            role_id=roles[RoleEnum.READ_ONLY].id,
            created_by="system",
            updated_by="system",
        )
        db.add(ur)
    summary["users"] = 2

    # 3. Seed Contract Register Entry & Unknown
    contract = (
        db.query(ContractRegisterEntry)
        .filter(ContractRegisterEntry.source_system == "HEALTH_PLAN_SOURCE")
        .first()
    )
    if not contract:
        contract = ContractRegisterEntry(
            id=uuid.uuid4(),
            source_system="HEALTH_PLAN_SOURCE",
            target_domain="MEMBERSHIP",
            description="Member demographic and eligibility monthly roster feed",
            data_owner="Member Operations",
            status=ContractStatusEnum.CONFIRMED,
            story_id="CF-V0-E1-01",
            notes="Foundation contract register baseline for Wave 0",
            created_by="system",
            updated_by="system",
        )
        db.add(contract)
        db.flush()

        unknown = ContractUnknown(
            id=uuid.uuid4(),
            contract_entry_id=contract.id,
            description="Confirm production SFTP delivery SLA and archive retention policy",
            risk_level=RiskLevelEnum.MEDIUM,
            status=UnknownStatusEnum.OPEN,
            resolution_notes="Awaiting confirmation from payer IT operations",
            created_by="system",
            updated_by="system",
        )
        db.add(unknown)
    summary["contracts"] = 1

    # 4. Seed Generic Feed & Published Version (No Feed-specific branching)
    feed = db.query(Feed).filter(Feed.name == "MEMBER_DEMO_FEED").first()
    if not feed:
        feed = Feed(
            id=uuid.uuid4(),
            name="MEMBER_DEMO_FEED",
            domain="MEMBERSHIP",
            description="Deterministic member demo feed with valid and invalid records",
            format=FeedFormatEnum.CSV,
            landing_folder="./data/landing",
            filename_pattern="MEMBER_*.csv",
            schedule_expression="manual",
            status=FeedStatusEnum.ACTIVE,
            created_by="system",
            updated_by="system",
        )
        db.add(feed)
        db.flush()

        # Version 1 published
        feed_version = FeedVersion(
            id=uuid.uuid4(),
            feed_id=feed.id,
            version_number=1,
            status=FeedVersionStatusEnum.PUBLISHED,
            config_snapshot={
                "fields": [
                    {"name": "member_id", "type": "STRING", "required": True},
                    {"name": "first_name", "type": "STRING", "required": True},
                    {"name": "last_name", "type": "STRING", "required": True},
                    {"name": "date_of_birth", "type": "DATE", "required": True},
                    {"name": "gender", "type": "ENUM", "allowed_values": ["M", "F", "U"], "required": False},
                ],
                "delimiter": ",",
                "has_header": True,
            },
            change_notes="Initial published configuration snapshot",
            published_by="mock-engineer-001",
            created_by="system",
            updated_by="system",
        )
        db.add(feed_version)
    summary["feeds"] = 1

    # 5. Audit Event for Seeding
    audit = AuditEvent(
        id=uuid.uuid4(),
        action=AuditActionEnum.FEED_CREATED,
        actor_id="system",
        actor_email="system@cinqflow.local",
        object_type="feed",
        object_id=str(feed.id),
        description="Database seeded with Wave 0 baseline configuration",
        created_by="system",
        updated_by="system",
    )
    db.add(audit)

    db.commit()
    return summary


if __name__ == "__main__":
    db = SessionLocal()
    try:
        res = seed_database(db)
        print(f"Seed completed successfully: {res}")
    finally:
        db.close()
