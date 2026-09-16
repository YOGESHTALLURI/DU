"""
Wave 2 Slice 2 Operations Service — KPI Aggregations, Arrival Board & Batch Monitoring (CF-V2-E12-01, CF-V2-E12-02)
"""
import uuid
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import func, desc, or_, case
from sqlalchemy.orm import Session, joinedload, selectinload
from fastapi import HTTPException, status

from backend.models.feed import Feed, FeedStatusEnum
from backend.models.schedule import FeedSchedule, ScheduleStatusEnum
from backend.models.input_registry import InputRegistry
from backend.models.pipeline import Batch, BatchStage, BatchStatusEnum, StageStatusEnum, StageNameEnum
from backend.models.reconciliation import BatchReconciliation
from backend.models.dq_result import DQResult, DQActionTakenEnum
from backend.models.drift import SchemaDriftReport, DriftSeverityEnum, DriftStatusEnum
from backend.models.audit import AuditEvent, AuditActionEnum
from backend.schemas.ops import (
    ArrivalStatusEnum,
    OpsKpis,
    OpsHomeResponse,
    OpsArrivalSlotItem,
    OpsArrivalBoardResponse,
    OpsStageItem,
    OpsBatchMonitorItem,
    OpsMonitorListResponse,
    OpsBatchDetailResponse,
)
from backend.engine.arrival_engine import ArrivalEngine


class OpsService:
    """Service layer for Operations Control Center."""

    @staticmethod
    def sanitize_error_message(error_msg: Optional[str]) -> Optional[str]:
        """Scrubs potential patient/member identifying strings from operational error messages."""
        return ArrivalEngine.sanitize_operational_error(error_msg)

    @classmethod
    def sanitize_filename(cls, filename: Optional[str]) -> Optional[str]:
        return ArrivalEngine.sanitize_filename(filename)

    @classmethod
    def get_home_kpis(cls, db: Session, now_utc: Optional[datetime] = None) -> OpsHomeResponse:
        """
        Computes 24-hour macro health metrics for the operations home dashboard.
        Guarantees zero-division safety and complete fallback handling on empty databases.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        w_start = now_utc - timedelta(hours=24)
        w_end = now_utc

        # 1. Active feeds count
        active_feeds = db.query(func.count(Feed.id)).filter(Feed.status == FeedStatusEnum.ACTIVE).scalar() or 0

        # 2. Batches execution metrics (24h) in a single aggregation query
        batch_counts = db.query(
            func.count(Batch.id).label("total"),
            func.count(case((Batch.status == BatchStatusEnum.SUCCESS, 1))).label("success"),
            func.count(case((Batch.status.in_([BatchStatusEnum.FAILED, BatchStatusEnum.FAILED_RECONCILIATION]), 1))).label("failed"),
        ).filter(Batch.created_at >= w_start, Batch.created_at <= w_end).one()

        batches_total = batch_counts.total or 0
        batches_success = batch_counts.success or 0
        batches_failed = batch_counts.failed or 0

        # Currently running batches (unbounded by start time)
        batches_running = db.query(func.count(Batch.id)).filter(
            Batch.status == BatchStatusEnum.RUNNING
        ).scalar() or 0

        # 3. Quarantined row volume across 24h
        quarantined_rows_24h = db.query(
            func.coalesce(func.sum(BatchReconciliation.rows_quarantined), 0)
        ).join(
            Batch, BatchReconciliation.batch_id == Batch.id
        ).filter(
            Batch.created_at >= w_start, Batch.created_at <= w_end
        ).scalar() or 0

        # 4. Active drift alerts in a single aggregation query
        drift_counts = db.query(
            func.count(case((SchemaDriftReport.drift_severity == DriftSeverityEnum.BREAKING, 1))).label("breaking"),
            func.count(case((SchemaDriftReport.drift_severity == DriftSeverityEnum.NON_BREAKING, 1))).label("non_breaking"),
        ).filter(SchemaDriftReport.status == DriftStatusEnum.DETECTED).one()

        breaking_drift_count = drift_counts.breaking or 0
        non_breaking_drift_count = drift_counts.non_breaking or 0
        unack_drift_total = breaking_drift_count + non_breaking_drift_count

        # 5. SLA Attainment Percentage across 24h scheduled slots
        schedules = (
            db.query(FeedSchedule)
            .join(Feed)
            .filter(
                Feed.status == FeedStatusEnum.ACTIVE,
                FeedSchedule.status == ScheduleStatusEnum.ACTIVE,
            )
            .all()
        )
        slots_on_time = 0
        slots_late = 0
        slots_missed = 0

        if schedules:
            active_feed_ids = [s.feed_id for s in schedules]
            # Bulk query arrivals for all active feeds in a single database round-trip (pre-sorted)
            arrivals_bulk = (
                db.query(InputRegistry.id, InputRegistry.feed_id, InputRegistry.detected_at, InputRegistry.status)
                .filter(
                    InputRegistry.feed_id.in_(active_feed_ids),
                    InputRegistry.status == "ACCEPTED",
                    InputRegistry.detected_at >= (w_start - timedelta(hours=6)),
                    InputRegistry.detected_at <= (w_end + timedelta(hours=6)),
                )
                .order_by(InputRegistry.detected_at.asc())
                .all()
            )
            arrivals_by_feed = defaultdict(list)
            for arr in arrivals_bulk:
                arrivals_by_feed[arr.feed_id].append(arr)

            for sched in schedules:
                slots = ArrivalEngine.expand_expected_slots(sched, w_start, w_end)
                if not slots:
                    continue
                feed_arrivals = arrivals_by_feed.get(sched.feed_id, [])
                lead_delta = timedelta(minutes=sched.lead_window_minutes)
                grace_delta = timedelta(minutes=sched.sla_grace_minutes)

                matched_map, _ = ArrivalEngine.match_arrivals_to_slots(
                    slots=slots,
                    arrivals=feed_arrivals,
                    lead_window=lead_delta,
                    sla_grace=grace_delta,
                )

                for slot_utc in slots:
                    matched_file = matched_map.get(slot_utc)
                    st = ArrivalEngine.eval_slot_status(
                        expected_time=slot_utc,
                        matched_arrival=matched_file,
                        now=now_utc,
                        lead_window=lead_delta,
                        sla_grace=grace_delta,
                        schedule_state=sched.status,
                    )
                    if st == ArrivalStatusEnum.ON_TIME:
                        slots_on_time += 1
                    elif st == ArrivalStatusEnum.LATE:
                        slots_late += 1
                    elif st == ArrivalStatusEnum.MISSED_SLA:
                        slots_missed += 1

        evaluated_slots = slots_on_time + slots_late + slots_missed
        if evaluated_slots == 0:
            sla_pct = 100.0
        else:
            sla_pct = round((slots_on_time / evaluated_slots) * 100.0, 1)

        kpis = OpsKpis(
            active_feeds=active_feeds,
            batches_24h_total=batches_total,
            batches_24h_success=batches_success,
            batches_24h_failed=batches_failed,
            batches_running=batches_running,
            sla_attainment_pct=sla_pct,
            quarantined_rows_24h=int(quarantined_rows_24h),
            unacknowledged_drift_alerts=unack_drift_total,
            breaking_drift_count=breaking_drift_count,
            non_breaking_drift_count=non_breaking_drift_count,
        )

        return OpsHomeResponse(window_start=w_start, window_end=w_end, kpis=kpis)

    @classmethod
    def get_arrivals_board(
        cls,
        db: Session,
        horizon: str = "today",
        window_hours: Optional[int] = None,
        status_filter: Optional[ArrivalStatusEnum] = None,
        feed_id: Optional[uuid.UUID] = None,
        now_utc: Optional[datetime] = None,
    ) -> OpsArrivalBoardResponse:
        """
        Calculates and returns the File-Arrival Board for expected vs actual arrivals.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        # Establish query window
        if window_hours is not None:
            w_start = now_utc - timedelta(hours=window_hours)
            w_end = now_utc + timedelta(hours=window_hours)
        elif horizon == "24h":
            w_start = now_utc - timedelta(hours=24)
            w_end = now_utc
        elif horizon == "next24h":
            w_start = now_utc
            w_end = now_utc + timedelta(hours=24)
        else:  # "today" default: midnight to midnight UTC
            w_start = datetime(now_utc.year, now_utc.month, now_utc.day, 0, 0, 0, tzinfo=timezone.utc)
            w_end = w_start + timedelta(days=1)

        # Query schedules with feeds joined in a single query
        sched_query = db.query(FeedSchedule).join(Feed).options(joinedload(FeedSchedule.feed))
        if feed_id:
            sched_query = sched_query.filter(FeedSchedule.feed_id == feed_id)
        schedules = sched_query.all()

        # Bulk query all arrivals across relevant feeds in a single query (pre-sorted, no batches upfront)
        arr_query = (
            db.query(InputRegistry)
            .options(joinedload(InputRegistry.feed))
            .filter(
                InputRegistry.detected_at >= (w_start - timedelta(hours=6)),
                InputRegistry.detected_at <= (w_end + timedelta(hours=6)),
            )
            .order_by(InputRegistry.detected_at.asc())
        )
        if feed_id:
            arr_query = arr_query.filter(InputRegistry.feed_id == feed_id)

        all_incoming_arrivals = arr_query.all()
        arrivals_by_feed = defaultdict(list)
        for arr in all_incoming_arrivals:
            arrivals_by_feed[arr.feed_id].append(arr)

        all_slots: List[OpsArrivalSlotItem] = []
        all_unmatched: List[InputRegistry] = []

        for sched in schedules:
            feed = sched.feed
            feed_arrivals = arrivals_by_feed.get(feed.id, [])

            feed_slots, unmatched = ArrivalEngine.generate_slots_for_schedule(
                schedule=sched,
                feed=feed,
                window_start_utc=w_start,
                window_end_utc=w_end,
                arrivals=feed_arrivals,
                now_utc=now_utc,
            )
            all_slots.extend(feed_slots)

        # Unscheduled arrivals in [w_start, w_end] (files not matched to any scheduled slot)
        already_matched_ids = {s.input_registry_id for s in all_slots if s.input_registry_id}
        unscheduled_arrivals = [
            arr for arr in all_incoming_arrivals
            if arr.id not in already_matched_ids and w_start <= arr.detected_at <= w_end
        ]

        # Convert unmatched arrivals into UNSCHEDULED_ARRIVAL slot items
        for u_arr in unscheduled_arrivals:
            feed_name = u_arr.feed.name if u_arr.feed else "Unknown"
            feed_domain = u_arr.feed.domain if u_arr.feed else "UNKNOWN"

            u_item = OpsArrivalSlotItem(
                slot_id=f"unscheduled_{u_arr.id}",
                feed_id=u_arr.feed_id,
                feed_name=feed_name,
                domain=feed_domain,
                timezone="UTC",
                cron_expression="manual",
                expected_at_utc=u_arr.detected_at,
                expected_at_local=u_arr.detected_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                sla_deadline_utc=u_arr.detected_at,
                sla_deadline_local=u_arr.detected_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                actual_arrival_at_utc=u_arr.detected_at,
                status=ArrivalStatusEnum.UNSCHEDULED_ARRIVAL,
                delay_minutes=0,
                input_registry_id=u_arr.id,
                filename=cls.sanitize_filename(u_arr.filename),
                file_fingerprint_preview=u_arr.file_fingerprint[:8] if u_arr.file_fingerprint else None,
                batch_id=None,
                batch_status=None,
            )
            all_slots.append(u_item)

        # Bulk fetch batches ONLY for items with an arrival to eliminate massive eager load overhead
        target_input_ids = [s.input_registry_id for s in all_slots if s.input_registry_id]
        if target_input_ids:
            batches_found = (
                db.query(Batch.input_registry_id, Batch.id, Batch.status)
                .filter(Batch.input_registry_id.in_(target_input_ids))
                .all()
            )
            batch_lookup = {
                b_in_id: (b_id, b_st.value if hasattr(b_st, "value") else str(b_st))
                for b_in_id, b_id, b_st in batches_found
            }
            for s in all_slots:
                if s.input_registry_id and s.input_registry_id in batch_lookup:
                    s.batch_id, s.batch_status = batch_lookup[s.input_registry_id]

        # Apply status filter if provided
        if status_filter:
            all_slots = [s for s in all_slots if s.status == status_filter]

        # Sort slots by expected_at_utc descending
        all_slots.sort(key=lambda s: s.expected_at_utc, reverse=True)

        on_time = sum(1 for s in all_slots if s.status == ArrivalStatusEnum.ON_TIME)
        late = sum(1 for s in all_slots if s.status == ArrivalStatusEnum.LATE)
        missed = sum(1 for s in all_slots if s.status == ArrivalStatusEnum.MISSED_SLA)
        expected = sum(1 for s in all_slots if s.status == ArrivalStatusEnum.EXPECTED)

        return OpsArrivalBoardResponse(
            horizon=horizon,
            total_slots=len(all_slots),
            on_time_count=on_time,
            late_count=late,
            missed_count=missed,
            expected_count=expected,
            items=all_slots,
        )

    @classmethod
    def get_batch_monitor(
        cls,
        db: Session,
        page: int = 1,
        limit: int = 25,
        feed_id: Optional[uuid.UUID] = None,
        status: Optional[BatchStatusEnum] = None,
        stage_status: Optional[StageStatusEnum] = None,
        has_violations: Optional[bool] = None,
        time_range: Optional[str] = "24h",
        now_utc: Optional[datetime] = None,
    ) -> OpsMonitorListResponse:
        """
        Returns paginated pipeline batches with stage progression, durations, and DQ indicators.
        Avoids N+1 query performance penalties through selectinload / joinedload.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        # Base filter conditions
        filters = []
        if feed_id:
            filters.append(Batch.feed_id == feed_id)
        if status:
            filters.append(Batch.status == status)
        if time_range:
            range_hours = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}.get(time_range, 24)
            cutoff = now_utc - timedelta(hours=range_hours)
            filters.append(Batch.created_at >= cutoff)

        if stage_status:
            total = db.query(func.count(func.distinct(Batch.id))).join(Batch.stages).filter(*filters, BatchStage.status == stage_status).scalar() or 0
        else:
            total = db.query(func.count(Batch.id)).filter(*filters).scalar() or 0

        # Paginate with index-backed ordering and eager-loaded relations
        query = db.query(Batch).options(
            joinedload(Batch.feed),
            joinedload(Batch.input_registry),
            selectinload(Batch.stages),
            selectinload(Batch.reconciliation),
        ).filter(*filters)
        if stage_status:
            query = query.join(Batch.stages).filter(BatchStage.status == stage_status).distinct()

        batches = query.order_by(desc(Batch.created_at)).offset((page - 1) * limit).limit(limit).all()

        items: List[OpsBatchMonitorItem] = []
        batch_ids = [b.id for b in batches]

        # Bulk prefetch DQ Results and Schema Drift Reports to prevent N+1 queries
        dq_results_by_batch: Dict[uuid.UUID, List[DQResult]] = {}
        if batch_ids:
            all_dq = db.query(DQResult).filter(DQResult.batch_id.in_(batch_ids)).all()
            for dqr in all_dq:
                dq_results_by_batch.setdefault(dqr.batch_id, []).append(dqr)

        drift_by_batch: Dict[uuid.UUID, SchemaDriftReport] = {}
        if batch_ids:
            all_drift = db.query(SchemaDriftReport).filter(SchemaDriftReport.batch_id.in_(batch_ids)).all()
            for dr in all_drift:
                drift_by_batch[dr.batch_id] = dr

        for b in batches:
            # Stages progression & duration calculation
            stage_items: List[OpsStageItem] = []
            for st in sorted(b.stages, key=lambda s: s.stage_order):
                duration_ms = 0
                if st.status == StageStatusEnum.SUCCESS or st.status == StageStatusEnum.FAILED:
                    if st.completed_at and st.started_at:
                        duration_ms = max(0, int((st.completed_at - st.started_at).total_seconds() * 1000))
                elif st.status == StageStatusEnum.RUNNING:
                    if st.started_at:
                        duration_ms = max(0, int((now_utc - st.started_at).total_seconds() * 1000))

                stage_items.append(
                    OpsStageItem(
                        stage_name=st.stage_name.value,
                        stage_order=st.stage_order,
                        status=st.status.value,
                        started_at=st.started_at,
                        completed_at=st.completed_at,
                        duration_ms=duration_ms,
                        rows_in=st.rows_in or 0,
                        rows_out=st.rows_out or 0,
                        rows_quarantined=st.rows_quarantined or 0,
                        rows_dropped=st.rows_dropped or 0,
                        error_message=cls.sanitize_error_message(st.error_message),
                    )
                )

            # Total batch duration
            total_duration_ms = 0
            if b.status in [BatchStatusEnum.SUCCESS, BatchStatusEnum.FAILED, BatchStatusEnum.FAILED_RECONCILIATION]:
                if b.completed_at and b.started_at:
                    total_duration_ms = max(0, int((b.completed_at - b.started_at).total_seconds() * 1000))
            elif b.status == BatchStatusEnum.RUNNING and b.started_at:
                total_duration_ms = max(0, int((now_utc - b.started_at).total_seconds() * 1000))

            # DQ Summary for this batch
            b_dq_list = dq_results_by_batch.get(b.id, [])
            has_quar = any(dqr.action_taken == DQActionTakenEnum.QUARANTINED_ROWS for dqr in b_dq_list)
            has_abort = any(dqr.action_taken == DQActionTakenEnum.BATCH_ABORTED for dqr in b_dq_list)

            if has_abort:
                dq_action = "BATCH_ABORTED"
            elif has_quar:
                dq_action = "QUARANTINED_ROWS"
            elif any(dqr.action_taken in [DQActionTakenEnum.LOGGED_WARNING, DQActionTakenEnum.LOGGED_INFO] for dqr in b_dq_list):
                dq_action = "LOGGED_WARNING"
            elif b_dq_list:
                dq_action = "PASSED"
            else:
                dq_action = "NO_RULES"

            # Drift Summary for this batch
            b_drift = drift_by_batch.get(b.id)
            has_drift = b_drift is not None
            drift_sev = b_drift.drift_severity.value if b_drift else None

            # Reconciliation
            recon_status = b.reconciliation.status.value if b.reconciliation else "PENDING"

            item = OpsBatchMonitorItem(
                batch_id=b.id,
                feed_id=b.feed_id,
                feed_name=b.feed.name if b.feed else "Unknown",
                domain=b.feed.domain if b.feed else "UNKNOWN",
                filename=cls.sanitize_filename(b.input_registry.filename) if b.input_registry else None,
                batch_status=b.status.value,
                created_at=b.created_at,
                started_at=b.started_at,
                completed_at=b.completed_at,
                total_duration_ms=total_duration_ms,
                stages=stage_items,
                dq_action=dq_action,
                has_quarantined_rows=has_quar,
                has_drift=has_drift,
                drift_severity=drift_sev,
                reconciliation_status=recon_status,
                error_message=cls.sanitize_error_message(b.error_message),
            )
            items.append(item)

        if has_violations is True:
            items = [it for it in items if it.has_quarantined_rows or it.has_drift or it.dq_action == "BATCH_ABORTED"]
        elif has_violations is False:
            items = [it for it in items if not it.has_quarantined_rows and not it.has_drift and it.dq_action != "BATCH_ABORTED"]

        return OpsMonitorListResponse(
            total=total,
            page=page,
            limit=limit,
            items=items,
        )

    @classmethod
    def get_batch_detail(cls, db: Session, batch_id: uuid.UUID, now_utc: Optional[datetime] = None) -> OpsBatchDetailResponse:
        """Deep drill-down details for a single batch."""
        res_list = cls.get_batch_monitor(db=db, page=1, limit=1, feed_id=None, now_utc=now_utc)
        batch = db.query(Batch).options(
            joinedload(Batch.feed),
            joinedload(Batch.input_registry),
            selectinload(Batch.stages),
            selectinload(Batch.reconciliation),
        ).filter(Batch.id == batch_id).first()

        if not batch:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Batch {batch_id} not found")

        # Reuse monitor item builder
        monitor_resp = cls.get_batch_monitor(db=db, page=1, limit=1, status=None, time_range=None, now_utc=now_utc)
        # Directly construct from single batch
        b_item_list = cls.get_batch_monitor(db=db, page=1, limit=1, feed_id=batch.feed_id, now_utc=now_utc).items
        target_item = next((it for it in b_item_list if it.batch_id == batch_id), None)
        if not target_item:
            # Fallback if outside default window
            stages_items: List[OpsStageItem] = []
            for st in sorted(batch.stages, key=lambda s: s.stage_order):
                duration_ms = 0
                if st.completed_at and st.started_at:
                    duration_ms = max(0, int((st.completed_at - st.started_at).total_seconds() * 1000))
                stages_items.append(
                    OpsStageItem(
                        stage_name=st.stage_name.value,
                        stage_order=st.stage_order,
                        status=st.status.value,
                        started_at=st.started_at,
                        completed_at=st.completed_at,
                        duration_ms=duration_ms,
                        rows_in=st.rows_in or 0,
                        rows_out=st.rows_out or 0,
                        rows_quarantined=st.rows_quarantined or 0,
                        rows_dropped=st.rows_dropped or 0,
                        error_message=cls.sanitize_error_message(st.error_message),
                    )
                )
            target_item = OpsBatchMonitorItem(
                batch_id=batch.id,
                feed_id=batch.feed_id,
                feed_name=batch.feed.name,
                domain=batch.feed.domain,
                filename=cls.sanitize_filename(batch.input_registry.filename) if batch.input_registry else None,
                batch_status=batch.status.value,
                created_at=batch.created_at,
                started_at=batch.started_at,
                completed_at=batch.completed_at,
                total_duration_ms=0,
                stages=stages_items,
                dq_action="NO_RULES",
                has_quarantined_rows=False,
                has_drift=False,
                drift_severity=None,
                reconciliation_status="PENDING",
                error_message=cls.sanitize_error_message(batch.error_message),
            )

        recon_dict = None
        if batch.reconciliation:
            recon_dict = {
                "rows_in": batch.reconciliation.rows_in,
                "rows_silver_raw": batch.reconciliation.rows_silver_raw,
                "rows_quarantined": batch.reconciliation.rows_quarantined,
                "rows_dropped": batch.reconciliation.rows_dropped,
                "balance_check_passed": batch.reconciliation.balance_check_passed,
                "status": batch.reconciliation.status.value,
                "discrepancy": batch.reconciliation.discrepancy,
            }

        # DQ Summary
        dq_results = db.query(DQResult).filter(DQResult.batch_id == batch_id).all()
        dq_summary = None
        if dq_results:
            dq_summary = {
                "total_rules": len(dq_results),
                "total_violations": sum(r.failed_rows for r in dq_results),
                "rules": [
                    {
                        "rule_version_id": str(r.rule_version_id),
                        "total_evaluated": r.total_rows_evaluated,
                        "passed_rows": r.passed_rows,
                        "failed_rows": r.failed_rows,
                        "pass_rate": float(r.pass_rate),
                        "action_taken": r.action_taken.value,
                        "duration_ms": r.execution_duration_ms,
                    }
                    for r in dq_results
                ],
            }

        # Drift Report
        drift_rep = db.query(SchemaDriftReport).filter(SchemaDriftReport.batch_id == batch_id).first()
        drift_dict = None
        if drift_rep:
            drift_dict = {
                "drift_severity": drift_rep.drift_severity.value,
                "status": drift_rep.status.value,
                "missing_fields": drift_rep.missing_fields,
                "unexpected_fields": drift_rep.unexpected_fields,
                "detected_delimiter": drift_rep.detected_delimiter,
            }

        return OpsBatchDetailResponse(
            **target_item.model_dump(),
            reconciliation=recon_dict,
            dq_summary=dq_summary,
            drift_report=drift_dict,
        )
