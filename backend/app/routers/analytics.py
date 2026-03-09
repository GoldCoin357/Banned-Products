"""
Router: Analytics / dashboard data endpoints.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import datetime, timedelta

from ..database import get_db
from ..models.listing import DetectedListing
from ..models.recall import RecalledProduct

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary", summary="High-level dashboard summary stats")
def get_summary(db: Session = Depends(get_db)):
    """Returns aggregate counts for the dashboard summary cards."""
    total_listings = db.query(DetectedListing).filter(DetectedListing.is_valid == True).count()
    confirmed = db.query(DetectedListing).filter(
        DetectedListing.is_valid == True,
        DetectedListing.is_confirmed == True,
    ).count()
    reported = db.query(DetectedListing).filter(DetectedListing.is_reported == True).count()
    total_recalls = db.query(RecalledProduct).filter(RecalledProduct.is_active == True).count()

    week_ago = datetime.utcnow() - timedelta(days=7)
    new_this_week = db.query(DetectedListing).filter(
        DetectedListing.detected_at >= week_ago,
        DetectedListing.is_valid == True,
    ).count()

    avg_conf_row = db.query(func.avg(DetectedListing.ai_confidence)).filter(
        DetectedListing.is_valid == True
    ).scalar()
    avg_confidence = round(float(avg_conf_row or 0), 4)

    return {
        "total_detected_listings": total_listings,
        "confirmed_listings": confirmed,
        "reported_to_esafe": reported,
        "active_recalls_in_db": total_recalls,
        "new_detections_last_7_days": new_this_week,
        "average_ai_confidence": avg_confidence,
    }


@router.get("/by-platform", summary="Listing counts grouped by C2C platform")
def by_platform(
    days: int = Query(30, description="Look-back window in days"),
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(DetectedListing.platform, func.count(DetectedListing.id).label("count"))
        .filter(DetectedListing.is_valid == True, DetectedListing.detected_at >= since)
        .group_by(DetectedListing.platform)
        .order_by(func.count(DetectedListing.id).desc())
        .all()
    )
    return [{"platform": r.platform, "count": r.count} for r in rows]


@router.get("/by-product-type", summary="Listing counts grouped by product type")
def by_product_type(
    days: int = Query(30),
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(DetectedListing.product_type, func.count(DetectedListing.id).label("count"))
        .filter(
            DetectedListing.is_valid == True,
            DetectedListing.detected_at >= since,
            DetectedListing.product_type != None,
            DetectedListing.product_type != "",
        )
        .group_by(DetectedListing.product_type)
        .order_by(func.count(DetectedListing.id).desc())
        .limit(20)
        .all()
    )
    return [{"product_type": r.product_type, "count": r.count} for r in rows]


@router.get("/by-category", summary="Listing counts grouped by category")
def by_category(
    days: int = Query(30),
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(DetectedListing.category, func.count(DetectedListing.id).label("count"))
        .filter(
            DetectedListing.is_valid == True,
            DetectedListing.detected_at >= since,
            DetectedListing.category != None,
            DetectedListing.category != "",
        )
        .group_by(DetectedListing.category)
        .order_by(func.count(DetectedListing.id).desc())
        .limit(20)
        .all()
    )
    return [{"category": r.category, "count": r.count} for r in rows]


@router.get("/trend", summary="Daily detection counts over time")
def trend(
    days: int = Query(30, description="Number of days to show"),
    platform: str = Query("", description="Filter by platform (empty = all)"),
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    q = db.query(
        func.date(DetectedListing.detected_at).label("date"),
        func.count(DetectedListing.id).label("count"),
    ).filter(
        DetectedListing.is_valid == True,
        DetectedListing.detected_at >= since,
    )
    if platform:
        q = q.filter(DetectedListing.platform == platform)

    rows = q.group_by(func.date(DetectedListing.detected_at)).order_by("date").all()
    return [{"date": str(r.date), "count": r.count} for r in rows]


@router.get("/top-recalls", summary="Recalled products with most detected listings")
def top_recalls(
    limit: int = Query(10, le=50),
    days: int = Query(30),
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            RecalledProduct.id,
            RecalledProduct.product_name,
            RecalledProduct.brand,
            RecalledProduct.recall_number,
            RecalledProduct.category,
            func.count(DetectedListing.id).label("listing_count"),
        )
        .join(DetectedListing, DetectedListing.recall_id == RecalledProduct.id)
        .filter(
            DetectedListing.is_valid == True,
            DetectedListing.detected_at >= since,
        )
        .group_by(RecalledProduct.id)
        .order_by(func.count(DetectedListing.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "recall_id": r.id,
            "product_name": r.product_name,
            "brand": r.brand,
            "recall_number": r.recall_number,
            "category": r.category,
            "listing_count": r.listing_count,
        }
        for r in rows
    ]


@router.get("/confidence-distribution", summary="AI confidence score histogram")
def confidence_distribution(
    buckets: int = Query(10, ge=2, le=20),
    db: Session = Depends(get_db),
):
    listings = (
        db.query(DetectedListing.ai_confidence)
        .filter(DetectedListing.is_valid == True, DetectedListing.ai_confidence != None)
        .all()
    )
    scores = [r.ai_confidence for r in listings]
    if not scores:
        return []

    bucket_size = 1.0 / buckets
    distribution = []
    for i in range(buckets):
        lo = round(i * bucket_size, 2)
        hi = round((i + 1) * bucket_size, 2)
        count = sum(1 for s in scores if lo <= s < hi)
        distribution.append({"range_low": lo, "range_high": hi, "count": count})

    return distribution


@router.get("/platform-product-matrix", summary="Cross-tab of platforms vs product types")
def platform_product_matrix(
    days: int = Query(30),
    db: Session = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            DetectedListing.platform,
            DetectedListing.product_type,
            func.count(DetectedListing.id).label("count"),
        )
        .filter(
            DetectedListing.is_valid == True,
            DetectedListing.detected_at >= since,
            DetectedListing.product_type != None,
            DetectedListing.product_type != "",
        )
        .group_by(DetectedListing.platform, DetectedListing.product_type)
        .order_by(func.count(DetectedListing.id).desc())
        .all()
    )
    return [{"platform": r.platform, "product_type": r.product_type, "count": r.count} for r in rows]
