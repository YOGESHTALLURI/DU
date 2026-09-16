"""
Scheduling Service — Wave 1 Slice 6 (CF-V1-E8-03)

Manages Feed operational schedules, cron parsing, next-run calculation,
and lifecycle state transitions (ACTIVE, PAUSED, DISABLED).
"""
import re
import uuid
import zoneinfo
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.feed import Feed, FeedStatusEnum
from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.core.security import CurrentUser


def parse_cron_field(field_str: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field into a set of matching integer values."""
    field_str = field_str.strip()
    if field_str == "*":
        return set(range(min_val, max_val + 1))

    # Step: */n or a-b/n
    if "/" in field_str:
        parts = field_str.split("/")
        if len(parts) != 2 or not parts[1].isdigit():
            raise ValueError(f"Invalid cron step syntax '{field_str}'")
        step = int(parts[1])
        if step <= 0:
            raise ValueError(f"Step must be positive in '{field_str}'")
        base_range = parse_cron_field(parts[0], min_val, max_val)
        return set(range(min(base_range), max(base_range) + 1, step))

    # List: a,b,c
    if "," in field_str:
        result = set()
        for item in field_str.split(","):
            result.update(parse_cron_field(item, min_val, max_val))
        return result

    # Range: a-b
    if "-" in field_str:
        parts = field_str.split("-")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            raise ValueError(f"Invalid cron range syntax '{field_str}'")
        start, end = int(parts[0]), int(parts[1])
        if start > end or start < min_val or end > max_val:
            raise ValueError(f"Range {start}-{end} out of bounds [{min_val}, {max_val}]")
        return set(range(start, end + 1))

    # Single number
    if field_str.isdigit():
        val = int(field_str)
        if val < min_val or val > max_val:
            raise ValueError(f"Value {val} out of bounds [{min_val}, {max_val}]")
        return {val}

    raise ValueError(f"Unrecognized cron field syntax '{field_str}'")


def validate_cron_expression(cron_str: str) -> bool:
    """Validates standard 5-part cron expression (minute, hour, dom, month, dow)."""
    if not cron_str or not isinstance(cron_str, str):
        raise ValueError("Cron expression cannot be empty")

    cron_str = cron_str.strip()
    if cron_str.lower() == "manual":
        return True

    parts = cron_str.split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must contain exactly 5 space-separated fields, got {len(parts)}")

    # Field bounds: minute (0-59), hour (0-23), day of month (1-31), month (1-12), day of week (0-7)
    parse_cron_field(parts[0], 0, 59)
    parse_cron_field(parts[1], 0, 23)
    parse_cron_field(parts[2], 1, 31)
    parse_cron_field(parts[3], 1, 12)
    parse_cron_field(parts[4], 0, 7)
    return True


def compute_next_run(
    cron_str: str,
    from_dt: Optional[datetime] = None,
    tz_str: str = "UTC",
) -> Optional[datetime]:
    """Computes the next scheduled run timestamp from from_dt with timezone/DST awareness."""
    if not cron_str or cron_str.lower() == "manual":
        return None

    validate_cron_expression(cron_str)
    parts = cron_str.strip().split()
    minutes = parse_cron_field(parts[0], 0, 59)
    hours = parse_cron_field(parts[1], 0, 23)
    doms = parse_cron_field(parts[2], 1, 31)
    months = parse_cron_field(parts[3], 1, 12)
    dows = parse_cron_field(parts[4], 0, 7)
    if 7 in dows:
        dows.add(0)

    try:
        target_tz = zoneinfo.ZoneInfo(tz_str or "UTC")
    except Exception:
        target_tz = timezone.utc

    start = from_dt or datetime.now(timezone.utc)
    local_start = start.astimezone(target_tz)
    current = local_start.replace(second=0, microsecond=0) + timedelta(minutes=1)

    # Search up to 366 days ahead (527,040 minutes)
    for _ in range(527040):
        if current.month in months and current.day in doms:
            cron_dow = (current.weekday() + 1) % 7
            if cron_dow in dows:
                if current.hour in hours and current.minute in minutes:
                    return current
        current += timedelta(minutes=1)

    return None


class SchedulingService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def get_schedule(self, feed_id: uuid.UUID) -> FeedSchedule:
        """Get or lazily initialize schedule for a feed."""
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed {feed_id} not found")

        sched = self.db.query(FeedSchedule).filter(FeedSchedule.feed_id == feed_id).first()
        if not sched:
            expr = feed.schedule_expression or "0 0 * * *"
            try:
                validate_cron_expression(expr)
                next_run = compute_next_run(expr, tz_str="UTC")
            except ValueError:
                expr = "manual"
                next_run = None

            sched = FeedSchedule(
                id=uuid.uuid4(),
                feed_id=feed.id,
                schedule_expression=expr,
                timezone="UTC",
                status=ScheduleStatusEnum.ACTIVE if expr != "manual" else ScheduleStatusEnum.PAUSED,
                next_run_at=next_run,
                catchup=False,
                created_by=feed.created_by,
                updated_by=feed.created_by,
            )
            self.db.add(sched)
            self.db.commit()
            self.db.refresh(sched)

        return sched

    def create_schedule(
        self,
        feed_id: uuid.UUID,
        schedule_expression: str,
        timezone_str: str,
        catchup: bool,
        current_user: CurrentUser,
    ) -> FeedSchedule:
        """Explicitly creates a schedule record (fails with 409 if one exists)."""
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed {feed_id} not found")

        existing = self.db.query(FeedSchedule).filter(FeedSchedule.feed_id == feed_id).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Schedule already exists for feed {feed_id}",
            )

        try:
            validate_cron_expression(schedule_expression)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid cron expression: {str(e)}")

        sched = FeedSchedule(
            id=uuid.uuid4(),
            feed_id=feed_id,
            schedule_expression=schedule_expression,
            timezone=timezone_str or "UTC",
            status=ScheduleStatusEnum.ACTIVE if schedule_expression != "manual" else ScheduleStatusEnum.PAUSED,
            catchup=catchup,
            created_by=current_user.user_id,
            updated_by=current_user.user_id,
        )
        sched.next_run_at = (
            compute_next_run(sched.schedule_expression, tz_str=sched.timezone)
            if sched.status == ScheduleStatusEnum.ACTIVE
            else None
        )
        self.db.add(sched)

        # Backward compatibility sync
        feed.schedule_expression = schedule_expression
        feed.updated_by = current_user.user_id

        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.SCHEDULE_CREATED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="feed_schedules",
            object_id=str(sched.id),
            after_state={
                "feed_id": str(feed_id),
                "schedule_expression": sched.schedule_expression,
                "timezone": sched.timezone,
                "status": sched.status.value,
                "next_run_at": sched.next_run_at.isoformat() if sched.next_run_at else None,
            },
            description=f"Created schedule for feed {feed.name} ('{sched.schedule_expression}')",
        )
        self.db.commit()
        self.db.refresh(sched)
        return sched

    def update_schedule(
        self,
        feed_id: uuid.UUID,
        schedule_expression: str,
        timezone_str: str,
        catchup: bool,
        current_user: CurrentUser,
    ) -> FeedSchedule:
        """Idempotent upsert: updates feed schedule expression or creates if missing."""
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed {feed_id} not found")

        try:
            validate_cron_expression(schedule_expression)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid cron expression: {str(e)}",
            )

        sched = self.db.query(FeedSchedule).filter(FeedSchedule.feed_id == feed_id).first()
        is_new = False
        before_state = None

        if not sched:
            is_new = True
            sched = FeedSchedule(
                id=uuid.uuid4(),
                feed_id=feed_id,
                schedule_expression=schedule_expression,
                timezone=timezone_str or "UTC",
                status=ScheduleStatusEnum.ACTIVE if schedule_expression != "manual" else ScheduleStatusEnum.PAUSED,
                catchup=catchup,
                created_by=current_user.user_id,
                updated_by=current_user.user_id,
            )
            self.db.add(sched)
        else:
            before_state = {
                "schedule_expression": sched.schedule_expression,
                "timezone": sched.timezone,
                "status": sched.status.value,
                "catchup": sched.catchup,
            }
            sched.schedule_expression = schedule_expression
            sched.timezone = timezone_str or "UTC"
            sched.catchup = catchup
            sched.updated_by = current_user.user_id
            sched.version += 1

        sched.next_run_at = (
            compute_next_run(sched.schedule_expression, tz_str=sched.timezone)
            if sched.status == ScheduleStatusEnum.ACTIVE
            else None
        )

        # Keep legacy Feed table in sync as backward-compatible projection
        feed.schedule_expression = schedule_expression
        feed.updated_by = current_user.user_id

        self.db.flush()

        action = AuditActionEnum.SCHEDULE_CREATED if is_new else AuditActionEnum.SCHEDULE_UPDATED
        self.audit.emit(
            action=action,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="feed_schedules",
            object_id=str(sched.id),
            before_state=before_state,
            after_state={
                "feed_id": str(feed_id),
                "schedule_expression": sched.schedule_expression,
                "timezone": sched.timezone,
                "status": sched.status.value,
                "next_run_at": sched.next_run_at.isoformat() if sched.next_run_at else None,
            },
            description=f"{'Created' if is_new else 'Updated'} schedule for feed {feed.name} ('{sched.schedule_expression}')",
        )

        self.db.commit()
        self.db.refresh(sched)
        return sched

    def pause_schedule(self, feed_id: uuid.UUID, current_user: CurrentUser) -> FeedSchedule:
        """Pause operational schedule for feed."""
        sched = self.get_schedule(feed_id)
        if sched.status == ScheduleStatusEnum.PAUSED:
            return sched

        before_status = sched.status.value
        sched.status = ScheduleStatusEnum.PAUSED
        sched.next_run_at = None
        sched.updated_by = current_user.user_id
        sched.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.SCHEDULE_PAUSED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="feed_schedules",
            object_id=str(sched.id),
            before_state={"status": before_status},
            after_state={"status": sched.status.value},
            description=f"Paused schedule for feed {sched.feed.name}",
        )

        self.db.commit()
        self.db.refresh(sched)
        return sched

    def resume_schedule(self, feed_id: uuid.UUID, current_user: CurrentUser) -> FeedSchedule:
        """Resume paused operational schedule for feed."""
        sched = self.get_schedule(feed_id)
        if sched.status == ScheduleStatusEnum.ACTIVE:
            return sched

        before_status = sched.status.value
        sched.status = ScheduleStatusEnum.ACTIVE
        sched.next_run_at = compute_next_run(sched.schedule_expression, tz_str=sched.timezone)
        sched.updated_by = current_user.user_id
        sched.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.SCHEDULE_RESUMED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="feed_schedules",
            object_id=str(sched.id),
            before_state={"status": before_status},
            after_state={"status": sched.status.value, "next_run_at": sched.next_run_at.isoformat() if sched.next_run_at else None},
            description=f"Resumed schedule for feed {sched.feed.name}",
        )

        self.db.commit()
        self.db.refresh(sched)
        return sched

    def disable_schedule(self, feed_id: uuid.UUID, current_user: CurrentUser) -> FeedSchedule:
        """Disable operational schedule for feed."""
        sched = self.get_schedule(feed_id)
        if sched.status == ScheduleStatusEnum.DISABLED:
            return sched

        before_status = sched.status.value
        sched.status = ScheduleStatusEnum.DISABLED
        sched.next_run_at = None
        sched.updated_by = current_user.user_id
        sched.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.SCHEDULE_DISABLED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="feed_schedules",
            object_id=str(sched.id),
            before_state={"status": before_status},
            after_state={"status": sched.status.value},
            description=f"Disabled schedule for feed {sched.feed.name}",
        )

        self.db.commit()
        self.db.refresh(sched)
        return sched

    def enable_schedule(self, feed_id: uuid.UUID, current_user: CurrentUser) -> FeedSchedule:
        """Enable disabled operational schedule for feed."""
        sched = self.get_schedule(feed_id)
        if sched.status == ScheduleStatusEnum.ACTIVE:
            return sched

        before_status = sched.status.value
        sched.status = ScheduleStatusEnum.ACTIVE
        sched.next_run_at = compute_next_run(sched.schedule_expression, tz_str=sched.timezone)
        sched.updated_by = current_user.user_id
        sched.version += 1
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.SCHEDULE_ENABLED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="feed_schedules",
            object_id=str(sched.id),
            before_state={"status": before_status},
            after_state={"status": sched.status.value, "next_run_at": sched.next_run_at.isoformat() if sched.next_run_at else None},
            description=f"Enabled schedule for feed {sched.feed.name}",
        )

        self.db.commit()
        self.db.refresh(sched)
        return sched
