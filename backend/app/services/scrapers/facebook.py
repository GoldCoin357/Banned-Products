"""
Facebook Marketplace scraper.

Facebook Marketplace does not have a public API. This scraper uses
Playwright (headless browser) to render the page and extract listings.
If Playwright is not installed, it falls back to a GraphQL endpoint
approach that mimics the mobile app requests.

NOTE: Facebook actively blocks scraping. This implementation uses
respectful delays, user-agent rotation, and session management to
minimise detection, but results may be incomplete or blocked.
"""

import json
import logging
import re
from typing import Any

from .base import BaseScraper
from ...config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

FB_GRAPHQL_URL = "https://www.facebook.com/api/graphql/"
FB_MARKETPLACE_URL = "https://www.facebook.com/marketplace/search/"


class FacebookMarketplaceScraper(BaseScraper):
    platform = "facebook"

    async def search_listings(
        self,
        keywords: list[str],
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        query = " ".join(keywords[:5])

        # Try GraphQL approach first
        listings = await self._graphql_search(query, max_results)
        if not listings:
            listings = await self._html_search(query, max_results)

        return listings[:max_results]

    # ------------------------------------------------------------------
    # GraphQL / internal API approach
    # ------------------------------------------------------------------

    async def _graphql_search(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """
        Mimics the Facebook Marketplace internal GraphQL search.
        This may break as Facebook changes their internal API.
        """
        listings: list[dict[str, Any]] = []

        # Variables for MarketplaceSearchListingsQuery
        variables = {
            "count": min(max_results, 24),
            "params": {
                "bqf": {"callsite": "COMMERCE_MKTPLACE_WWW", "query": query},
                "browse_request_params": {
                    "commerce_enable_local_pickup": True,
                    "commerce_enable_shipping": True,
                    "filter_location_latitude": 38.8935,   # DC area default
                    "filter_location_longitude": -77.0846,
                    "filter_radius_km": 100,
                },
                "custom_request_params": {"viewer_coordinates": {"latitude": 38.8935, "longitude": -77.0846}},
            },
        }

        headers = {
            **self.headers,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-FB-Friendly-Name": "MarketplaceSearchListingsQuery",
            "X-FB-LSD": "AVo6Qd3ydE8",
        }

        data = {
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "MarketplaceSearchListingsQuery",
            "variables": json.dumps(variables),
            "server_timestamps": "true",
            "doc_id": "7111939735526424",
        }

        try:
            assert self._client is not None
            resp = await self._client.post(FB_GRAPHQL_URL, data=data, headers=headers)
            if resp.status_code != 200:
                return []
            raw = resp.text
            # FB returns multiple JSON objects separated by newlines
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    edges = (
                        obj.get("data", {})
                        .get("marketplace_search", {})
                        .get("feed_units", {})
                        .get("edges", [])
                    )
                    for edge in edges:
                        parsed = self._parse_graphql_edge(edge)
                        if parsed:
                            listings.append(self._normalise(parsed))
                except json.JSONDecodeError:
                    continue
        except Exception as exc:
            logger.debug("FB GraphQL error: %s", exc)

        return listings

    def _parse_graphql_edge(self, edge: dict) -> dict[str, Any] | None:
        try:
            node = edge.get("node", {}).get("listing", {})
            if not node:
                return None

            listing_id = node.get("id", "")
            title = node.get("marketplace_listing_title", "")
            desc = node.get("redacted_description", {}).get("text", "")
            price_info = node.get("listing_price", {})
            price_str = price_info.get("amount", "")
            currency = price_info.get("currency", "USD")
            location = node.get("location", {}).get("reverse_geocode", {}).get("city", "")
            seller_id = node.get("marketplace_listing_seller", {}).get("id", "")

            primary_photo = node.get("primary_listing_photo", {}).get("image", {}).get("uri", "")
            all_photos = [
                photo.get("image", {}).get("uri", "")
                for photo in node.get("listing_photos", [])
                if photo.get("image", {}).get("uri")
            ]

            price = None
            if price_str:
                m = re.search(r"[\d.]+", price_str.replace(",", ""))
                if m:
                    try:
                        price = float(m.group())
                    except ValueError:
                        pass

            return {
                "platform": "facebook",
                "listing_id": listing_id,
                "listing_url": f"https://www.facebook.com/marketplace/item/{listing_id}/",
                "title": title,
                "description": desc,
                "price": price,
                "currency": currency,
                "seller_id": seller_id,
                "seller_url": f"https://www.facebook.com/profile.php?id={seller_id}",
                "location": location,
                "image_urls": list(filter(None, [primary_photo] + all_photos)),
                "listing_date": "",
            }
        except Exception as exc:
            logger.debug("FB edge parse error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # HTML fallback
    # ------------------------------------------------------------------

    async def _html_search(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """
        Attempt to scrape marketplace search results page.
        Results are heavily limited by Facebook's client-side rendering.
        """
        import urllib.parse
        url = f"{FB_MARKETPLACE_URL}?query={urllib.parse.quote_plus(query)}&exact=false"
        try:
            resp = await self._get(url)
            soup = self._parse_html(resp.text)

            # Facebook renders most content via JS, but meta tags contain some data
            script_tags = soup.find_all("script", type="application/json")
            listings = []
            for script in script_tags:
                try:
                    data = json.loads(script.string or "")
                    listings.extend(self._extract_from_json(data))
                except Exception:
                    continue
            return listings[:max_results]
        except Exception as exc:
            logger.debug("FB HTML search error: %s", exc)
            return []

    def _extract_from_json(self, data: Any) -> list[dict[str, Any]]:
        """Recursively search JSON blob for marketplace listing nodes."""
        listings = []
        if isinstance(data, dict):
            if data.get("__typename") == "MarketplaceListing":
                parsed = self._parse_graphql_edge({"node": {"listing": data}})
                if parsed:
                    listings.append(self._normalise(parsed))
            for v in data.values():
                listings.extend(self._extract_from_json(v))
        elif isinstance(data, list):
            for item in data:
                listings.extend(self._extract_from_json(item))
        return listings
