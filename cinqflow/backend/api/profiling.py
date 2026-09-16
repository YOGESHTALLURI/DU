"""
Sample and Profiling API Endpoints — Wave 1 Slice 1
"""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import (
    require_analyst_or_engineer,
    require_any_role,
    CurrentUser,
)
from backend.services.profiling_service import ProfilingService
from backend.schemas.schema import (
    SampleFileUploadResponse,
    SampleFileListResponse,
    ProfilingRunResponse,
    ProfilingRunDetailResponse,
)

router = APIRouter()


@router.post("/feeds/{feed_id}/samples", response_model=SampleFileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_sample_file(
    feed_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Upload a representative sample file for an existing feed.
    (BUSINESS_ANALYST or ENGINEER only).
    """
    service = ProfilingService(db)
    content = await file.read()
    sample = service.upload_sample_file(
        feed_id=feed_id,
        filename=file.filename or "sample.csv",
        content=content,
        mime_type=file.content_type or "text/csv",
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )
    return sample


@router.get("/feeds/{feed_id}/samples", response_model=List[SampleFileUploadResponse])
def list_feed_samples(
    feed_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """List sample files for a given feed."""
    service = ProfilingService(db)
    return service.list_sample_files(feed_id=feed_id)


@router.post("/feeds/{feed_id}/samples/{sample_file_id}/profile", response_model=ProfilingRunResponse, status_code=status.HTTP_201_CREATED)
def start_profiling_run(
    feed_id: UUID,
    sample_file_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Execute deterministic profiling on a sample file.
    Validates server-side that sample belongs to feed.
    (BUSINESS_ANALYST or ENGINEER only).
    """
    service = ProfilingService(db)
    run = service.run_profiling(
        feed_id=feed_id,
        sample_file_id=sample_file_id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
    )
    return run


@router.get("/profiling-runs/{run_id}", response_model=ProfilingRunDetailResponse)
def get_profiling_run_details(
    run_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Get profiling run status, summary, and per-column observational facts.
    """
    service = ProfilingService(db)
    return service.get_profiling_run(run_id)


@router.get("/profiling-runs/{run_id}/paths")
def get_hierarchical_paths(
    run_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    """
    Get discovered hierarchical paths (JSONPath / dot-paths) and nested structure stats.
    """
    service = ProfilingService(db)
    paths = service.get_hierarchical_paths(run_id)
    return {"run_id": str(run_id), "count": len(paths), "paths": paths}


@router.post("/inspect-complex")
async def inspect_complex_format(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_analyst_or_engineer),
):
    """
    Direct observational inspection and path discovery of a complex file (JSON, FHIR, XML, NDJSON).
    Does not persist to database; returns discovered paths and data structure.
    """
    from backend.engine.profiler import DeterministicProfiler
    content = await file.read()
    text_content = content.decode("utf-8-sig", errors="replace")
    result = DeterministicProfiler.profile_auto(text_content)
    return result
