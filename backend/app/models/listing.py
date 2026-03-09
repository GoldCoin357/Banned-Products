"""
SQLAlchemy models for C2C marketplace detected listings and scan jobs.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base


class DetectedListing(Base):
    __tablename__ = "detected_listings"

    id = Column(Integer, primary_key=True, index=True)

    # Source platform
    platform = Column(String(64), index=True, nullable=False)   # ebay, craigslist, facebook, etc.
    listing_url = Column(String(2048), unique=True, nullable=False)
    listing_id = Column(String(256), index=True, nullable=True) # platform-native ID

    # Listing details
    title = Column(String(1024), nullable=True)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=True)
    currency = Column(String(8), default="USD")
    seller_id = Column(String(256), nullable=True, index=True)
    seller_url = Column(String(1024), nullable=True)
    location = Column(String(256), nullable=True)
    image_urls = Column(JSON, nullable=True)        # list of image URLs captured
    listing_date = Column(DateTime, nullable=True)

    # Detection results
    recall_id = Column(Integer, ForeignKey("recalled_products.id"), nullable=True, index=True)
    recall = relationship("RecalledProduct", lazy="joined")

    ai_confidence = Column(Float, nullable=True)          # 0.0 – 1.0
    ai_reasoning = Column(Text, nullable=True)            # Claude's explanation
    text_match_score = Column(Float, nullable=True)       # keyword / fuzzy match score
    image_match_score = Column(Float, nullable=True)      # vision similarity score
    match_method = Column(String(64), nullable=True)      # "text", "image", "combined"

    # Status
    is_valid = Column(Boolean, default=True, index=True)          # passed validation checks
    is_confirmed = Column(Boolean, default=False, index=True)     # human confirmed
    is_reported = Column(Boolean, default=False, index=True)      # reported to CPSC eSAFE
    esafe_report_id = Column(String(128), nullable=True)          # eSAFE case number
    esafe_submitted_at = Column(DateTime, nullable=True)

    # Product category
    product_type = Column(String(128), index=True, nullable=True)
    category = Column(String(128), index=True, nullable=True)

    # Timestamps
    detected_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    scan_job_id = Column(Integer, ForeignKey("scan_jobs.id"), nullable=True, index=True)

    def __repr__(self):
        return f"<DetectedListing id={self.id} platform={self.platform} url={self.listing_url[:60]!r}>"


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(64), index=True, nullable=False)
    status = Column(String(32), default="pending", index=True)   # pending, running, completed, failed
    recall_id = Column(Integer, ForeignKey("recalled_products.id"), nullable=True)

    # Runtime stats
    listings_scanned = Column(Integer, default=0)
    listings_detected = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    listings = relationship("DetectedListing", backref="scan_job", lazy="dynamic",
                            foreign_keys=[DetectedListing.scan_job_id])

    def __repr__(self):
        return f"<ScanJob id={self.id} platform={self.platform} status={self.status}>"
