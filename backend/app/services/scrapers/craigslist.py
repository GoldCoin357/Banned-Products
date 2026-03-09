"""
Craigslist scraper.

Craigslist does not have a public API, so this scraper uses HTML parsing.
Searches across major US regional sites for-sale listings.
"""

import logging
import re
from typing import Any
from urllib.parse import urlencode

from .base import BaseScraper
from ...config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Major US Craigslist regional subdomains to scan
CRAIGSLIST_REGIONS = [
    "newyork", "losangeles", "chicago", "houston", "sfbay",
    "seattle", "boston", "miami", "dallas", "atlanta",
    "denver", "minneapolis", "portland", "phoenix", "sandiego",
]

CRAIGSLIST_SEARCH_URL = "https://{region}.craigslist.org/search/sss"


class CraigslistScraper(BaseScraper):
    platform = "craigslist"

    async def search_listings(
        self,
        keywords: list[str],
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        query = " ".join(keywords[:5])
        listings: list[dict[str, Any]] = []

        per_region = max(5, max_results // len(CRAIGSLIST_REGIONS))

        for region in CRAIGSLIST_REGIONS:
            if len(listings) >= max_results:
                break
            region_listings = await self._search_region(region, query, per_region)
            listings.extend(region_listings)

        return listings[:max_results]

    async def _search_region(
        self,
        region: str,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        listings = []
        offset = 0

        while len(listings) < max_results:
            url = CRAIGSLIST_SEARCH_URL.format(region=region)
            params = {
                "query": query,
                "sort": "date",
                "s": offset,
            }
            try:
                resp = await self._get(url, params=params)
                soup = self._parse_html(resp.text)
            except Exception as exc:
                logger.debug("Craigslist %s error: %s", region, exc)
                break

            items = soup.select("li.cl-search-result")
            # Fallback for older CL layout
            if not items:
                items = soup.select(".result-info")

            if not items:
                break

            for item in items:
                parsed = self._parse_item(item, region)
                if parsed:
                    listings.append(self._normalise(parsed))
                if len(listings) >= max_results:
                    break

            if len(items) < 25:
                break
            offset += len(items)

        return listings

    def _parse_item(self, item, region: str) -> dict[str, Any] | None:
        try:
            # New CL layout
            title_el = item.select_one("a.cl-app-anchor .label") or item.select_one(".result-title")
            link_el = item.select_one("a.cl-app-anchor") or item.select_one("a.result-title")
            price_el = item.select_one(".priceinfo") or item.select_one(".result-price")
            img_el = item.select_one("img")
            date_el = item.select_one("time")

            if not link_el:
                return None

            url = link_el.get("href", "")
            if not url:
                return None
            if url.startswith("/"):
                url = f"https://{region}.craigslist.org{url}"

            # Extract listing ID from URL pattern /xxx/yyy/d/title/1234567890.html
            listing_id = ""
            m = re.search(r"/(\d+)\.html", url)
            if m:
                listing_id = m.group(1)

            price_str = price_el.get_text(strip=True) if price_el else ""
            price = None
            if price_str:
                m2 = re.search(r"[\d,]+\.?\d*", price_str.replace(",", ""))
                if m2:
                    try:
                        price = float(m2.group())
                    except ValueError:
                        pass

            return {
                "platform": "craigslist",
                "listing_id": listing_id,
                "listing_url": url,
                "title": title_el.get_text(strip=True) if title_el else "",
                "description": "",
                "price": price,
                "currency": "USD",
                "seller_id": "",
                "seller_url": "",
                "location": region,
                "image_urls": [img_el["src"]] if img_el and img_el.get("src") else [],
                "listing_date": date_el.get("datetime", "") if date_el else "",
            }
        except Exception as exc:
            logger.debug("CL item parse error: %s", exc)
            return None

    async def fetch_listing_detail(self, url: str) -> dict[str, str]:
        """Fetch the full description and additional images from a listing page."""
        try:
            resp = await self._get(url)
            soup = self._parse_html(resp.text)

            body_el = soup.select_one("#postingbody")
            description = body_el.get_text(separator=" ", strip=True) if body_el else ""

            images = [
                img["src"]
                for img in soup.select(".swipe-wrap img")
                if img.get("src")
            ]
            return {"description": description, "image_urls": images}
        except Exception:
            return {"description": "", "image_urls": []}
