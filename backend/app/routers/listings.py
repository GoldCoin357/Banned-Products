"""
Router: Detected marketplace listings.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc

from ..database import get_db
from ..models.listing import DetectedListing

router = APIRouter(prefix="/api/listings", tags=["listings"])


# ---------- Pydantic schemas ----------

class RecallInfo(BaseModel):
    id: int
    product_name: str
    recall_number: str | None
    brand: str | None

    class Config:
        from_attributes = True


class ListingOut(BaseModel):
    id: int
    platform: str
    listing_url: str
    listing_id: str | None
    title: str | None
    description: str | None
    price: float | None
    currency: str | None
    seller_id: str | None
    seller_url: str | None
    location: str | None
    image_urls: list[str] | None
    listing_date: datetime | None
    ai_confidence: float | None
    ai_reasoning: str | None
    text_match_score: float | None
    image_match_score: float | None
    match_method: str | None
    product_type: str | None
    category: str | None
    is_valid: bool
    is_confirmed: bool
    is_reported: bool
    esafe_report_id: str | None
    esafe_submitted_at: datetime | None
    detected_at: datetime | None
    recall: RecallInfo | None

    class Config:
        from_attributes = True


class ListingPage(BaseModel):
    total: int
    page: int
    page_size: int
    results: list[ListingOut]


# ---------- Endpoints ----------

@router.get("/", response_model=ListingPage)
def list_listings(
    platform: str = Query("", description="Filter by platform"),
    product_type: str = Query("", description="Filter by product type"),
    category: str = Query("", description="Filter by category"),
    is_valid: bool | None = Query(True),
    is_confirmed: bool | None = Query(None),
    is_reported: bool | None = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    search: str = Query("", description="Search title, seller, URL"),
    sort_by: str = Query("detected_at", description="Field to sort by"),
    sort_order: str = Query("desc", description="asc or desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(DetectedListing)

    if platform:
        q = q.filter(DetectedListing.platform == platform)
    if product_type:
        q = q.filter(DetectedListing.product_type.ilike(f"%{product_type}%"))
    if category:
        q = q.filter(DetectedListing.category.ilike(f"%{category}%"))
    if is_valid is not None:
        q = q.filter(DetectedListing.is_valid == is_valid)
    if is_confirmed is not None:
        q = q.filter(DetectedListing.is_confirmed == is_confirmed)
    if is_reported is not None:
        q = q.filter(DetectedListing.is_reported == is_reported)
    if min_confidence > 0:
        q = q.filter(DetectedListing.ai_confidence >= min_confidence)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                DetectedListing.title.ilike(like),
                DetectedListing.listing_url.ilike(like),
                DetectedListing.seller_id.ilike(like),
            )
        )

    # Sorting
    sort_col = getattr(DetectedListing, sort_by, DetectedListing.detected_at)
    if sort_order == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(desc(sort_col))

    total = q.count()
    results = q.offset((page - 1) * page_size).limit(page_size).all()

    return ListingPage(total=total, page=page, page_size=page_size, results=results)


@router.get("/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    listing = db.query(DetectedListing).filter(DetectedListing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


@router.patch("/{listing_id}/confirm", summary="Confirm or dismiss a listing")
def confirm_listing(
    listing_id: int,
    confirmed: bool = True,
    db: Session = Depends(get_db),
):
    listing = db.query(DetectedListing).filter(DetectedListing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.is_confirmed = confirmed
    if not confirmed:
        listing.is_valid = False
    db.commit()
    return {"id": listing_id, "is_confirmed": listing.is_confirmed, "is_valid": listing.is_valid}


@router.delete("/{listing_id}", summary="Invalidate / remove a listing from results")
def invalidate_listing(listing_id: int, db: Session = Depends(get_db)):
    listing = db.query(DetectedListing).filter(DetectedListing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.is_valid = False
    db.commit()
    return {"message": "Listing invalidated", "id": listing_id}
