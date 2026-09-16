"""
Dependency Service — Wave 1 Slice 6 (CF-V1-E8-03)

Manages Feed Dependency DAGs:
- Concurrency-safe topological cycle prevention (PostgreSQL transaction advisory locking)
- Downstream Protection Policies (production batch status, quarantine rate boundaries, reconciliation, lag, REJECT_FILE)
- Full DAG and Blast Radius impact queries
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.feed import Feed, FeedStatusEnum
from backend.models.schedule import (
    FeedDependency,
    FeedSchedule,
    DependencyTypeEnum,
    ScheduleStatusEnum,
)
from backend.models.pipeline import Batch, BatchStatusEnum, BatchStage, StageStatusEnum
from backend.models.reconciliation import BatchReconciliation, ReconciliationStatusEnum
from backend.models.input_registry import QuarantineRecord, QuarantineReasonEnum
from backend.models.audit import AuditActionEnum
from backend.services.audit_service import AuditService
from backend.core.security import CurrentUser
from backend.schemas.schedule import (
    FeedDependencyCreateRequest,
    FeedDependencyUpdateRequest,
    FeedDependencyResponse,
    GateCheckResult,
    DependencyGateItem,
    DAGGraphResponse,
    DAGNode,
    DAGEdge,
)


class DependencyService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def get_dependencies_for_feed(self, feed_id: uuid.UUID) -> Dict[str, Any]:
        """Returns all upstream prerequisites and downstream dependents for a feed."""
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed {feed_id} not found")

        upstream_deps = (
            self.db.query(FeedDependency)
            .filter(FeedDependency.downstream_feed_id == feed_id)
            .all()
        )
        downstream_deps = (
            self.db.query(FeedDependency)
            .filter(FeedDependency.upstream_feed_id == feed_id)
            .all()
        )

        def to_dict(d: FeedDependency) -> FeedDependencyResponse:
            return FeedDependencyResponse(
                id=d.id,
                downstream_feed_id=d.downstream_feed_id,
                upstream_feed_id=d.upstream_feed_id,
                downstream_feed_name=d.downstream_feed.name if d.downstream_feed else None,
                upstream_feed_name=d.upstream_feed.name if d.upstream_feed else None,
                dependency_type=d.dependency_type,
                max_lag_hours=d.max_lag_hours,
                block_on_upstream_failure=d.block_on_upstream_failure,
                block_on_reject_file=d.block_on_reject_file,
                block_on_unbalanced_reconciliation=d.block_on_unbalanced_reconciliation,
                max_quarantine_rate_pct=d.max_quarantine_rate_pct,
                is_active=d.is_active,
                created_at=d.created_at,
                created_by=d.created_by,
                updated_at=d.updated_at,
                updated_by=d.updated_by,
                version=d.version,
            )

        return {
            "feed_id": feed_id,
            "feed_name": feed.name,
            "upstream_dependencies": [to_dict(d) for d in upstream_deps],
            "downstream_dependents": [to_dict(d) for d in downstream_deps],
        }

    def _find_path(self, start_id: uuid.UUID, target_id: uuid.UUID, adj: Dict[uuid.UUID, List[uuid.UUID]]) -> Optional[List[uuid.UUID]]:
        """BFS to find a directed path from start_id to target_id."""
        queue = [[start_id]]
        visited = {start_id}

        while queue:
            path = queue.pop(0)
            node = path[-1]
            if node == target_id:
                return path
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = list(path)
                    new_path.append(neighbor)
                    queue.append(new_path)
        return None

    def create_dependency(
        self,
        data: FeedDependencyCreateRequest,
        current_user: CurrentUser,
    ) -> FeedDependency:
        """Creates an inter-feed dependency with concurrency-safe cycle detection."""
        if data.downstream_feed_id == data.upstream_feed_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A feed cannot depend on itself (self-dependency prohibited)",
            )

        downstream = self.db.query(Feed).filter(Feed.id == data.downstream_feed_id).first()
        if not downstream:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Downstream feed {data.downstream_feed_id} not found")

        upstream = self.db.query(Feed).filter(Feed.id == data.upstream_feed_id).first()
        if not upstream:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Upstream feed {data.upstream_feed_id} not found")

        # Concurrency safety: acquire transaction-scoped advisory lock for DAG modification
        self.db.execute(text("SELECT pg_advisory_xact_lock(hashtext('feed_dependencies_dag_lock'))"))

        # Check existing edge
        existing = (
            self.db.query(FeedDependency)
            .filter(
                FeedDependency.downstream_feed_id == data.downstream_feed_id,
                FeedDependency.upstream_feed_id == data.upstream_feed_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Dependency already exists: Feed '{downstream.name}' already depends on '{upstream.name}'",
            )

        # Build adjacency graph of existing active dependencies: parent -> child
        # Edge u -> d means d depends on u (u must finish before d)
        all_deps = self.db.query(FeedDependency).filter(FeedDependency.is_active == True).all()
        adj: Dict[uuid.UUID, List[uuid.UUID]] = {}
        for dep in all_deps:
            adj.setdefault(dep.upstream_feed_id, []).append(dep.downstream_feed_id)

        cycle_path = self._find_path(data.downstream_feed_id, data.upstream_feed_id, adj)
        if cycle_path:
            feed_names = {f.id: f.name for f in self.db.query(Feed).filter(Feed.id.in_(cycle_path + [data.upstream_feed_id, data.downstream_feed_id])).all()}
            readable_path = " -> ".join([feed_names.get(fid, str(fid)) for fid in cycle_path])

            self.audit.emit(
                action=AuditActionEnum.DEPENDENCY_CYCLE_REJECTED,
                actor_id=current_user.user_id,
                actor_email=current_user.email,
                object_type="feed_dependencies",
                object_id=str(data.downstream_feed_id),
                after_state={
                    "downstream_feed_id": str(data.downstream_feed_id),
                    "downstream_feed_name": downstream.name,
                    "upstream_feed_id": str(data.upstream_feed_id),
                    "upstream_feed_name": upstream.name,
                    "cycle_path": [str(fid) for fid in cycle_path],
                    "readable_path": f"{upstream.name} -> {readable_path}",
                },
                description=f"Circular dependency rejected: {upstream.name} -> {readable_path}",
            )
            self.db.commit()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Circular dependency detected: Adding dependency creates cycle ({upstream.name} -> {readable_path})",
            )

        dep = FeedDependency(
            id=uuid.uuid4(),
            downstream_feed_id=data.downstream_feed_id,
            upstream_feed_id=data.upstream_feed_id,
            dependency_type=data.dependency_type,
            max_lag_hours=data.max_lag_hours,
            block_on_upstream_failure=data.block_on_upstream_failure,
            block_on_reject_file=data.block_on_reject_file,
            block_on_unbalanced_reconciliation=data.block_on_unbalanced_reconciliation,
            max_quarantine_rate_pct=data.max_quarantine_rate_pct,
            is_active=data.is_active,
            created_by=current_user.user_id,
            updated_by=current_user.user_id,
        )
        self.db.add(dep)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.DEPENDENCY_CREATED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="feed_dependencies",
            object_id=str(dep.id),
            after_state={
                "downstream_feed_id": str(dep.downstream_feed_id),
                "downstream_feed_name": downstream.name,
                "upstream_feed_id": str(dep.upstream_feed_id),
                "upstream_feed_name": upstream.name,
                "dependency_type": dep.dependency_type.value,
                "max_lag_hours": dep.max_lag_hours,
                "block_on_upstream_failure": dep.block_on_upstream_failure,
            },
            description=f"Created dependency: Feed {downstream.name} depends on {upstream.name}",
        )

        self.db.commit()
        self.db.refresh(dep)
        return dep

    def delete_dependency(self, dep_id: uuid.UUID, current_user: CurrentUser) -> None:
        """Deletes a dependency edge."""
        dep = self.db.query(FeedDependency).filter(FeedDependency.id == dep_id).first()
        if not dep:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dependency {dep_id} not found")

        downstream_name = dep.downstream_feed.name if dep.downstream_feed else str(dep.downstream_feed_id)
        upstream_name = dep.upstream_feed.name if dep.upstream_feed else str(dep.upstream_feed_id)

        before_state = {
            "downstream_feed_id": str(dep.downstream_feed_id),
            "upstream_feed_id": str(dep.upstream_feed_id),
            "dependency_type": dep.dependency_type.value,
        }

        self.db.delete(dep)
        self.db.flush()

        self.audit.emit(
            action=AuditActionEnum.DEPENDENCY_DELETED,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            object_type="feed_dependencies",
            object_id=str(dep_id),
            before_state=before_state,
            description=f"Deleted dependency: Feed {downstream_name} no longer depends on {upstream_name}",
        )

        self.db.commit()

    def update_dependency(
        self,
        dep_id: uuid.UUID,
        data: FeedDependencyUpdateRequest,
        current_user: CurrentUser,
    ) -> FeedDependency:
        """Updates thresholds or active status of a dependency."""
        dep = self.db.query(FeedDependency).filter(FeedDependency.id == dep_id).first()
        if not dep:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dependency {dep_id} not found")

        if data.dependency_type is not None:
            dep.dependency_type = data.dependency_type
        if data.max_lag_hours is not None:
            dep.max_lag_hours = data.max_lag_hours
        if data.block_on_upstream_failure is not None:
            dep.block_on_upstream_failure = data.block_on_upstream_failure
        if data.block_on_reject_file is not None:
            dep.block_on_reject_file = data.block_on_reject_file
        if data.block_on_unbalanced_reconciliation is not None:
            dep.block_on_unbalanced_reconciliation = data.block_on_unbalanced_reconciliation
        if data.max_quarantine_rate_pct is not None:
            dep.max_quarantine_rate_pct = data.max_quarantine_rate_pct
        if data.is_active is not None:
            dep.is_active = data.is_active

        dep.updated_by = current_user.user_id
        dep.version += 1
        self.db.commit()
        self.db.refresh(dep)
        return dep

    def get_dag(self) -> DAGGraphResponse:
        """Generates the full system DAG with node readiness and edges."""
        feeds = self.db.query(Feed).all()
        schedules = {s.feed_id: s for s in self.db.query(FeedSchedule).all()}
        dependencies = self.db.query(FeedDependency).all()

        nodes = []
        for f in feeds:
            sched = schedules.get(f.id)
            gate = self.evaluate_execution_gate(f.id, audit_on_block=False)
            nodes.append(
                DAGNode(
                    id=str(f.id),
                    feed_id=f.id,
                    name=f.name,
                    domain=f.domain,
                    status=f.status.value,
                    schedule_expression=sched.schedule_expression if sched else f.schedule_expression,
                    schedule_status=sched.status.value if sched else None,
                    next_run_at=sched.next_run_at if sched else None,
                    is_gate_cleared=gate.is_allowed,
                )
            )

        edges = [
            DAGEdge(
                id=str(d.id),
                source_feed_id=d.upstream_feed_id,
                target_feed_id=d.downstream_feed_id,
                dependency_type=d.dependency_type,
                is_active=d.is_active,
                max_lag_hours=d.max_lag_hours,
            )
            for d in dependencies
        ]

        return DAGGraphResponse(
            nodes=nodes,
            edges=edges,
            total_feeds=len(nodes),
            total_dependencies=len(edges),
            is_acyclic=True,
        )

    def evaluate_execution_gate(
        self,
        feed_id: uuid.UUID,
        audit_on_block: bool = True,
        actor_id: Optional[str] = None,
        actor_email: Optional[str] = None,
    ) -> GateCheckResult:
        """
        Evaluates downstream protection gates for a feed based strictly on production evidence.
        Inspects upstream production batch status, reconciliation balance, quarantine rates, and SLA lag.
        """
        feed = self.db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feed {feed_id} not found")

        active_deps = (
            self.db.query(FeedDependency)
            .filter(
                FeedDependency.downstream_feed_id == feed_id,
                FeedDependency.is_active == True,
            )
            .all()
        )

        now = datetime.now(timezone.utc)
        blocking_reasons: List[str] = []
        warnings: List[str] = []
        items_evaluated: List[DependencyGateItem] = []

        for dep in active_deps:
            u_feed = dep.upstream_feed
            u_name = u_feed.name if u_feed else str(dep.upstream_feed_id)

            # Query latest production batch for upstream feed (strictly production batches table)
            latest_batch = (
                self.db.query(Batch)
                .filter(Batch.feed_id == dep.upstream_feed_id)
                .order_by(Batch.created_at.desc())
                .first()
            )

            is_satisfied = True
            reason = None
            batch_id = latest_batch.id if latest_batch else None
            batch_status = latest_batch.status.value if latest_batch else None
            completed_at = latest_batch.completed_at if latest_batch else None
            quarantine_rate = None
            recon_status = None

            if not latest_batch:
                is_satisfied = False
                reason = f"Upstream feed '{u_name}' has never completed any pipeline run"
            else:
                # 1. Status Check
                if latest_batch.status in [
                    BatchStatusEnum.FAILED,
                    BatchStatusEnum.CANCELLED,
                    BatchStatusEnum.FAILED_RECONCILIATION,
                ]:
                    if dep.block_on_upstream_failure:
                        is_satisfied = False
                        reason = f"Upstream feed '{u_name}' latest batch ({str(latest_batch.id)[:8]}) is {latest_batch.status.value}"
                elif latest_batch.status in [BatchStatusEnum.RUNNING, BatchStatusEnum.PENDING]:
                    is_satisfied = False
                    reason = f"Upstream feed '{u_name}' is currently executing (batch {str(latest_batch.id)[:8]})"
                elif latest_batch.status == BatchStatusEnum.SUCCESS:
                    # 2. Max Lag Check
                    if dep.max_lag_hours and latest_batch.completed_at:
                        elapsed = (now - latest_batch.completed_at).total_seconds() / 3600.0
                        if elapsed > dep.max_lag_hours:
                            is_satisfied = False
                            reason = f"Upstream feed '{u_name}' run is stale ({elapsed:.1f}h ago, max allowed: {dep.max_lag_hours}h)"

                    # 3. Reconciliation Check
                    recon = (
                        self.db.query(BatchReconciliation)
                        .filter(BatchReconciliation.batch_id == latest_batch.id)
                        .first()
                    )
                    if recon:
                        recon_status = recon.status.value
                        if dep.block_on_unbalanced_reconciliation and (
                            recon.status != ReconciliationStatusEnum.PASS or not recon.balance_check_passed
                        ):
                            is_satisfied = False
                            reason = f"Upstream feed '{u_name}' latest batch reconciliation is UNBALANCED ({recon.status.value})"

                        # 4. Quarantine Rate Check (strictly greater than threshold blocks; <= passes)
                        if dep.max_quarantine_rate_pct is not None and recon.rows_in > 0:
                            rate = (recon.rows_quarantined / recon.rows_in) * 100.0
                            quarantine_rate = round(rate, 2)
                            if rate > dep.max_quarantine_rate_pct:
                                is_satisfied = False
                                reason = f"Upstream feed '{u_name}' quarantine rate ({rate:.1f}%) exceeds policy threshold ({dep.max_quarantine_rate_pct}%)"

                    # 5. REJECT_FILE Severity Check in production QuarantineRecord
                    if dep.block_on_reject_file:
                        has_rf = (
                            self.db.query(QuarantineRecord)
                            .filter(
                                QuarantineRecord.batch_id == latest_batch.id,
                                QuarantineRecord.reason_detail.like("%REJECT_FILE%"),
                            )
                            .first()
                        )
                        if has_rf:
                            is_satisfied = False
                            reason = f"Upstream feed '{u_name}' batch encountered REJECT_FILE severity data quality violations"

            blocking_reason_val = None
            warning_reason_val = None

            if not is_satisfied:
                if dep.dependency_type == DependencyTypeEnum.HARD:
                    blocking_reasons.append(reason)
                    blocking_reason_val = reason
                else:
                    warnings.append(reason)
                    warning_reason_val = reason

            items_evaluated.append(
                DependencyGateItem(
                    dependency_id=dep.id,
                    upstream_feed_id=dep.upstream_feed_id,
                    upstream_feed_name=u_name,
                    dependency_type=dep.dependency_type,
                    is_satisfied=is_satisfied,
                    blocking_reason=blocking_reason_val,
                    warning_reason=warning_reason_val,
                    last_upstream_batch_id=batch_id,
                    last_upstream_batch_status=batch_status,
                    last_upstream_completed_at=completed_at,
                    quarantine_rate_pct=quarantine_rate,
                    reconciliation_status=recon_status,
                )
            )

        is_allowed = (len(blocking_reasons) == 0)

        # Audit is strictly emitted during execution pre-flight (audit_on_block=True), never on read-only GET
        if not is_allowed and audit_on_block:
            self.audit.emit(
                action=AuditActionEnum.DEPENDENCY_GATE_BLOCKED,
                actor_id=actor_id or "SYSTEM",
                actor_email=actor_email,
                object_type="feeds",
                object_id=str(feed_id),
                after_state={
                    "feed_name": feed.name,
                    "blocking_reasons": blocking_reasons,
                },
                description=f"Downstream protection gate blocked execution for feed {feed.name}: {'; '.join(blocking_reasons)}",
            )
            self.db.commit()

        return GateCheckResult(
            feed_id=feed_id,
            feed_name=feed.name,
            is_allowed=is_allowed,
            evaluated_at=now,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            dependencies_evaluated=items_evaluated,
        )
