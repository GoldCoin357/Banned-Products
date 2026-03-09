"""
Configuration management for the Banned Products Detection System.
"""

import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Banned Products Detection System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite:///./banned_products.db"

    # Anthropic / Claude API
    ANTHROPIC_API_KEY: str = ""

    # CPSC eSAFE Rapid API
    CPSC_ESAFE_BASE_URL: str = "https://www.saferproducts.gov/RestWebServices"
    CPSC_ESAFE_API_KEY: str = ""
    CPSC_RECALLS_URL: str = "https://www.cpsc.gov/cgi-bin/rem召recalldb/search.aspx"
    CPSC_API_BASE: str = "https://www.cpsc.gov/cgi-bin/recalldb"
    CPSC_RECALLS_JSON_URL: str = "https://www.cpsc.gov/data.json"
    CPSC_RAPID_SUBMIT_URL: str = "https://esafe.cpsc.gov/Ess/Reporting/api"
    CPSC_RAPID_API_KEY: str = ""

    # eBay API (Finding API / Browse API)
    EBAY_APP_ID: str = ""
    EBAY_CERT_ID: str = ""
    EBAY_DEV_ID: str = ""
    EBAY_USER_TOKEN: str = ""
    EBAY_SANDBOX: bool = False

    # Scraping
    SCRAPE_DELAY_MIN: float = 1.0
    SCRAPE_DELAY_MAX: float = 3.0
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    MAX_CONCURRENT_SCRAPERS: int = 3
    REQUEST_TIMEOUT: int = 30

    # Scheduler
    SCRAPE_INTERVAL_MINUTES: int = 60
    CPSC_REFRESH_INTERVAL_HOURS: int = 6

    # AI Detection
    AI_CONFIDENCE_THRESHOLD: float = 0.75
    IMAGE_ANALYSIS_ENABLED: bool = True

    # eSAFE Rapid report defaults
    ESAFE_REPORTER_NAME: str = "CPSC Banned Products Bot"
    ESAFE_REPORTER_EMAIL: str = "admin@example.com"
    ESAFE_REPORTER_PHONE: str = ""
    ESAFE_REPORTER_ORG: str = "Automated Detection System"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
