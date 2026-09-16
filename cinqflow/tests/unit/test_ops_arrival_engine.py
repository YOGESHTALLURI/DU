import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from backend.engine.arrival_engine import ArrivalEngine
from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.models.input_registry import InputRegistry, InputStatusEnum
from backend.schemas.ops import ArrivalStatusEnum


def make_schedule(
    cron="0 8 * * *",
    tz="UTC",
    sla_grace=60,
    lead_window=120,
    status=ScheduleStatusEnum.ACTIVE,
    feed_id=None,
):
    if not feed_id:
        feed_id = uuid.uuid4()
    sched = FeedSchedule(
        id=uuid.uuid4(),
        feed_id=feed_id,
        schedule_expression=cron,
        timezone=tz,
        sla_grace_minutes=sla_grace,
        lead_window_minutes=lead_window,
        status=status,
        created_by="test",
        updated_by="test",
    )
    return sched


def test_arrival_one_to_one_slot_assignment():
    """Confirms one arrival binds to at most one slot and is never assigned to multiple slots."""
    sched = make_schedule()
    slot1 = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
    slot2 = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)

    arr = InputRegistry(
        id=uuid.uuid4(),
        feed_id=sched.feed_id,
        filename="single_arrival.csv",
        file_path="/data/landing/single_arrival.csv",
        file_size_bytes=1024,
        file_fingerprint="fp_single_1",
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime(2026, 9, 6, 7, 30, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )

    matched, remaining = ArrivalEngine.match_arrivals_to_slots(
        slots=[slot1, slot2],
        arrivals=[arr],
        lead_window=timedelta(minutes=120),
        sla_grace=timedelta(minutes=60),
    )

    # Bound to slot1, NOT slot2
    assert matched[slot1] == arr
    assert matched[slot2] is None
    assert len(remaining) == 0


def test_multiple_arrivals_for_single_slot():
    """Earliest accepted file satisfies the slot; second arrival in the same window remains unconsumed."""
    sched = make_schedule()
    slot = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)

    arr_first = InputRegistry(
        id=uuid.uuid4(),
        feed_id=sched.feed_id,
        filename="first.csv",
        file_path="/data/landing/first.csv",
        file_size_bytes=1024,
        file_fingerprint="fp_first",
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime(2026, 9, 6, 7, 15, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )

    arr_second = InputRegistry(
        id=uuid.uuid4(),
        feed_id=sched.feed_id,
        filename="second.csv",
        file_path="/data/landing/second.csv",
        file_size_bytes=1024,
        file_fingerprint="fp_second",
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime(2026, 9, 6, 7, 45, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )

    matched, remaining = ArrivalEngine.match_arrivals_to_slots(
        slots=[slot],
        arrivals=[arr_second, arr_first],  # pass unordered
        lead_window=timedelta(minutes=120),
        sla_grace=timedelta(minutes=60),
    )

    assert matched[slot] == arr_first
    assert arr_second in remaining


def test_duplicate_fingerprint_rejection_behavior():
    """Files rejected with status=DUPLICATE are ignored and do not satisfy slots."""
    sched = make_schedule()
    slot = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)

    arr_dup = InputRegistry(
        id=uuid.uuid4(),
        feed_id=sched.feed_id,
        filename="dup.csv",
        file_path="/data/landing/dup.csv",
        file_size_bytes=1024,
        file_fingerprint="fp_duplicate",
        status=InputStatusEnum.DUPLICATE,
        registered_by="test",
        detected_at=datetime(2026, 9, 6, 7, 30, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )

    matched, remaining = ArrivalEngine.match_arrivals_to_slots(
        slots=[slot],
        arrivals=[arr_dup],
        lead_window=timedelta(minutes=120),
        sla_grace=timedelta(minutes=60),
    )

    assert matched[slot] is None


def test_overlapping_schedule_windows_deterministic_resolution():
    """When schedule slot windows overlap, the earliest scheduled slot wins deterministically."""
    slot1 = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
    slot2 = datetime(2026, 9, 6, 9, 0, tzinfo=timezone.utc)

    # File arrived at 8:15 UTC (inside slot1's grace and slot2's lead window)
    arr = InputRegistry(
        id=uuid.uuid4(),
        feed_id=uuid.uuid4(),
        filename="overlap.csv",
        file_path="/data/landing/overlap.csv",
        file_size_bytes=1024,
        file_fingerprint="fp_overlap",
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime(2026, 9, 6, 8, 15, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )

    matched, remaining = ArrivalEngine.match_arrivals_to_slots(
        slots=[slot1, slot2],
        arrivals=[arr],
        lead_window=timedelta(minutes=120),
        sla_grace=timedelta(minutes=60),
    )

    # Earliest slot (slot1) wins
    assert matched[slot1] == arr
    assert matched[slot2] is None


def test_late_arrival_bounded_by_next_slot():
    """Late arrival after the next slot's lead window start is bounded and cannot match the older slot."""
    slot1 = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
    slot2 = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    # slot2 lead window start is 12:00 - 120m = 10:00 UTC
    # File arrived at 10:15 UTC (after slot1 deadline + next slot lead start)

    arr = InputRegistry(
        id=uuid.uuid4(),
        feed_id=uuid.uuid4(),
        filename="bounded.csv",
        file_path="/data/landing/bounded.csv",
        file_size_bytes=1024,
        file_fingerprint="fp_bounded",
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=datetime(2026, 9, 6, 10, 15, tzinfo=timezone.utc),
        created_by="test",
        updated_by="test",
    )

    matched, remaining = ArrivalEngine.match_arrivals_to_slots(
        slots=[slot1, slot2],
        arrivals=[arr],
        lead_window=timedelta(minutes=120),
        sla_grace=timedelta(minutes=60),
    )

    # Does NOT match slot1 because window_end is capped by slot2's start
    assert matched[slot1] is None
    # Matches slot2 because 10:15 is inside slot2's lead window [10:00, 13:00]
    assert matched[slot2] == arr


def test_eval_slot_all_sla_states():
    """Validates exact transition points for EXPECTED, ON_TIME, LATE, and MISSED_SLA."""
    expected = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
    lead = timedelta(minutes=120)
    grace = timedelta(minutes=60)
    deadline = expected + grace

    # 1. EXPECTED: now before deadline, no file
    s_exp = ArrivalEngine.eval_slot_status(
        expected_time=expected,
        matched_arrival=None,
        now=expected - timedelta(minutes=30),
        lead_window=lead,
        sla_grace=grace,
        schedule_state=ScheduleStatusEnum.ACTIVE,
    )
    assert s_exp == ArrivalStatusEnum.EXPECTED

    # 2. MISSED_SLA: now after deadline, no file
    s_missed = ArrivalEngine.eval_slot_status(
        expected_time=expected,
        matched_arrival=None,
        now=deadline + timedelta(minutes=5),
        lead_window=lead,
        sla_grace=grace,
        schedule_state=ScheduleStatusEnum.ACTIVE,
    )
    assert s_missed == ArrivalStatusEnum.MISSED_SLA

    # 3. ON_TIME: file arrived exactly at deadline
    arr_on_time = InputRegistry(
        id=uuid.uuid4(),
        feed_id=uuid.uuid4(),
        filename="on_time.csv",
        file_path="/data/landing/on_time.csv",
        file_size_bytes=100,
        file_fingerprint="fp_ontime",
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=deadline,
        created_by="test",
        updated_by="test",
    )
    s_ontime = ArrivalEngine.eval_slot_status(
        expected_time=expected,
        matched_arrival=arr_on_time,
        now=deadline + timedelta(hours=1),
        lead_window=lead,
        sla_grace=grace,
        schedule_state=ScheduleStatusEnum.ACTIVE,
    )
    assert s_ontime == ArrivalStatusEnum.ON_TIME

    # 4. LATE: file arrived +1 second after deadline
    arr_late = InputRegistry(
        id=uuid.uuid4(),
        feed_id=uuid.uuid4(),
        filename="late.csv",
        file_path="/data/landing/late.csv",
        file_size_bytes=100,
        file_fingerprint="fp_late",
        status=InputStatusEnum.ACCEPTED,
        registered_by="test",
        detected_at=deadline + timedelta(seconds=1),
        created_by="test",
        updated_by="test",
    )
    s_late = ArrivalEngine.eval_slot_status(
        expected_time=expected,
        matched_arrival=arr_late,
        now=deadline + timedelta(hours=1),
        lead_window=lead,
        sla_grace=grace,
        schedule_state=ScheduleStatusEnum.ACTIVE,
    )
    assert s_late == ArrivalStatusEnum.LATE


def test_timezone_conversion_and_display():
    """Verify schedule in America/New_York (UTC-4 in Sep) correctly handles local time and UTC conversion."""
    ny_tz = "America/New_York"
    cron = "0 8 * * *"  # 8 AM NY time
    sched = make_schedule(cron=cron, tz=ny_tz)

    start_window = datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc)
    end_window = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)

    slots = ArrivalEngine.expand_expected_slots(sched, start_window, end_window)
    assert len(slots) >= 1
    # 8 AM EDT is 12:00 PM (noon) UTC
    slot_utc = slots[0]
    assert slot_utc.hour == 12
    assert slot_utc.tzinfo == timezone.utc


def test_dst_transition_slot_expansion():
    """Verify DST transition week produces expected occurrences without crashing or jumping."""
    # US Fall transition: first Sunday in November (Nov 1, 2026)
    sched = make_schedule(cron="30 2 * * *", tz="America/New_York")
    start_window = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
    end_window = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)

    slots = ArrivalEngine.expand_expected_slots(sched, start_window, end_window)
    assert len(slots) >= 2
    for slot in slots:
        assert slot.tzinfo == timezone.utc


def test_invalid_timezone_safe_fallback():
    """Validates unknown/invalid IANA string safely defaults to UTC without unhandled exceptions."""
    tz = ArrivalEngine.get_safe_zoneinfo("Invalid/NonExistent_Zone")
    assert tz == ZoneInfo("UTC")

    tz_empty = ArrivalEngine.get_safe_zoneinfo("")
    assert tz_empty == ZoneInfo("UTC")


def test_paused_and_disabled_schedule_status():
    """Paused and disabled schedules return PAUSED status for slot if no arrival matched."""
    expected_time = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)

    status_paused = ArrivalEngine.eval_slot_status(
        expected_time=expected_time,
        matched_arrival=None,
        now=now,
        lead_window=timedelta(minutes=120),
        sla_grace=timedelta(minutes=60),
        schedule_state=ScheduleStatusEnum.PAUSED,
    )
    assert status_paused == ArrivalStatusEnum.PAUSED

    status_disabled = ArrivalEngine.eval_slot_status(
        expected_time=expected_time,
        matched_arrival=None,
        now=now,
        lead_window=timedelta(minutes=120),
        sla_grace=timedelta(minutes=60),
        schedule_state=ScheduleStatusEnum.DISABLED,
    )
    assert status_disabled == ArrivalStatusEnum.PAUSED
