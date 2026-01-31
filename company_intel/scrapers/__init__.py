"""
Scrapery dla różnych źródeł danych.
"""

from .base import BaseScraper, ScraperResult
from .website import WebsiteScraper
from .google_maps import GoogleMapsScraper
from .facebook import FacebookScraper
from .instagram import InstagramScraper
from .tiktok import TikTokScraper

__all__ = [
    "BaseScraper",
    "ScraperResult",
    "WebsiteScraper",
    "GoogleMapsScraper",
    "FacebookScraper",
    "InstagramScraper",
    "TikTokScraper",
]
