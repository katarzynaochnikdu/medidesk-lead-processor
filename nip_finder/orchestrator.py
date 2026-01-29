"""
Orchestrator - główny flow wyszukiwania NIP.
Koordynuje wszystkie komponenty: Apify, AI, walidację, cache.
"""

import asyncio
import logging
import time
from typing import Optional

from .apify_client import ApifyClient
from .ai_extractor import AIExtractor
from .cache import NIPCache
from .config import get_nip_finder_settings
from .models import NIPRequest, NIPResult, SearchSource, ValidationResult
from .validator import NIPValidator

logger = logging.getLogger(__name__)


class NIPFinder:
    """
    Główna klasa do wyszukiwania NIP firm.
    
    Flow wyszukiwania (wielopoziomowy):
    1. Cache lookup (instant)
    2. AI query expansion
    3. Google search (Apify)
    4. Deep scraping (Apify)
    5. AI extraction
    6. Walidacja (checksum + VAT + GUS)
    7. Cache wynik
    """
    
    def __init__(
        self,
        settings: Optional[object] = None,
        use_cache: bool = True,
    ):
        """
        Args:
            settings: NIPFinderSettings (opcjonalne)
            use_cache: Czy używać cache (domyślnie True)
        """
        self.settings = settings or get_nip_finder_settings()
        self.use_cache = use_cache
        
        # Komponenty (lazy initialization)
        self._apify_client: Optional[ApifyClient] = None
        self._ai_extractor: Optional[AIExtractor] = None
        self._validator: Optional[NIPValidator] = None
        self._cache: Optional[NIPCache] = None
    
    @property
    def apify_client(self) -> ApifyClient:
        """Lazy init Apify client."""
        if self._apify_client is None:
            self._apify_client = ApifyClient(self.settings)
        return self._apify_client
    
    @property
    def ai_extractor(self) -> AIExtractor:
        """Lazy init AI extractor."""
        if self._ai_extractor is None:
            self._ai_extractor = AIExtractor(self.settings)
        return self._ai_extractor
    
    @property
    def validator(self) -> NIPValidator:
        """Lazy init validator."""
        if self._validator is None:
            self._validator = NIPValidator(self.settings)
        return self._validator
    
    @property
    def cache(self) -> NIPCache:
        """Lazy init cache."""
        if self._cache is None:
            self._cache = NIPCache(self.settings)
        return self._cache
    
    async def find_nip(
        self,
        company_name: str,
        city: Optional[str] = None,
        email: Optional[str] = None,
        skip_cache: bool = False,
    ) -> NIPResult:
        """
        Główna metoda wyszukiwania NIP.
        
        Args:
            company_name: Nazwa firmy (może być chaotyczna)
            city: Miasto (opcjonalne)
            email: Email (opcjonalne, dla domeny)
            skip_cache: Czy pominąć cache (domyślnie False)
        
        Returns:
            NIPResult z wynikiem wyszukiwania
        """
        start_time = time.time()
        errors = []
        warnings = []
        
        logger.info("[SEARCH] Szukam NIP dla: %s (miasto: %s)", company_name, city or "brak")
        
        try:
            # === POZIOM 1: CACHE LOOKUP ===
            if self.use_cache and not skip_cache:
                logger.info("[CACHE] Sprawdzam cache...")
                cached = await self.cache.get(company_name, city)
                if cached:
                    logger.info("[OK] Cache HIT - zwracam z cache")
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    
                    # Zwróć z cache
                    result = NIPResult(
                        company_name=company_name,
                        city=city,
                        nip=cached.nip,
                        nip_formatted=self._format_nip(cached.nip) if cached.nip else None,
                        found=cached.found,
                        confidence=cached.confidence,
                        strategy_used="cache",
                        validation=cached.validation_result,
                        processing_time_ms=processing_time_ms,
                        warnings=["Wynik z cache - może być nieaktualny"] if cached.nip else [],
                    )
                    return result
            
            # === POZIOM 2: AI QUERY EXPANSION ===
            logger.info("[AI] Generuje queries...")
            queries = await self.ai_extractor.generate_queries(
                company_name=company_name,
                city=city,
                email=email,
            )
            logger.info("[OK] Wygenerowano %d queries: %s", len(queries), queries[:3])
            
            # === POZIOM 3: GOOGLE SEARCH (Apify) ===
            logger.info("[GOOGLE] Google Search przez Apify...")
            google_results = await self.apify_client.google_search(queries)
            
            if not google_results:
                errors.append("Google Search nie zwrocil wynikow")
                logger.warning("[WARN] Brak wynikow Google Search")
            else:
                logger.info("[OK] Google zwrocil %d URL", len(google_results))
            
            # Priorytetyzuj URL z polityka-prywatnosci, kontakt, etc.
            priority_urls = self._prioritize_urls(google_results)
            logger.info("[INFO] Priorytetowe URL: %d", len(priority_urls))
            
            # === POZIOM 4: DEEP SCRAPING (Apify) ===
            scraped_texts = []
            if priority_urls:
                logger.info("[SCRAPE] Scraping top %d URL...", min(len(priority_urls), self.settings.max_urls_to_scrape))
                scraped_texts = await self.apify_client.scrape_urls(
                    priority_urls[:self.settings.max_urls_to_scrape]
                )
                logger.info("[OK] Zescrapowano %d stron", len(scraped_texts))
            
            if not scraped_texts:
                errors.append("Scraping nie zwrocil zadnych tekstow")
                logger.warning("[WARN] Brak tekstow ze scrapingu")
            
            # === POZIOM 5: AI EXTRACTION ===
            nip_result = None
            if scraped_texts:
                logger.info("[AI] Wyciaga NIP z tekstow...")
                nip_result = await self.ai_extractor.extract_nip(
                    company_name=company_name,
                    scraped_texts=scraped_texts,
                )
                
                if nip_result and nip_result.get("nip"):
                    logger.info("[OK] AI znalazl NIP: %s (confidence: %.2f)", 
                               nip_result["nip"], nip_result.get("confidence", 0))
                else:
                    logger.warning("[WARN] AI nie znalazl NIP w tekstach")
            
            # === POZIOM 6: WALIDACJA ===
            validation_result = None
            if nip_result and nip_result.get("nip"):
                logger.info("[VALID] Walidacja NIP...")
                validation_result = await self.validator.validate(
                    nip=nip_result["nip"],
                    company_name=company_name,
                )
                
                if validation_result.validated:
                    logger.info("[OK] NIP zwalidowany pomyslnie")
                else:
                    logger.warning("[WARN] NIP nie przeszedl pelnej walidacji: %s", 
                                 validation_result.validation_errors)
                    warnings.extend(validation_result.validation_errors)
            
            # === Budowanie wyniku ===
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            found = bool(nip_result and nip_result.get("nip"))
            nip = nip_result.get("nip") if nip_result else None
            
            result = NIPResult(
                company_name=company_name,
                city=city,
                nip=nip,
                nip_formatted=self._format_nip(nip) if nip else None,
                found=found,
                confidence=nip_result.get("confidence", 0.0) if nip_result else 0.0,
                source=SearchSource(
                    url=nip_result.get("source_url", ""),
                    strategy="google_search_ai",
                    text_snippet=nip_result.get("text_snippet"),
                ) if nip_result and nip_result.get("source_url") else None,
                strategy_used="google_search_ai" if found else None,
                validation=validation_result,
                ai_reasoning=nip_result.get("reasoning") if nip_result else None,
                search_queries_used=queries,
                urls_searched=google_results,
                processing_time_ms=processing_time_ms,
                errors=errors,
                warnings=warnings,
            )
            
            # === POZIOM 7: CACHE ===
            if self.use_cache and found:
                logger.info("[CACHE] Zapisuje do cache...")
                await self.cache.set(
                    company_name=company_name,
                    city=city,
                    nip=nip,
                    confidence=result.confidence,
                    validation_result=validation_result,
                )
            
            logger.info("[DONE] Wyszukiwanie zakonczone: found=%s, confidence=%.2f, time=%dms",
                       found, result.confidence, processing_time_ms)
            
            return result
            
        except Exception as e:
            logger.error("[ERROR] Blad wyszukiwania NIP: %s", e, exc_info=True)
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            return NIPResult(
                company_name=company_name,
                city=city,
                found=False,
                confidence=0.0,
                processing_time_ms=processing_time_ms,
                errors=[f"Błąd wyszukiwania: {str(e)}"],
            )
    
    async def find_nip_from_request(self, request: NIPRequest) -> NIPResult:
        """Wyszukaj NIP z obiektu NIPRequest."""
        return await self.find_nip(
            company_name=request.company_name,
            city=request.city,
            email=request.email,
        )
    
    async def batch_find_nip(
        self,
        requests: list[NIPRequest],
        max_concurrent: int = 5,
    ) -> list[NIPResult]:
        """
        Batch processing - wyszukuje NIP dla wielu firm równolegle.
        
        Args:
            requests: Lista NIPRequest
            max_concurrent: Maksymalna liczba równoległych zapytań (domyślnie 5)
        
        Returns:
            Lista NIPResult
        """
        logger.info("[BATCH] Batch processing: %d firm (max concurrent: %d)",
                   len(requests), max_concurrent)
        
        # Semafore dla ograniczenia równoległości
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_with_semaphore(req: NIPRequest) -> NIPResult:
            async with semaphore:
                return await self.find_nip_from_request(req)
        
        # Równoległe przetwarzanie
        tasks = [process_with_semaphore(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Obsłuż wyjątki
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Błąd przetwarzania %s: %s", requests[i].company_name, result)
                final_results.append(NIPResult(
                    company_name=requests[i].company_name,
                    city=requests[i].city,
                    found=False,
                    errors=[str(result)],
                ))
            else:
                final_results.append(result)
        
        logger.info("[DONE] Batch zakonczony: %d/%d znalezionych",
                   sum(1 for r in final_results if r.found),
                   len(final_results))
        
        return final_results
    
    def _prioritize_urls(self, urls: list[str]) -> list[str]:
        """
        Priorytetyzuje URL wedlug prawdopodobienstwa znalezienia NIP.
        
        Priority (od najwyzszego):
        1. Zrodla KRS (okredo, krs-online, bizraport) - 95% szans
        2. /polityka-prywatnosci, /rodo - 90% szans
        3. /kontakt, /o-nas - 70% szans
        """
        # Tier 1: KRS and business registries (highest priority)
        krs_domains = [
            "okredo.com",
            "krs-online.com",
            "bizraport.pl",
            "krs-pobierz.pl",
            "rejestr.io",
            "aleo.com",
            "infoveriti.pl",
        ]
        
        # Tier 2: Privacy/RODO pages
        privacy_keywords = [
            "/polityka-prywatnosci",
            "/polityka-prywatności",
            "/privacy-policy",
            "/rodo",
        ]
        
        # Tier 3: Contact/About pages
        contact_keywords = [
            "/kontakt",
            "/contact",
            "/o-nas",
            "/about",
        ]
        
        tier1 = []  # KRS sources
        tier2 = []  # Privacy pages
        tier3 = []  # Contact pages
        remaining = []
        
        for url in urls:
            url_lower = url.lower()
            
            # Check KRS domains first
            if any(domain in url_lower for domain in krs_domains):
                tier1.append(url)
            elif any(kw in url_lower for kw in privacy_keywords):
                tier2.append(url)
            elif any(kw in url_lower for kw in contact_keywords):
                tier3.append(url)
            else:
                remaining.append(url)
        
        return tier1 + tier2 + tier3 + remaining
    
    def _format_nip(self, nip: Optional[str]) -> Optional[str]:
        """Formatuje NIP do XXX-XXX-XX-XX."""
        if not nip or len(nip) != 10:
            return None
        return f"{nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:10]}"
    
    async def close(self):
        """Zamknij wszystkie połączenia."""
        if self._cache:
            await self._cache.close()
        if self._apify_client:
            await self._apify_client.close()
        if self._validator:
            await self._validator.close()
