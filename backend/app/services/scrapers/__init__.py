from .ebay import EbayScraper
from .craigslist import CraigslistScraper
from .facebook import FacebookMarketplaceScraper
from .offerup import OfferUpScraper

PLATFORM_SCRAPERS = {
    "ebay": EbayScraper,
    "craigslist": CraigslistScraper,
    "facebook": FacebookMarketplaceScraper,
    "offerup": OfferUpScraper,
}

__all__ = [
    "EbayScraper",
    "CraigslistScraper",
    "FacebookMarketplaceScraper",
    "OfferUpScraper",
    "PLATFORM_SCRAPERS",
]
