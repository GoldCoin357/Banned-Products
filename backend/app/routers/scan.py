"""
Router: Scan job management — trigger and monitor platform scans.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..models.recall import RecalledProduct
from ..models.listing import ScanJob
from ..services.scan_service import run_scan, run_all_platforms_scan
from ..services.scrapers import PLATFORM_SCRAPERS

router = APIRouter(prefix="/api/scans", tags=["scans"])


class ScanJobOut(BaseModel):
    id: int
    platform: str
    status: str
    recall_id: int | None
    listings_scanned: int
    listings_detected: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class ScanRequest(BaseModel):
    platform: str | None = None          # None = all platforms
    recall_id: int | None = None         # None = all active recalls
    max_results: int = 50
    auto_submit_esafe: bool = False


# ---------- Endpoints ----------

@router.get("/platforms", summary="List available scraper platforms")
def list_platforms():
    return {"platforms": list(PLATFORM_SCRAPERS.keys())}


@router.get("/trigger", include_in_schema=False)
def trigger_method_hint():
    raise HTTPException(status_code=405, detail="Use POST /api/scans/trigger to start a scan")


@router.post("/trigger", summary="Trigger a new scan job")
async def trigger_scan(
    payload: ScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger a scan for one or all platforms against one or all active recalls.
    Scans run in the background; use GET /api/scans to monitor progress.
    """
    platforms = [payload.platform] if payload.platform else list(PLATFORM_SCRAPERS.keys())
    if payload.platform and payload.platform not in PLATFORM_SCRAPERS:
        raise HTTPException(status_code=422, detail=f"Unknown platform: {payload.platform}")

    # Resolve recalls
    if payload.recall_id:
        recall = db.query(RecalledProduct).filter(RecalledProduct.id == payload.recall_id).first()
        if not recall:
            raise HTTPException(status_code=404, detail="Recall not found")
        recalls = [recall]
    else:
        recalls = db.query(RecalledProduct).filter(RecalledProduct.is_active == True).all()

    if not recalls:
        return {"message": "No active recalls found — sync CPSC data first", "platforms": [], "recall_count": 0}

    async def _scan_task(platform: str, recall_id: int) -> None:
        task_db = SessionLocal()
        try:
            task_recall = task_db.query(RecalledProduct).filter(RecalledProduct.id == recall_id).first()
            if task_recall:
                await run_scan(
                    db=task_db,
                    platform=platform,
                    recall=task_recall,
                    max_results=payload.max_results,
                    auto_submit_esafe=payload.auto_submit_esafe,
                )
        finally:
            task_db.close()

    # Queue background tasks
    job_count = 0
    for recall in recalls:
        for platform in platforms:
            background_tasks.add_task(_scan_task, platform, recall.id)
            job_count += 1

    return {
        "message": f"Queued {job_count} scan job(s) in the background",
        "platforms": platforms,
        "recall_count": len(recalls),
    }


@router.get("/", summary="List scan jobs")
def list_scans(
    platform: str = Query("", description="Filter by platform"),
    status: str = Query("", description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(ScanJob)
    if platform:
        q = q.filter(ScanJob.platform == platform)
    if status:
        q = q.filter(ScanJob.status == status)

    total = q.count()
    results = q.order_by(ScanJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": [ScanJobOut.from_orm(j) for j in results],
    }


@router.get("/{job_id}", response_model=ScanJobOut)
def get_scan(job_id: int, db: Session = Depends(get_db)):
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")
    return job


@router.delete("/", summary="Delete all scan jobs")
def delete_all_scans(db: Session = Depends(get_db)):
    count = db.query(ScanJob).delete()
    db.commit()
    return {"message": f"Deleted {count} scan job(s)"}
