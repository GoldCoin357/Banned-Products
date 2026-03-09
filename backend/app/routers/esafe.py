"""
Router: CPSC eSAFE Rapid submission management.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.listing import DetectedListing
from ..services.cpsc_service import submit_esafe_report, submit_pending_reports

router = APIRouter(prefix="/api/esafe", tags=["esafe"])


@router.post("/submit/{listing_id}", summary="Submit a single listing to CPSC eSAFE Rapid")
async def submit_listing(
    listing_id: int,
    db: Session = Depends(get_db),
):
    """Manually submit a specific detected listing to CPSC eSAFE Rapid."""
    listing = db.query(DetectedListing).filter(DetectedListing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.is_reported:
        return {
            "message": "Already reported",
            "esafe_report_id": listing.esafe_report_id,
            "esafe_submitted_at": listing.esafe_submitted_at,
        }

    report_id = await submit_esafe_report(listing, db)
    db.commit()

    if report_id:
        return {
            "message": "Successfully submitted to CPSC eSAFE Rapid",
            "esafe_report_id": report_id,
            "listing_id": listing_id,
        }
    else:
        raise HTTPException(
            status_code=503,
            detail="eSAFE submission failed. Check CPSC_RAPID_API_KEY configuration and logs.",
        )


@router.post("/submit-pending", summary="Submit all confirmed pending listings to eSAFE Rapid")
async def submit_all_pending(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Queue bulk submission of all confirmed, not-yet-reported listings."""
    background_tasks.add_task(submit_pending_reports, db)
    return {"message": "Bulk eSAFE submission queued in background"}


@router.get("/status", summary="eSAFE submission statistics")
def esafe_status(db: Session = Depends(get_db)):
    reported = db.query(DetectedListing).filter(DetectedListing.is_reported == True).count()
    pending = db.query(DetectedListing).filter(
        DetectedListing.is_confirmed == True,
        DetectedListing.is_reported == False,
        DetectedListing.is_valid == True,
    ).count()
    failed = db.query(DetectedListing).filter(
        DetectedListing.is_confirmed == True,
        DetectedListing.is_reported == False,
        DetectedListing.is_valid == False,
    ).count()
    return {
        "total_reported": reported,
        "pending_submission": pending,
        "invalidated": failed,
    }
