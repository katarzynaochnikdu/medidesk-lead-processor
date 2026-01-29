"""
NIP Finder v2 Orchestrator.

Koordynuje wyszukiwanie NIP przez rozne strategie:
1. GUS API (oficjalne zrodlo)
2. Google Snippet Mining (NIP z wynikow wyszukiwania)
3. Homepage Scraper (ostatecznosc)
"""

import logging
import time
from typing import Optional

from .config import get_settings, NIPFinderV2Settings
from .models import NIPResultV2, SearchStrategy
from .gus import GUSSearch
from .google import GoogleMining
from .scraper import HomepageScraper
from .utils import format_nip

logger = logging.getLogger(__name__)


class NIPFinderV2:
    """
    Glowna klasa do wyszukiwania NIP dla firm.
    
    Uzycie:
        finder = NIPFinderV2()
        result = await finder.find_nip("PragaMed", city="Warszawa")
        if result.found:
            print(f"NIP: {result.nip}")
    """
    
    def __init__(self, settings: Optional[NIPFinderV2Settings] = None):
        self.settings = settings or get_settings()
        self._gus: Optional[GUSSearch] = None
        self._google: Optional[GoogleMining] = None
        self._scraper: Optional[HomepageScraper] = None
    
    @property
    def gus(self) -> GUSSearch:
        """Lazy init GUS client."""
        if self._gus is None:
            self._gus = GUSSearch(self.settings)
        return self._gus
    
    @property
    def google(self) -> GoogleMining:
        """Lazy init Google client."""
        if self._google is None:
            self._google = GoogleMining(self.settings)
        return self._google
    
    @property
    def scraper(self) -> HomepageScraper:
        """Lazy init Scraper."""
        if self._scraper is None:
            self._scraper = HomepageScraper(self.settings)
        return self._scraper
    
    async def find_nip(
        self,
        company_name: str,
        city: Optional[str] = None,
        skip_gus: bool = False,
        skip_google: bool = False,
        skip_scraper: bool = False,
    ) -> NIPResultV2:
        """
        Szuka NIP dla firmy.
        
        Kolejnosc strategii:
        1. GUS API - najlepsza jakosc, oficjalne dane
        2. Google Snippets - szybkie, bez wchodzenia na strony
        3. Homepage Scraper - ostatecznosc
        
        Args:
            company_name: Nazwa firmy
            city: Miasto (poprawia dokladnosc)
            skip_gus: Pomin GUS (debug)
            skip_google: Pomin Google (debug)
            skip_scraper: Pomin scraper (debug)
        
        Returns:
            NIPResultV2 z wynikami
        """
        start_time = time.time()
        
        result = NIPResultV2(
            company_name=company_name,
            city=city,
        )
        
        logger.info("=" * 60)
        logger.info("[NIPFinder v2] Szukam NIP dla: %s (city=%s)", company_name, city)
        logger.info("=" * 60)
        
        # === 1. GUS API ===
        if not skip_gus:
            logger.info("[STEP 1] Probuję GUS API...")
            try:
                gus_result = await self.gus.search_by_name_async(company_name, city)
                
                if gus_result:
                    result.found = True
                    result.nip = gus_result.nip
                    result.nip_formatted = format_nip(gus_result.nip)
                    result.confidence = 1.0  # GUS = 100% pewnosc
                    result.strategy = SearchStrategy.GUS
                    result.gus_name = gus_result.name
                    result.gus_regon = gus_result.regon
                    result.gus_city = gus_result.city
                    
                    logger.info("[SUCCESS] GUS: NIP=%s", result.nip)
                    result.processing_time_ms = int((time.time() - start_time) * 1000)
                    return result
                else:
                    logger.info("[STEP 1] GUS: brak wynikow")
                    
            except Exception as e:
                logger.error("[STEP 1] GUS error: %s", e)
                result.errors.append(f"GUS: {e}")
        
        # === 2. Google Snippet Mining ===
        if not skip_google:
            logger.info("[STEP 2] Probuję Google Snippets...")
            try:
                google_result = await self.google.search_snippets(company_name, city)
                
                if google_result:
                    result.found = True
                    result.nip = google_result.nip
                    result.nip_formatted = format_nip(google_result.nip)
                    result.confidence = google_result.confidence
                    result.strategy = SearchStrategy.GOOGLE_SNIPPET
                    result.source_url = google_result.source_url
                    result.source_snippet = google_result.snippet
                    
                    logger.info("[SUCCESS] Google: NIP=%s", result.nip)
                    result.processing_time_ms = int((time.time() - start_time) * 1000)
                    return result
                else:
                    logger.info("[STEP 2] Google: brak NIP w snippetach")
                    
            except Exception as e:
                logger.error("[STEP 2] Google error: %s", e)
                result.errors.append(f"Google: {e}")
        
        # === 3. Homepage Scraper ===
        if not skip_scraper:
            logger.info("[STEP 3] Probuję Homepage Scraper...")
            try:
                scraper_result = await self.scraper.scrape_homepage(company_name, city)
                
                if scraper_result:
                    result.found = True
                    result.nip = scraper_result.nip
                    result.nip_formatted = format_nip(scraper_result.nip)
                    result.confidence = scraper_result.confidence
                    result.strategy = SearchStrategy.HOMEPAGE
                    result.source_url = scraper_result.source_url
                    
                    logger.info("[SUCCESS] Scraper: NIP=%s", result.nip)
                    result.processing_time_ms = int((time.time() - start_time) * 1000)
                    return result
                else:
                    logger.info("[STEP 3] Scraper: nie znaleziono NIP")
                    
            except Exception as e:
                logger.error("[STEP 3] Scraper error: %s", e)
                result.errors.append(f"Scraper: {e}")
        
        # === 4. Brak wynikow ===
        logger.warning("[FAILED] Nie znaleziono NIP dla: %s", company_name)
        result.processing_time_ms = int((time.time() - start_time) * 1000)
        return result
    
    async def close(self):
        """Zamyka wszystkie klienty."""
        if self._google:
            await self._google.close()
        if self._scraper:
            await self._scraper.close()
