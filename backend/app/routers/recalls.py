"""
Router: CPSC Recalled Products CRUD + sync trigger.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from datetime import datetime
from typing import Any

from ..database import get_db, SessionLocal
from ..models.recall import RecalledProduct
from ..services.cpsc_service import fetch_cpsc_recalls

router = APIRouter(prefix="/api/recalls", tags=["recalls"])


# ---------- Pydantic schemas ----------

class RecallOut(BaseModel):
    id: int
    cpsc_recall_id: str | None
    recall_number: str | None
    product_name: str
    brand: str | None
    product_type: str | None
    category: str | None
    recall_date: datetime | None
    hazard_description: str | None
    is_banned: bool
    is_active: bool
    source_url: str | None
    image_urls: list[str] | None
    search_keywords: list[str] | None
    model_numbers: list[str] | None
    units_sold: str | None
    remedy: str | None
    updated_at: datetime | None

    class Config:
        from_attributes = True


class RecallPage(BaseModel):
    total: int
    page: int
    page_size: int
    results: list[RecallOut]


# ---------- Endpoints ----------

@router.get("/", response_model=RecallPage)
def list_recalls(
    search: str = Query("", description="Full-text search across name, brand, description"),
    category: str = Query("", description="Filter by category"),
    product_type: str = Query("", description="Filter by product type"),
    is_banned: bool | None = Query(None, description="Filter banned-only vs recalled"),
    is_active: bool | None = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(RecalledProduct)

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                RecalledProduct.product_name.ilike(like),
                RecalledProduct.brand.ilike(like),
                RecalledProduct.product_description.ilike(like),
                RecalledProduct.recall_number.ilike(like),
            )
        )
    if category:
        q = q.filter(RecalledProduct.category.ilike(f"%{category}%"))
    if product_type:
        q = q.filter(RecalledProduct.product_type.ilike(f"%{product_type}%"))
    if is_banned is not None:
        q = q.filter(RecalledProduct.is_banned == is_banned)
    if is_active is not None:
        q = q.filter(RecalledProduct.is_active == is_active)

    total = q.count()
    results = q.order_by(RecalledProduct.recall_date.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return RecallPage(total=total, page=page, page_size=page_size, results=results)


@router.get("/{recall_id}", response_model=RecallOut)
def get_recall(recall_id: int, db: Session = Depends(get_db)):
    recall = db.query(RecalledProduct).filter(RecalledProduct.id == recall_id).first()
    if not recall:
        raise HTTPException(status_code=404, detail="Recall not found")
    return recall


@router.post("/sync", summary="Trigger CPSC data sync")
async def sync_cpsc(
    background_tasks: BackgroundTasks,
    days_back: int = Query(1825, description="Days of history to sync"),
    db: Session = Depends(get_db),
):
    """Trigger a background sync of CPSC recall data."""
    async def _sync_task():
        task_db = SessionLocal()
        try:
            await fetch_cpsc_recalls(task_db, days_back=days_back)
        finally:
            task_db.close()

    background_tasks.add_task(_sync_task)
    return {"message": "CPSC sync started in the background"}


@router.delete("/{recall_id}", summary="Deactivate a recall record")
def deactivate_recall(recall_id: int, db: Session = Depends(get_db)):
    recall = db.query(RecalledProduct).filter(RecalledProduct.id == recall_id).first()
    if not recall:
        raise HTTPException(status_code=404, detail="Recall not found")
    recall.is_active = False
    db.commit()
    return {"message": "Recall deactivated", "id": recall_id}


@router.post("/seed", summary="Seed sample recalled products for demo/testing")
def seed_recalls(db: Session = Depends(get_db)):
    """Insert a set of real CPSC recalled products for offline demo use."""
    from datetime import datetime as dt
    samples = [
        dict(cpsc_recall_id="seed-001", recall_number="24-001", product_name="Infant Inclined Sleeper",
             brand="Fisher-Price", product_type="Infant Product", category="Children's Products",
             product_description="Rock 'n Play infant sleeper recalled due to infant deaths.",
             hazard_description="Infants can roll over and suffocate", recall_date=dt(2019, 4, 12),
             search_keywords=["fisher-price","rock n play","sleeper","infant","baby sleeper"],
             model_numbers=["CMR37","CMR39"], is_active=True, is_banned=True),
        dict(cpsc_recall_id="seed-002", recall_number="24-002", product_name="Hoverboard Self-Balancing Scooter",
             brand="Swagway", product_type="Recreational Equipment", category="Sports & Recreation",
             product_description="Hoverboards recalled due to fire and explosion hazard from lithium batteries.",
             hazard_description="Battery can overheat, catch fire, or explode", recall_date=dt(2016, 7, 6),
             search_keywords=["hoverboard","swagway","self-balancing","scooter","swagtron"],
             model_numbers=["X1"], is_active=True, is_banned=False),
        dict(cpsc_recall_id="seed-003", recall_number="24-003", product_name="Portable Charger / Power Bank",
             brand="Anker", product_type="Electronics", category="Electronics",
             product_description="Power banks recalled due to fire hazard from overheating battery.",
             hazard_description="Battery can overheat and catch fire", recall_date=dt(2023, 3, 15),
             search_keywords=["anker","power bank","portable charger","battery pack"],
             model_numbers=["A1263"], is_active=True, is_banned=False),
        dict(cpsc_recall_id="seed-004", recall_number="24-004", product_name="Children's Magnetic Toy Set",
             brand="Buckyballs", product_type="Toy", category="Toys",
             product_description="High-powered magnetic balls recalled due to ingestion hazard for children.",
             hazard_description="Small magnets can be swallowed and attract internally causing injury",
             recall_date=dt(2012, 7, 10),
             search_keywords=["buckyballs","magnetic","magnets","bucky","neodymium","magnet balls"],
             model_numbers=[], is_active=True, is_banned=True),
        dict(cpsc_recall_id="seed-005", recall_number="24-005", product_name="Infant Bath Seat",
             brand="Summer Infant", product_type="Infant Product", category="Children's Products",
             product_description="Bath seats recalled due to drowning risk.",
             hazard_description="Child can tip over and drown", recall_date=dt(2020, 9, 1),
             search_keywords=["summer infant","bath seat","baby bath","infant bath"],
             model_numbers=["91749"], is_active=True, is_banned=False),
    ]
    created = 0
    for s in samples:
        if not db.query(RecalledProduct).filter(RecalledProduct.cpsc_recall_id == s["cpsc_recall_id"]).first():
            db.add(RecalledProduct(**s))
            created += 1
    db.commit()
    return {"message": f"Seeded {created} sample recalls ({len(samples) - created} already existed)"}


@router.post("/import", summary="Manually import a recall record")
def import_recall(payload: dict[str, Any], db: Session = Depends(get_db)):
    """Manually import a recalled product record (e.g. from CSV upload)."""
    required = ("product_name",)
    for field in required:
        if field not in payload:
            raise HTTPException(status_code=422, detail=f"Missing required field: {field}")

    record = RecalledProduct(**{k: v for k, v in payload.items() if hasattr(RecalledProduct, k)})
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "message": "Recall imported successfully"}
