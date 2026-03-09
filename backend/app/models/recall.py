"""
SQLAlchemy model for CPSC recalled / banned products.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, JSON
from ..database import Base


class RecalledProduct(Base):
    __tablename__ = "recalled_products"

    id = Column(Integer, primary_key=True, index=True)

    # CPSC identifiers
    cpsc_recall_id = Column(String(64), unique=True, index=True, nullable=True)
    recall_number = Column(String(32), index=True, nullable=True)

    # Product details
    product_name = Column(String(512), nullable=False)
    product_description = Column(Text, nullable=True)
    product_type = Column(String(128), index=True, nullable=True)
    brand = Column(String(256), index=True, nullable=True)
    model_numbers = Column(JSON, nullable=True)       # list of model numbers
    upcs = Column(JSON, nullable=True)                # list of UPC codes

    # Recall meta
    recall_date = Column(DateTime, nullable=True)
    hazard_description = Column(Text, nullable=True)
    injury_description = Column(Text, nullable=True)
    remedy = Column(String(512), nullable=True)
    units_sold = Column(String(128), nullable=True)

    # Images / keywords for AI matching
    image_urls = Column(JSON, nullable=True)          # list of image URLs
    search_keywords = Column(JSON, nullable=True)     # list of search terms

    # Classification
    category = Column(String(128), index=True, nullable=True)
    is_banned = Column(Boolean, default=False, index=True)  # True = fully banned (not just recalled)
    is_active = Column(Boolean, default=True, index=True)

    # Embedding for similarity search (stored as JSON array)
    embedding = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    source_url = Column(String(1024), nullable=True)

    def __repr__(self):
        return f"<RecalledProduct id={self.id} recall_number={self.recall_number} name={self.product_name!r}>"
