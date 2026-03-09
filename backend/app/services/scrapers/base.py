"""
Base scraper class for C2C marketplace scrapers.

All platform-specific scrapers inherit from BaseScraper and implement
`search_listings()`. Results are normalised into a standard dict schema.
"""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import Any

import httpx
from bs4 import BeautifulSoup

from ...config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# Standard listing schema returned by every scraper
LISTING_SCHEMA = {
    "platform": str,        # e.g. "ebay"
    "listing_id": str,      # platform-native ID
    "listing_url": str,     # canonical URL
    "title": str,
    "description": str,
    "price": float | None,
    "currency": str,        # e.g. "USD"
    "seller_id": str,
    "seller_url": str,
    "location": str,
    "image_urls": list,     # list[str]
    "listing_date": str,    # ISO-8601 or empty string
}


class BaseScraper(ABC):
    platform: str = "base"

    def __init__(self):
        self.headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            headers=self.headers,
            timeout=settings.REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    @abstractmethod
    async def search_listings(
        self,
        keywords: list[str],
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Search the platform for listings matching the given keywords.
        Returns a list of dicts conforming to LISTING_SCHEMA.
        """

    async def _get(self, url: str, **kwargs) -> httpx.Response:
        """GET with retry and polite delay."""
        delay = random.uniform(settings.SCRAPE_DELAY_MIN, settings.SCRAPE_DELAY_MAX)
        await asyncio.sleep(delay)
        assert self._client is not None, "Use scraper as async context manager"
        for attempt in range(3):
            try:
                resp = await self._client.get(url, **kwargs)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (429, 503) and attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError(f"Failed to GET {url} after 3 attempts")

    def _parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def _normalise(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ensure all required keys are present with correct types."""
        result = {}
        for key, typ in LISTING_SCHEMA.items():
            val = data.get(key)
            if val is None:
                result[key] = [] if typ is list else ("" if typ is str else None)
            else:
                result[key] = val
        return result
