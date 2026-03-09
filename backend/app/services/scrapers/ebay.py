"""
eBay scraper — uses the official eBay Browse API when credentials are available,
falling back to HTML scraping of search results.

eBay Browse API docs:
  https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
"""

import logging
from typing import Any
from urllib.parse import urlencode, quote_plus

import httpx

from .base import BaseScraper
from ...config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

EBAY_BROWSE_API = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_SANDBOX_API = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
EBAY_AUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SANDBOX_AUTH_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"

EBAY_SEARCH_URL = "https://www.ebay.com/sch/i.html"


class EbayScraper(BaseScraper):
    platform = "ebay"

    def __init__(self):
        super().__init__()
        self._access_token: str | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def search_listings(
        self,
        keywords: list[str],
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        query = " ".join(keywords[:5])
        if settings.EBAY_APP_ID:
            token = await self._get_app_token()
            if token:
                return await self._api_search(query, max_results, token)
        return await self._html_search(query, max_results)

    # ------------------------------------------------------------------
    # Browse API path
    # ------------------------------------------------------------------

    async def _get_app_token(self) -> str | None:
        """Obtain an OAuth application token using client_credentials grant."""
        import base64
        if self._access_token:
            return self._access_token

        creds = base64.b64encode(
            f"{settings.EBAY_APP_ID}:{settings.EBAY_CERT_ID}".encode()
        ).decode()

        auth_url = EBAY_SANDBOX_AUTH_URL if settings.EBAY_SANDBOX else EBAY_AUTH_URL
        try:
            resp = await self._client.post(
                auth_url,
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                },
            )
            resp.raise_for_status()
            self._access_token = resp.json().get("access_token")
            return self._access_token
        except Exception as exc:
            logger.warning("eBay OAuth failed: %s", exc)
            return None

    async def _api_search(
        self,
        query: str,
        max_results: int,
        token: str,
    ) -> list[dict[str, Any]]:
        base_url = EBAY_SANDBOX_API if settings.EBAY_SANDBOX else EBAY_BROWSE_API
        listings: list[dict[str, Any]] = []
        offset = 0
        limit = min(max_results, 200)

        while len(listings) < max_results:
            params = {
                "q": query,
                "limit": min(limit, max_results - len(listings)),
                "offset": offset,
                "filter": "buyingOptions:{FIXED_PRICE|AUCTION}",
            }
            try:
                resp = await self._client.get(
                    base_url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.error("eBay API search error: %s", exc)
                break

            items = data.get("itemSummaries", [])
            if not items:
                break

            for item in items:
                listings.append(self._normalise(self._parse_api_item(item)))

            total = data.get("total", 0)
            offset += len(items)
            if offset >= total:
                break

        return listings

    def _parse_api_item(self, item: dict) -> dict[str, Any]:
        price_info = item.get("price", {})
        image_info = item.get("image", {})
        additional_images = [img.get("imageUrl", "") for img in item.get("additionalImages", [])]

        return {
            "platform": "ebay",
            "listing_id": item.get("itemId", ""),
            "listing_url": item.get("itemWebUrl", ""),
            "title": item.get("title", ""),
            "description": item.get("shortDescription", ""),
            "price": float(price_info.get("value", 0)) if price_info.get("value") else None,
            "currency": price_info.get("currency", "USD"),
            "seller_id": item.get("seller", {}).get("username", ""),
            "seller_url": f"https://www.ebay.com/usr/{item.get('seller', {}).get('username', '')}",
            "location": item.get("itemLocation", {}).get("country", ""),
            "image_urls": [image_info.get("imageUrl", "")] + additional_images,
            "listing_date": item.get("itemCreationDate", ""),
        }

    # ------------------------------------------------------------------
    # HTML scraping fallback
    # ------------------------------------------------------------------

    async def _html_search(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        listings: list[dict[str, Any]] = []
        page = 1

        while len(listings) < max_results:
            params = {
                "_nkw": query,
                "_pgn": page,
                "_ipg": 60,
                "LH_ItemCondition": 3,  # Used items
            }
            url = f"{EBAY_SEARCH_URL}?{urlencode(params)}"
            try:
                resp = await self._get(url)
                soup = self._parse_html(resp.text)
            except Exception as exc:
                logger.error("eBay HTML scrape error: %s", exc)
                break

            items = soup.select("li.s-item")
            if not items:
                break

            for item in items:
                parsed = self._parse_html_item(item)
                if parsed and parsed.get("listing_url"):
                    listings.append(self._normalise(parsed))
                if len(listings) >= max_results:
                    break

            # Check for next page
            next_btn = soup.select_one("a.pagination__next")
            if not next_btn:
                break
            page += 1

        return listings

    def _parse_html_item(self, item) -> dict[str, Any] | None:
        try:
            title_el = item.select_one(".s-item__title")
            link_el = item.select_one("a.s-item__link")
            price_el = item.select_one(".s-item__price")
            img_el = item.select_one("img.s-item__image-img")
            location_el = item.select_one(".s-item__location")

            url = link_el["href"] if link_el else ""
            if not url or "ebay.com" not in url:
                return None

            # Extract listing ID from URL
            listing_id = ""
            if "/itm/" in url:
                listing_id = url.split("/itm/")[1].split("?")[0].split("/")[-1]

            price_str = price_el.get_text(strip=True) if price_el else ""
            price = None
            if price_str:
                import re
                m = re.search(r"[\d,]+\.?\d*", price_str.replace(",", ""))
                if m:
                    try:
                        price = float(m.group())
                    except ValueError:
                        pass

            return {
                "platform": "ebay",
                "listing_id": listing_id,
                "listing_url": url.split("?")[0],
                "title": title_el.get_text(strip=True) if title_el else "",
                "description": "",
                "price": price,
                "currency": "USD",
                "seller_id": "",
                "seller_url": "",
                "location": location_el.get_text(strip=True) if location_el else "",
                "image_urls": [img_el["src"]] if img_el and img_el.get("src") else [],
                "listing_date": "",
            }
        except Exception as exc:
            logger.debug("eBay item parse error: %s", exc)
            return None
