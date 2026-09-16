"""
API Router for Feed Dependencies, DAG Graph, and Downstream Protection Gates (Wave 1 Slice 6 - CF-V1-E8-03).
"""
import uuid
from typing import Dict, Any
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import require_engineer, require_any_role, CurrentUser
from backend.schemas.schedule import (
    FeedDependencyCreateRequest,
    FeedDependencyUpdateRequest,
    FeedDependencyResponse,
    GateCheckResult,
    DAGGraphResponse,
)
from backend.services.dependency_service import DependencyService

router = APIRouter()


@router.get("/dag", response_model=DAGGraphResponse)
def get_dag(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Retrieve the full system dependency DAG with feed nodes, edges, and readiness state."""
    service = DependencyService(db)
    return service.get_dag()


@router.get("/gate-check/{feed_id}", response_model=GateCheckResult)
def evaluate_gate_check(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Evaluate downstream protection gates for a feed without blocking pipeline run."""
    service = DependencyService(db)
    return service.evaluate_execution_gate(
        feed_id=feed_id,
        audit_on_block=False,
    )


@router.get("/feed/{feed_id}")
def get_feed_dependencies(
    feed_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """Retrieve upstream prerequisites and downstream dependents for a specific feed."""
    service = DependencyService(db)
    return service.get_dependencies_for_feed(feed_id)


@router.post("", response_model=FeedDependencyResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=FeedDependencyResponse, status_code=status.HTTP_201_CREATED)
def create_dependency(
    payload: FeedDependencyCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Create a new inter-feed dependency with server-side cycle detection (ENGINEER only)."""
    service = DependencyService(db)
    dep = service.create_dependency(payload, current_user)
    return FeedDependencyResponse(
        id=dep.id,
        downstream_feed_id=dep.downstream_feed_id,
        upstream_feed_id=dep.upstream_feed_id,
        downstream_feed_name=dep.downstream_feed.name if dep.downstream_feed else None,
        upstream_feed_name=dep.upstream_feed.name if dep.upstream_feed else None,
        dependency_type=dep.dependency_type,
        max_lag_hours=dep.max_lag_hours,
        block_on_upstream_failure=dep.block_on_upstream_failure,
        block_on_reject_file=dep.block_on_reject_file,
        block_on_unbalanced_reconciliation=dep.block_on_unbalanced_reconciliation,
        max_quarantine_rate_pct=dep.max_quarantine_rate_pct,
        is_active=dep.is_active,
        created_at=dep.created_at,
        created_by=dep.created_by,
        updated_at=dep.updated_at,
        updated_by=dep.updated_by,
        version=dep.version,
    )


@router.put("/{dep_id}", response_model=FeedDependencyResponse)
def update_dependency(
    dep_id: uuid.UUID,
    payload: FeedDependencyUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Update thresholds or active status of an existing dependency (ENGINEER only)."""
    service = DependencyService(db)
    dep = service.update_dependency(dep_id, payload, current_user)
    return FeedDependencyResponse(
        id=dep.id,
        downstream_feed_id=dep.downstream_feed_id,
        upstream_feed_id=dep.upstream_feed_id,
        downstream_feed_name=dep.downstream_feed.name if dep.downstream_feed else None,
        upstream_feed_name=dep.upstream_feed.name if dep.upstream_feed else None,
        dependency_type=dep.dependency_type,
        max_lag_hours=dep.max_lag_hours,
        block_on_upstream_failure=dep.block_on_upstream_failure,
        block_on_reject_file=dep.block_on_reject_file,
        block_on_unbalanced_reconciliation=dep.block_on_unbalanced_reconciliation,
        max_quarantine_rate_pct=dep.max_quarantine_rate_pct,
        is_active=dep.is_active,
        created_at=dep.created_at,
        created_by=dep.created_by,
        updated_at=dep.updated_at,
        updated_by=dep.updated_by,
        version=dep.version,
    )


@router.delete("/{dep_id}")
def delete_dependency(
    dep_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_engineer),
):
    """Delete a dependency edge (ENGINEER only)."""
    service = DependencyService(db)
    service.delete_dependency(dep_id, current_user)
    return {"message": "Dependency deleted successfully"}
