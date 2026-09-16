"""
Wave 2 Slice 2 Engine — Timezone-Aware File Arrival & SLA Calculation Engine (CF-V2-E12-01)
"""
import uuid
import re
import functools
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import bisect
from croniter import croniter

from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.models.feed import Feed
from backend.models.input_registry import InputRegistry
from backend.schemas.ops import ArrivalStatusEnum, OpsArrivalSlotItem

# Pre-compiled regex patterns for zero-overhead PHI sanitization
_RE_SSN_HYPHEN = re.compile(r"\d{3}-\d{2}-\d{4}")
_RE_SSN_DIGITS = re.compile(r"(?:(?<=[\W_])|^)\d{9}(?:(?=[\W_])|$)")
_RE_PHONE = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_MRN = re.compile(r"\b(?:MRN|mrn)[:\s#-]*[A-Za-z0-9]{5,15}\b")


class ArrivalEngine:
    """
    Deterministic calculation of scheduled arrival slots and SLA adherence.
    Consumes feed_schedules (recurrence and timezone) and input_registry (actual arrival).
    """

    @staticmethod
    @functools.lru_cache(maxsize=128)
    def get_safe_zoneinfo(tz_name: str) -> ZoneInfo:
        """Resolves IANA timezone string, falling back safely to UTC if unknown (cached)."""
        if not tz_name:
            return ZoneInfo("UTC")
        try:
            return ZoneInfo(tz_name.strip())
        except (ZoneInfoNotFoundError, Exception):
            return ZoneInfo("UTC")

    @classmethod
    def sanitize_filename(cls, filename: Optional[str]) -> Optional[str]:
        """
        Redacts embedded SSNs, emails, phone numbers, and sensitive patient identifiers from filenames.
        Zero PHI exposure in operational dashboards.
        """
        if not filename:
            return None
        s = _RE_SSN_HYPHEN.sub("[REDACTED_SSN]", filename)
        s = _RE_SSN_DIGITS.sub("[REDACTED_SSN]", s)
        s = _RE_PHONE.sub("[REDACTED_PHONE]", s)
        s = _RE_EMAIL.sub("[REDACTED_EMAIL]", s)
        s = _RE_MRN.sub("[REDACTED_MRN]", s)
        return s

    @classmethod
    def sanitize_operational_error(cls, error_msg: Optional[str]) -> Optional[str]:
        """Scrubs potential patient/member identifying strings from operational error messages."""
        if not error_msg:
            return None
        s = _RE_SSN_HYPHEN.sub("[REDACTED_SSN]", error_msg)
        s = _RE_SSN_DIGITS.sub("[REDACTED_SSN]", s)
        s = _RE_PHONE.sub("[REDACTED_PHONE]", s)
        s = _RE_EMAIL.sub("[REDACTED_EMAIL]", s)
        s = _RE_MRN.sub("[REDACTED_MRN]", s)
        return s

    @staticmethod
    @functools.lru_cache(maxsize=512)
    def _expand_expected_slots_cached(
        cron_expr: str,
        timezone_str: str,
        window_start_utc: datetime,
        window_end_utc: datetime,
    ) -> Tuple[datetime, ...]:
        tz = ArrivalEngine.get_safe_zoneinfo(timezone_str)
        window_start_local = window_start_utc.astimezone(tz)
        window_end_local = window_end_utc.astimezone(tz)

        base_time = window_start_local - timedelta(seconds=1)
        try:
            iter_obj = croniter(cron_expr, base_time)
        except Exception:
            return ()

        slots_utc: List[datetime] = []
        while True:
            try:
                next_local = iter_obj.get_next(datetime)
            except Exception:
                break

            if next_local > window_end_local:
                break

            next_utc = next_local.astimezone(timezone.utc)
            slots_utc.append(next_utc)

            if len(slots_utc) > 500:
                break

        return tuple(slots_utc)

    @classmethod
    def expand_expected_slots(
        cls,
        schedule: FeedSchedule,
        window_start_utc: datetime,
        window_end_utc: datetime,
    ) -> List[datetime]:
        """
        Enumerates all scheduled slot occurrence timestamps (in UTC) for a schedule within [window_start_utc, window_end_utc].
        """
        cron_expr = schedule.schedule_expression.strip() if schedule.schedule_expression else ""
        if not cron_expr or cron_expr in ["manual", "MANUAL"]:
            return []

        return list(cls._expand_expected_slots_cached(cron_expr, schedule.timezone, window_start_utc, window_end_utc))

    @classmethod
    def match_arrivals_to_slots(
        cls,
        slots: List[datetime],
        arrivals: List[InputRegistry],
        lead_window: timedelta,
        sla_grace: timedelta,
    ) -> Tuple[Dict[datetime, Optional[InputRegistry]], List[InputRegistry]]:
        """
        Matches incoming arrivals to chronological slots with strict 1:1 semantics and bounded horizons.
        Only ACCEPTED arrivals (not DUPLICATE or REJECTED) can bind to a slot.
        A slot's matching window is:
          window_start = slot - lead_window
          window_end = min(slot + sla_grace + sla_grace, next_slot) if next_slot exists else slot + sla_grace + sla_grace
        Earliest unconsumed accepted arrival binds to the slot.
        """
        valid_arrivals = [
            a for a in arrivals
            if getattr(a, "status", None) is None or getattr(a.status, "value", a.status) == "ACCEPTED"
        ]
        if not valid_arrivals:
            return {s: None for s in slots}, []

        sorted_arrivals = sorted(valid_arrivals, key=lambda a: a.detected_at)
        sorted_slots = sorted(slots)
        arrival_times = [a.detected_at for a in sorted_arrivals]

        matched_arrival_ids = set()
        matched_map: Dict[datetime, Optional[InputRegistry]] = {}

        for i, slot in enumerate(sorted_slots):
            window_start = slot - lead_window
            max_late_deadline = slot + sla_grace + sla_grace
            if i + 1 < len(sorted_slots):
                window_end = min(max_late_deadline, sorted_slots[i + 1])
            else:
                window_end = max_late_deadline

            # Fast binary search to find earliest candidate in window
            start_idx = bisect.bisect_left(arrival_times, window_start)
            matched: Optional[InputRegistry] = None
            for idx in range(start_idx, len(sorted_arrivals)):
                arr = sorted_arrivals[idx]
                if arr.detected_at > window_end:
                    break
                if arr.id in matched_arrival_ids:
                    continue
                matched = arr
                matched_arrival_ids.add(arr.id)
                break

            matched_map[slot] = matched

        unmatched = [a for a in sorted_arrivals if a.id not in matched_arrival_ids]
        return matched_map, unmatched

    @classmethod
    def eval_slot_status(
        cls,
        expected_time: datetime,
        matched_arrival: Optional[InputRegistry],
        now: datetime,
        lead_window: timedelta,
        sla_grace: timedelta,
        schedule_state: ScheduleStatusEnum,
    ) -> ArrivalStatusEnum:
        """
        Evaluates the SLA status for a given slot.
        """
        if schedule_state in [ScheduleStatusEnum.PAUSED, ScheduleStatusEnum.DISABLED]:
            if matched_arrival is None:
                return ArrivalStatusEnum.PAUSED

        sla_deadline = expected_time + sla_grace

        if matched_arrival is not None:
            if matched_arrival.detected_at <= sla_deadline:
                return ArrivalStatusEnum.ON_TIME
            else:
                return ArrivalStatusEnum.LATE
        else:
            if now <= sla_deadline:
                return ArrivalStatusEnum.EXPECTED
            else:
                return ArrivalStatusEnum.MISSED_SLA

    @classmethod
    def generate_slots_for_schedule(
        cls,
        schedule: FeedSchedule,
        feed: Feed,
        window_start_utc: datetime,
        window_end_utc: datetime,
        arrivals: List[InputRegistry],
        now_utc: Optional[datetime] = None,
        batch_lookup: Optional[Dict[uuid.UUID, Tuple[uuid.UUID, str]]] = None,
    ) -> Tuple[List[OpsArrivalSlotItem], List[InputRegistry]]:
        """
        Calculates all scheduled slots for a given feed schedule within a UTC window,
        and matches them to actual incoming files from input_registry.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        slots_utc = cls.expand_expected_slots(schedule, window_start_utc, window_end_utc)
        tz = cls.get_safe_zoneinfo(schedule.timezone)

        lead_delta = timedelta(minutes=schedule.lead_window_minutes)
        grace_delta = timedelta(minutes=schedule.sla_grace_minutes)

        matched_map, unmatched_arrivals = cls.match_arrivals_to_slots(
            slots=slots_utc,
            arrivals=arrivals,
            lead_window=lead_delta,
            sla_grace=grace_delta,
        )

        items: List[OpsArrivalSlotItem] = []
        for slot_utc in slots_utc:
            sla_deadline = slot_utc + grace_delta
            matched_file = matched_map.get(slot_utc)

            status = cls.eval_slot_status(
                expected_time=slot_utc,
                matched_arrival=matched_file,
                now=now_utc,
                lead_window=lead_delta,
                sla_grace=grace_delta,
                schedule_state=schedule.status,
            )

            # Delay calculation
            if status == ArrivalStatusEnum.LATE and matched_file is not None:
                delay_mins = max(1, int((matched_file.detected_at - sla_deadline).total_seconds() / 60))
            elif status == ArrivalStatusEnum.MISSED_SLA:
                delay_mins = max(1, int((now_utc - sla_deadline).total_seconds() / 60))
            else:
                delay_mins = 0

            sched_time_local = slot_utc.astimezone(tz)
            sla_deadline_local = sla_deadline.astimezone(tz)
            expected_at_local_str = sched_time_local.strftime("%Y-%m-%d %H:%M:%S %Z")
            sla_deadline_local_str = sla_deadline_local.strftime("%Y-%m-%d %H:%M:%S %Z")

            slot_id = f"{feed.id}_{slot_utc.strftime('%Y%m%d%H%M%S')}"

            batch_id = None
            batch_status = None
            if matched_file is not None:
                if batch_lookup is not None:
                    batch_id, batch_status = batch_lookup.get(matched_file.id, (None, None))
                elif hasattr(matched_file, "__dict__") and "batches" in matched_file.__dict__:
                    batches_rel = matched_file.__dict__.get("batches")
                    if batches_rel:
                        latest_b = batches_rel[-1]
                        batch_id = latest_b.id
                        batch_status = latest_b.status.value if hasattr(latest_b.status, "value") else str(latest_b.status)

            fp_preview = (
                matched_file.file_fingerprint[:8]
                if (matched_file and getattr(matched_file, "file_fingerprint", None))
                else None
            )

            sanitized_fname = cls.sanitize_filename(matched_file.filename) if matched_file else None

            item = OpsArrivalSlotItem(
                slot_id=slot_id,
                feed_id=feed.id,
                feed_name=feed.name,
                domain=feed.domain,
                timezone=schedule.timezone,
                cron_expression=schedule.schedule_expression.strip(),
                expected_at_utc=slot_utc,
                expected_at_local=expected_at_local_str,
                sla_deadline_utc=sla_deadline,
                sla_deadline_local=sla_deadline_local_str,
                actual_arrival_at_utc=matched_file.detected_at if matched_file else None,
                status=status,
                delay_minutes=delay_mins,
                input_registry_id=matched_file.id if matched_file else None,
                filename=sanitized_fname,
                file_fingerprint_preview=fp_preview,
                batch_id=batch_id,
                batch_status=batch_status,
            )
            items.append(item)

        return items, unmatched_arrivals
