"""
OfferUp scraper — uses the OfferUp public search endpoint.

OfferUp has an internal REST API used by their mobile apps. This scraper
mimics those requests. API paths are subject to change.
"""

import logging
import re
from typing import Any
from urllib.parse import urlencode

from .base import BaseScraper
from ...config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

OFFERUP_SEARCH_API = "https://offerup.com/api/items/search/"
OFFERUP_ITEM_URL = "https://offerup.com/item/detail/{item_id}/"


class OfferUpScraper(BaseScraper):
    platform = "offerup"

    async def search_listings(
        self,
        keywords: list[str],
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        query = " ".join(keywords[:5])
        listings: list[dict[str, Any]] = []
        start = 0

        while len(listings) < max_results:
            params = {
                "q": query,
                "start": start,
                "limit": min(20, max_results - len(listings)),
                "radius": 500,
                "platform": "web",
            }
            try:
                resp = await self._get(OFFERUP_SEARCH_API, params=params)
                data = resp.json()
            except Exception as exc:
                logger.debug("OfferUp search error: %s", exc)
                break

            items = data.get("data", {}).get("items", [])
            if not items:
                # Try alternate response format
                items = data.get("items", [])
            if not items:
                break

            for item in items:
                parsed = self._parse_item(item)
                if parsed:
                    listings.append(self._normalise(parsed))
                if len(listings) >= max_results:
                    break

            if len(items) < 20:
                break
            start += len(items)

        return listings

    def _parse_item(self, item: dict) -> dict[str, Any] | None:
        try:
            item_id = str(item.get("id", ""))
            title = item.get("title", "")
            price_str = str(item.get("price", ""))
            price = None
            if price_str:
                m = re.search(r"[\d.]+", price_str.replace(",", ""))
                if m:
                    try:
                        price = float(m.group())
                    except ValueError:
                        pass

            # Image: OfferUp returns a photo dict with url key
            photos = item.get("photos", []) or []
            image_urls = [p.get("detail", {}).get("url", "") or p.get("url", "") for p in photos]
            image_urls = [u for u in image_urls if u]

            location = item.get("location", {})
            city = location.get("city", "") if isinstance(location, dict) else ""

            seller = item.get("seller", {}) or {}
            seller_id = str(seller.get("id", ""))

            return {
                "platform": "offerup",
                "listing_id": item_id,
                "listing_url": OFFERUP_ITEM_URL.format(item_id=item_id),
                "title": title,
                "description": item.get("description", ""),
                "price": price,
                "currency": "USD",
                "seller_id": seller_id,
                "seller_url": f"https://offerup.com/profile/{seller_id}/",
                "location": city,
                "image_urls": image_urls,
                "listing_date": item.get("post_date", ""),
            }
        except Exception as exc:
            logger.debug("OfferUp item parse error: %s", exc)
            return None
