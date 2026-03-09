"""
CPSC eSAFE Rapid integration service.

Covers two workflows:
  1. Fetching & syncing recalled/banned product data from CPSC public APIs.
  2. Submitting incident reports to the CPSC eSAFE Rapid reporting tool.

CPSC public data endpoints:
  - Recalls JSON feed:  https://www.cpsc.gov/data.json  (RSS / JSON)
  - SaferProducts REST: https://www.saferproducts.gov/RestWebServices/Recall
  - Recall search API:  https://recalls.gov (generic government recalls)

eSAFE Rapid submission:
  - Base URL: https://esafe.cpsc.gov/Ess/Reporting/api
  - Requires API key issued by CPSC (CPSC_RAPID_API_KEY setting).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.recall import RecalledProduct
from ..models.listing import DetectedListing

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# CPSC Recall Data Fetching
# ---------------------------------------------------------------------------

SAFERPRODUCTS_RECALL_URL = (
    "https://www.saferproducts.gov/RestWebServices/Recall"
)


async def fetch_cpsc_recalls(
    db: Session,
    max_pages: int = 20,
    days_back: int = 365 * 5,
) -> dict[str, int]:
    """
    Fetch recalled products from the CPSC SaferProducts REST API and upsert
    them into the local database.

    Returns a dict with counts: {"fetched": N, "created": N, "updated": N}.
    """
    since = datetime.utcnow() - timedelta(days=days_back)
    stats = {"fetched": 0, "created": 0, "updated": 0, "errors": 0}

    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
        page = 0
        while page < max_pages:
            params = {
                "format": "json",
                "RecallDateStart": since.strftime("%Y-%m-%d"),
                "Limit": 100,
                "Offset": page * 100,
            }
            try:
                resp = await client.get(SAFERPRODUCTS_RECALL_URL, params=params)
                resp.raise_for_status()
                recalls = resp.json()
            except Exception as exc:
                logger.error("CPSC recall fetch error (page %d): %s", page, exc)
                stats["errors"] += 1
                break

            if not recalls:
                break

            for raw in recalls:
                stats["fetched"] += 1
                try:
                    created = _upsert_recall(db, raw)
                    if created:
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1
                except Exception as exc:
                    logger.warning("Failed to upsert recall %s: %s", raw.get("RecallID"), exc)
                    stats["errors"] += 1

            page += 1
            # Rate-limit courtesy delay
            await asyncio.sleep(0.5)

    db.commit()
    logger.info("CPSC sync complete: %s", stats)
    return stats


def _upsert_recall(db: Session, raw: dict[str, Any]) -> bool:
    """
    Insert or update a RecalledProduct from raw CPSC API data.
    Returns True if a new record was created.
    """
    recall_id = str(raw.get("RecallID", ""))
    recall_number = str(raw.get("RecallNumber", ""))

    existing = (
        db.query(RecalledProduct)
        .filter(RecalledProduct.cpsc_recall_id == recall_id)
        .first()
    )

    # Parse product list (CPSC returns a list under "Products")
    products = raw.get("Products", [{}])
    primary = products[0] if products else {}

    product_name = (
        primary.get("Name")
        or raw.get("Title")
        or "Unknown Product"
    )
    brand = primary.get("Brand") or raw.get("Manufacturers", [{}])[0].get("Name", "")
    model_numbers = [p.get("Model", "") for p in products if p.get("Model")]
    upcs = [p.get("UPC", "") for p in products if p.get("UPC")]

    image_urls = [
        img.get("URL", "")
        for img in raw.get("Images", [])
        if img.get("URL")
    ]

    recall_date_str = raw.get("RecallDate", "")
    recall_date = None
    if recall_date_str:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                recall_date = datetime.strptime(recall_date_str[:19], fmt)
                break
            except ValueError:
                continue

    # Build search keywords from product name, brand, model numbers
    keywords = list({
        w.lower()
        for token in ([product_name, brand] + model_numbers)
        for w in token.split()
        if len(w) > 2
    })

    data = dict(
        recall_number=recall_number,
        product_name=product_name,
        product_description=raw.get("Description", ""),
        product_type=raw.get("ProductType", ""),
        brand=brand,
        model_numbers=model_numbers,
        upcs=upcs,
        recall_date=recall_date,
        hazard_description=raw.get("Hazards", [{}])[0].get("Name", "") if raw.get("Hazards") else "",
        injury_description=raw.get("Injuries", [{}])[0].get("Name", "") if raw.get("Injuries") else "",
        remedy=", ".join(r.get("Name", "") for r in raw.get("Remedies", [])),
        units_sold=raw.get("NumberOfUnits", ""),
        image_urls=image_urls,
        search_keywords=keywords,
        category=raw.get("ProductType", ""),
        is_active=True,
        source_url=raw.get("URL", ""),
        updated_at=datetime.utcnow(),
    )

    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        return False
    else:
        record = RecalledProduct(cpsc_recall_id=recall_id, **data)
        db.add(record)
        return True


# ---------------------------------------------------------------------------
# eSAFE Rapid Incident Submission
# ---------------------------------------------------------------------------

ESAFE_INCIDENT_ENDPOINT = f"{settings.CPSC_RAPID_SUBMIT_URL}/incident"


async def submit_esafe_report(listing: DetectedListing, db: Session) -> str | None:
    """
    Submit a detected marketplace listing as an incident to CPSC eSAFE Rapid.

    Returns the eSAFE case/report ID on success, or None on failure.
    The listing record is updated in-place (esafe_report_id, esafe_submitted_at,
    is_reported) but NOT committed – caller must commit.
    """
    if not settings.CPSC_RAPID_API_KEY:
        logger.warning("CPSC_RAPID_API_KEY not configured – skipping eSAFE submission.")
        return None

    recall = listing.recall
    payload = _build_esafe_payload(listing, recall)

    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": settings.CPSC_RAPID_API_KEY,
    }

    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
        try:
            resp = await client.post(ESAFE_INCIDENT_ENDPOINT, json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()
            report_id = result.get("reportId") or result.get("caseNumber") or str(result.get("id", ""))
            listing.esafe_report_id = report_id
            listing.esafe_submitted_at = datetime.utcnow()
            listing.is_reported = True
            logger.info("eSAFE report submitted: %s for listing %s", report_id, listing.id)
            return report_id
        except httpx.HTTPStatusError as exc:
            logger.error(
                "eSAFE submission failed (HTTP %d): %s",
                exc.response.status_code,
                exc.response.text,
            )
        except Exception as exc:
            logger.error("eSAFE submission error: %s", exc)

    return None


def _build_esafe_payload(listing: DetectedListing, recall: RecalledProduct | None) -> dict:
    """Build the JSON payload for the CPSC eSAFE Rapid API."""
    product_name = listing.title or (recall.product_name if recall else "Unknown Product")
    brand = recall.brand if recall else ""
    hazard = recall.hazard_description if recall else "Recalled/banned product listed for sale on C2C marketplace."

    return {
        "reporter": {
            "name": settings.ESAFE_REPORTER_NAME,
            "email": settings.ESAFE_REPORTER_EMAIL,
            "phone": settings.ESAFE_REPORTER_PHONE,
            "organization": settings.ESAFE_REPORTER_ORG,
        },
        "product": {
            "name": product_name,
            "brand": brand,
            "modelNumber": recall.model_numbers[0] if (recall and recall.model_numbers) else "",
            "description": listing.description or "",
            "type": listing.product_type or (recall.product_type if recall else ""),
            "recallNumber": recall.recall_number if recall else "",
        },
        "incident": {
            "type": "MARKETPLACE_LISTING",
            "description": (
                f"Recalled/banned product found for sale on {listing.platform}.\n"
                f"Listing URL: {listing.listing_url}\n"
                f"Price: {listing.price} {listing.currency}\n"
                f"Seller: {listing.seller_id or 'Unknown'}\n"
                f"AI Detection Confidence: {listing.ai_confidence:.0%}\n"
                f"AI Reasoning: {listing.ai_reasoning or ''}\n"
                f"Recall Hazard: {hazard}"
            ),
            "listingUrl": listing.listing_url,
            "platform": listing.platform,
            "detectedAt": listing.detected_at.isoformat() if listing.detected_at else "",
            "cpscRecallNumber": recall.recall_number if recall else "",
        },
        "images": listing.image_urls or [],
    }


# ---------------------------------------------------------------------------
# Bulk eSAFE submission helper
# ---------------------------------------------------------------------------

async def submit_pending_reports(db: Session) -> dict[str, int]:
    """
    Find all confirmed, not-yet-reported listings and submit them to eSAFE.
    Returns stats dict.
    """
    pending = (
        db.query(DetectedListing)
        .filter(
            DetectedListing.is_confirmed == True,
            DetectedListing.is_reported == False,
            DetectedListing.is_valid == True,
        )
        .all()
    )
    stats = {"submitted": 0, "failed": 0}
    for listing in pending:
        result = await submit_esafe_report(listing, db)
        if result:
            stats["submitted"] += 1
        else:
            stats["failed"] += 1
    db.commit()
    return stats
