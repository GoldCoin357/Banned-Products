"""
Scan orchestration service.

Coordinates the full pipeline:
  1. Pick a recalled product from the DB.
  2. Search C2C platforms using the product's keywords.
  3. Run AI detection on each listing.
  4. Persist DetectedListing records for matches above the confidence threshold.
  5. Optionally submit high-confidence matches to CPSC eSAFE Rapid.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.recall import RecalledProduct
from ..models.listing import DetectedListing, ScanJob
from .ai_detector import detect_listing
from .scrapers import PLATFORM_SCRAPERS
from .cpsc_service import submit_esafe_report

logger = logging.getLogger(__name__)
settings = get_settings()


async def run_scan(
    db: Session,
    platform: str,
    recall: RecalledProduct,
    max_results: int = 50,
    auto_submit_esafe: bool = False,
) -> ScanJob:
    """
    Execute a full scan for one recalled product on one platform.
    Creates and returns a ScanJob record.
    """
    job = ScanJob(
        platform=platform,
        recall_id=recall.id,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        scraper_cls = PLATFORM_SCRAPERS.get(platform)
        if not scraper_cls:
            raise ValueError(f"Unknown platform: {platform}")

        keywords = _build_keywords(recall)

        async with scraper_cls() as scraper:
            raw_listings = await scraper.search_listings(keywords, max_results=max_results)

        job.listings_scanned = len(raw_listings)
        logger.info(
            "Scan job %d: scraped %d listings from %s for recall %s",
            job.id, len(raw_listings), platform, recall.recall_number,
        )

        # Run AI detection concurrently in batches
        detected = await _detect_batch(db, raw_listings, recall, job, auto_submit_esafe)
        job.listings_detected = detected
        job.status = "completed"

    except Exception as exc:
        logger.error("Scan job %d failed: %s", job.id, exc, exc_info=True)
        job.status = "failed"
        job.error_message = str(exc)

    finally:
        job.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(job)

    return job


def _build_keywords(recall: RecalledProduct) -> list[str]:
    """Derive the best search keywords from a recalled product record."""
    parts: list[str] = []
    if recall.brand:
        parts.append(recall.brand)
    if recall.product_name:
        parts.append(recall.product_name)
    if recall.model_numbers:
        parts.extend(recall.model_numbers[:2])
    # Also include any explicit search keywords from the recall record
    if recall.search_keywords:
        parts.extend(recall.search_keywords[:3])
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for p in parts:
        if p.lower() not in seen:
            seen.add(p.lower())
            unique.append(p)
    return unique[:8]  # Keep it manageable


async def _detect_batch(
    db: Session,
    raw_listings: list[dict[str, Any]],
    recall: RecalledProduct,
    job: ScanJob,
    auto_submit_esafe: bool,
) -> int:
    """Run AI detection on a batch of listings, persisting matches."""
    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_SCRAPERS)
    detected_count = 0

    async def process_one(raw: dict[str, Any]) -> None:
        nonlocal detected_count
        async with semaphore:
            url = raw.get("listing_url", "")
            if not url:
                return

            # Skip if already in DB
            existing = db.query(DetectedListing).filter(
                DetectedListing.listing_url == url
            ).first()
            if existing:
                return

            result = await detect_listing(
                listing_title=raw.get("title", ""),
                listing_description=raw.get("description", ""),
                listing_image_urls=raw.get("image_urls", []),
                recalled_product=recall,
            )

            if not result["is_match"]:
                return

            # Persist the match
            listing = DetectedListing(
                platform=raw.get("platform", job.platform),
                listing_url=url,
                listing_id=raw.get("listing_id", ""),
                title=raw.get("title", ""),
                description=raw.get("description", ""),
                price=raw.get("price"),
                currency=raw.get("currency", "USD"),
                seller_id=raw.get("seller_id", ""),
                seller_url=raw.get("seller_url", ""),
                location=raw.get("location", ""),
                image_urls=raw.get("image_urls", []),
                recall_id=recall.id,
                ai_confidence=result["confidence"],
                ai_reasoning=result["reasoning"],
                text_match_score=result["text_match_score"],
                image_match_score=result["image_match_score"],
                match_method=result["match_method"],
                product_type=recall.product_type,
                category=recall.category,
                is_valid=True,
                scan_job_id=job.id,
            )
            db.add(listing)
            db.commit()
            db.refresh(listing)
            detected_count += 1

            logger.info(
                "Detected listing: %s | conf=%.2f | platform=%s",
                url, result["confidence"], job.platform,
            )

            # Auto-submit to eSAFE if confidence is very high
            if auto_submit_esafe and result["confidence"] >= 0.90:
                await submit_esafe_report(listing, db)
                db.commit()

    tasks = [process_one(raw) for raw in raw_listings]
    await asyncio.gather(*tasks)
    return detected_count


async def run_all_platforms_scan(
    db: Session,
    recall: RecalledProduct,
    platforms: list[str] | None = None,
    max_results: int = 50,
    auto_submit_esafe: bool = False,
) -> list[ScanJob]:
    """
    Run a scan across all (or specified) platforms for a single recalled product.
    Returns a list of ScanJob records.
    """
    if platforms is None:
        platforms = list(PLATFORM_SCRAPERS.keys())

    jobs = []
    for platform in platforms:
        job = await run_scan(
            db=db,
            platform=platform,
            recall=recall,
            max_results=max_results,
            auto_submit_esafe=auto_submit_esafe,
        )
        jobs.append(job)

    return jobs
