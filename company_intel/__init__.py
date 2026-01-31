"""
Company Intelligence Tool - zbieranie danych o placówkach medycznych.

Moduły:
- scrapers: Scrapery dla różnych źródeł (WWW, Google Maps, Facebook, Instagram, TikTok)
- analyzers: Analizatory (AI kategoryzacja, wykrywanie filii, scoring)
- orchestrator: Główny flow łączący wszystko
"""

from .orchestrator import CompanyIntelOrchestrator
from .models import CompanyIntel, Placowka, SocialProfile, ActivityScore, KategoryzacjaAI

__all__ = [
    "CompanyIntelOrchestrator",
    "CompanyIntel",
    "Placowka", 
    "SocialProfile",
    "ActivityScore",
    "KategoryzacjaAI",
]

__version__ = "0.1.0"
