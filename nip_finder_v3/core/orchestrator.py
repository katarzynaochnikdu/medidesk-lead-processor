"""
NIP Finder V3 Ultimate Orchestrator - główny koordynator strategii wyszukiwania.

ULTIMATE CASCADE (8 poziomów):
0. AI Input Enrichment (predict domain, normalize name)
1. Cache (with fuzzy matching)
2. Privacy policy scraping (90% success, FREE)
3. Google Search (80-85% success, $0.005) [NEW!]
4. Homepage footer scraping (70% success, FREE)
5. AI Domain Discovery + Privacy/Homepage (if no domain) [NEW!]
6. Brave Search + domain (60% success, $0.002)
7. Brave Search by name (30% success, $0.002)
8. Deep AI (optional)
"""

import logging
import time
from typing import Optional

from ..ai.domain_discovery import AIDomainDiscovery
from ..ai.enrichment import AIEnrichment
from ..config import NIPFinderV3Settings, get_settings
from ..models import NIPRequest, NIPResult, SearchStrategy
from ..strategies.brave_search import BraveSearchStrategy
from ..strategies.google_search import GoogleSearchStrategy
from ..strategies.homepage_scraper import HomepageScraperStrategy
from ..strategies.privacy_scraper import PrivacyScraperStrategy
from ..utils import (
    extract_company_base_name,
    format_nip,
    get_company_domain_from_email,
    normalize_company_name,
)
from ..validation.validator import NIPValidator
from .cache import NIPCache

logger = logging.getLogger(__name__)


class NIPFinderV3:
    """
    NIP Finder V3 - główny koordynator.

    Implementuje 7-poziomową kaskadę strategii z short-circuit.
    """

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()

        # AI-powered helpers
        self.ai_enrichment = (
            AIEnrichment(settings) if self.settings.enable_ai_enrichment else None
        )
        self.ai_domain_discovery = (
            AIDomainDiscovery(settings) if self.settings.enable_ai_domain_discovery else None
        )

        # Cache
        self.cache = NIPCache(settings) if self.settings.enable_cache else None

        # Strategies
        self.privacy_scraper = (
            PrivacyScraperStrategy(settings) if self.settings.enable_privacy_scraping else None
        )
        # GUS search strategy not implemented yet
        self.gus_search = None
        self.google_search = (
            GoogleSearchStrategy(settings) if self.settings.enable_google_search else None
        )
        self.homepage_scraper = (
            HomepageScraperStrategy(settings) if self.settings.enable_homepage_scraping else None
        )
        self.brave_search = (
            BraveSearchStrategy(settings) if self.settings.enable_brave_search else None
        )
        # Deep AI strategy not implemented
        self.deep_ai_search = None

        # Validation
        self.validator = NIPValidator(settings)

        # Cost tracking
        self.total_cost = 0.0

    async def close(self):
        """Close all resources."""
        if self.ai_enrichment:
            await self.ai_enrichment.close()
        if self.ai_domain_discovery:
            await self.ai_domain_discovery.close()
        if self.cache:
            await self.cache.close()
        if self.privacy_scraper:
            await self.privacy_scraper.close()
        if self.google_search:
            await self.google_search.close()
        if self.homepage_scraper:
            await self.homepage_scraper.close()
        if self.brave_search:
            await self.brave_search.close()
        await self.validator.close()

        logger.info("NIP Finder V3 Ultimate closed (total cost: $%.4f)", self.total_cost)

    async def find_nip(
        self,
        company_name: str,
        city: Optional[str] = None,
        email: Optional[str] = None,
        skip_cache: bool = False,
    ) -> NIPResult:
        """
        Szuka NIP firmy przez kaskadę strategii.

        Args:
            company_name: Nazwa firmy
            city: Miasto (opcjonalne)
            email: Email (opcjonalny, do ekstrakcji domeny)
            skip_cache: Pomiń cache

        Returns:
            NIPResult
        """
        start_time = time.time()

        logger.info("="*60)
        logger.info("NIP Finder V3: szukam NIP dla '%s' (%s)", company_name, city or "brak miasta")
        logger.info("="*60)

        # ============================================
        # LEVEL 0: AI Input Enrichment (NEW!)
        # ============================================
        domain = get_company_domain_from_email(email) if email else None
        clean_name = normalize_company_name(company_name)

        # AI-powered enrichment
        predicted_domain = None
        if self.ai_enrichment and not domain:
            logger.info("LEVEL 0: AI input enrichment...")
            enriched = await self.ai_enrichment.enrich_input(company_name, city, email)
            if enriched.get("predicted_domain"):
                predicted_domain = enriched["predicted_domain"]
                logger.info("AI Enrichment: predicted domain=%s", predicted_domain)
            # Use AI's base name if available
            if enriched.get("base_name") and enriched.get("confidence", 0) > 0.7:
                logger.info("AI Enrichment: using AI base name='%s'", enriched["base_name"])

        logger.info("Input: company='%s', city='%s', domain='%s', predicted_domain='%s'",
                   clean_name, city, domain or "brak", predicted_domain or "brak")

        # ============================================
        # LEVEL 1: Cache
        # ============================================
        if self.cache and not skip_cache:
            logger.info("LEVEL 1: Cache lookup...")
            cached = await self.cache.get(clean_name, city)

            if cached:
                # Build result from cache
                age_days = cached.age_days()
                warnings = []

                if cached.needs_freshness_warning(self.settings.cache_freshness_warning_days):
                    warnings.append(
                        f"Cache entry is {age_days} days old - consider refresh"
                    )

                # Parse strategy (handle "none" for not found results)
                strategy = None
                if cached.strategy and cached.strategy != "none":
                    try:
                        strategy = SearchStrategy(cached.strategy)
                    except ValueError:
                        logger.warning("Unknown strategy in cache: %s", cached.strategy)

                result = NIPResult(
                    company_name=company_name,
                    city=city,
                    found=cached.nip is not None,
                    nip=cached.nip,
                    nip_formatted=format_nip(cached.nip) if cached.nip else None,
                    confidence=cached.confidence,
                    strategy_used=strategy,
                    warnings=warnings,
                    from_cache=True,
                    cache_age_days=age_days,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

                logger.info("✅ LEVEL 1: Cache HIT (age: %d days)", age_days)
                return result

            logger.info("Cache MISS - continuing cascade")

        # ============================================
        # LEVEL 2: Privacy Policy Scraping
        # ============================================
        if self.privacy_scraper and domain:
            logger.info("LEVEL 2: Privacy policy scraping (domain=%s)...", domain)

            result = await self.privacy_scraper.find_nip(clean_name, city, domain)

            if result.found:
                # Validate with domain
                if self.settings.require_domain_validation:
                    logger.info("Validating NIP %s with domain %s...", result.nip, domain)
                    validation = await self.validator.validate(result.nip, company_name, domain)
                    result.validation = validation

                    if validation.domain_valid:
                        logger.info("✅ Domain validation SUCCESS")
                        result.confidence = 0.95
                    else:
                        logger.warning("⚠️ Domain validation FAILED")
                        result.confidence = 0.60
                        result.warnings.append("NIP nie zwalidowany z domeną - wymaga weryfikacji")

                # Cache and return
                await self._cache_result(result)
                result.processing_time_ms = int((time.time() - start_time) * 1000)
                logger.info("✅ LEVEL 2: Privacy scraper SUCCESS (NIP=%s)", result.nip)
                return result

            logger.info("Level 2: Privacy scraper nie znalazł NIP")

        # ============================================
        # LEVEL 3: Google Search (NEW!)
        # ============================================
        if self.google_search:
            logger.info("LEVEL 3: Google Search...")

            result = await self.google_search.find_nip(clean_name, city, domain or predicted_domain)

            if result.found:
                # Add cost
                self.total_cost += result.cost_usd

                # Check if domain was discovered
                discovered_domain = result.metadata.get("discovered_domain")
                if discovered_domain and not domain:
                    logger.info("Google Search: discovered domain=%s", discovered_domain)
                    domain = discovered_domain  # Use for subsequent strategies

                # Validate
                validation = await self.validator.validate(result.nip, company_name, domain or predicted_domain)
                result.validation = validation

                # STRICT MODE: Reject if domain validation failed
                if self.settings.require_domain_for_acceptance:
                    ai_confidence = result.metadata.get("ai_validation", {}).get("confidence", 0.0) if result.metadata else 0.0
                    
                    # domain_valid: True=OK, False=FAIL, None=skipped (registry domain)
                    # Only reject when domain_valid is explicitly False, not when skipped (None)
                    if validation.domain_valid is False and (domain or predicted_domain):
                        # Gdy mamy domenę jako INPUT - walidacja domenowa jest WYMAGANA
                        # AI confidence nie może nadpisać faktu że NIP nie jest na podanej domenie
                        logger.warning("⚠️ STRICT MODE: NIP %s nie znaleziony na domenie %s - sprawdzam alternatywy...",
                                      result.nip, domain or predicted_domain)
                        
                        # Spróbuj alternatywnych kandydatów
                        if result.alternatives:
                            logger.info("Checking %d alternative candidates...", len(result.alternatives))
                            for alt in result.alternatives:
                                alt_validation = await self.validator.validate(alt.nip, company_name, domain or predicted_domain)
                                # domain_valid: True=OK, False=FAIL, None=skipped -> treat None as OK
                                if alt_validation.domain_valid is not False:
                                    logger.info("✅ Alternative NIP %s passed domain validation!", alt.nip)
                                    # Użyj alternatywnego kandydata
                                    result.nip = alt.nip
                                    result.nip_formatted = alt.nip_formatted
                                    result.confidence = alt.confidence
                                    result.validation = alt_validation
                                    result.warnings = result.warnings or []
                                    result.warnings.append(f"Used alternative candidate (original {result.nip} failed domain validation)")
                                    await self._cache_result(result)
                                    result.processing_time_ms = int((time.time() - start_time) * 1000)
                                    logger.info("✅ LEVEL 3: Google Search SUCCESS (alternative NIP=%s, cost=$%.4f)",
                                              result.nip, result.cost_usd)
                                    return result
                        
                        # Żaden kandydat nie przeszedł walidacji domenowej - odrzuć
                        logger.warning("⚠️ All candidates failed domain validation - rejecting")
                        # Don't return, continue to next strategy
                    else:
                        # Domain validated OR no domain to validate against
                        await self._cache_result(result)
                        result.processing_time_ms = int((time.time() - start_time) * 1000)
                        logger.info("✅ LEVEL 3: Google Search SUCCESS (NIP=%s, cost=$%.4f)",
                                  result.nip, result.cost_usd)
                        return result
                else:
                    # Non-strict mode: accept anyway
                    await self._cache_result(result)
                    result.processing_time_ms = int((time.time() - start_time) * 1000)
                    logger.info("✅ LEVEL 3: Google Search SUCCESS (NIP=%s, cost=$%.4f)",
                              result.nip, result.cost_usd)
                    return result

            logger.info("Level 3: Google Search nie znalazł NIP")

        # ============================================
        # LEVEL 4: Homepage Footer Scraping
        # ============================================
        if self.homepage_scraper and domain:
            logger.info("LEVEL 4: Homepage footer scraping (domain=%s)...", domain)

            result = await self.homepage_scraper.find_nip(clean_name, city, domain)

            if result.found:
                # Validate with domain
                if self.settings.require_domain_validation:
                    logger.info("Validating NIP %s with domain %s...", result.nip, domain)
                    validation = await self.validator.validate(result.nip, company_name, domain)
                    result.validation = validation

                    if not validation.domain_valid:
                        logger.warning("⚠️ Domain validation FAILED")
                        result.confidence = max(result.confidence - 0.20, 0.50)
                        result.warnings.append("NIP nie zwalidowany z domeną")

                # Cache and return
                await self._cache_result(result)
                result.processing_time_ms = int((time.time() - start_time) * 1000)
                logger.info("✅ LEVEL 4: Homepage scraper SUCCESS (NIP=%s)", result.nip)
                return result

            logger.info("Level 4: Homepage scraper nie znalazł NIP")

        # ============================================
        # LEVEL 5: AI Domain Discovery (NEW!)
        # ============================================
        if self.ai_domain_discovery and not domain and not predicted_domain:
            logger.info("LEVEL 5: AI Domain Discovery (no domain available)...")

            # Use Google Search results to discover domain
            if self.google_search:
                # Re-run Google Search just to get search results (without NIP extraction)
                discovery_queries: list[str] = []

                def add_query(query: str) -> None:
                    cleaned = query.strip()
                    if cleaned and cleaned not in discovery_queries:
                        discovery_queries.append(cleaned)

                if city:
                    add_query(f'"{company_name}" "{city}"')
                add_query(f'"{company_name}"')
                if city:
                    add_query(f"{company_name} {city}")
                add_query(f"{company_name}")

                base_name = extract_company_base_name(company_name)
                if base_name and base_name != clean_name:
                    if city:
                        add_query(f"{base_name} {city}")
                    add_query(base_name)

                google_result = []
                for query in discovery_queries:
                    google_result = await self.google_search._google_search_apify(
                        query,
                        max_results=10,
                    )
                    if not google_result:
                        google_result = await self.google_search._google_search_json_api(
                            query,
                            max_results=10,
                        )
                    if google_result:
                        logger.info("AI Domain Discovery: using results from query '%s'", query)
                        break

                if google_result:
                    # Use AI to discover domain
                    discovered_domain = await self.ai_domain_discovery.discover_domain(
                        company_name, city, google_result
                    )

                    if discovered_domain:
                        logger.info("AI Domain Discovery: found domain=%s", discovered_domain)
                        domain = discovered_domain

                        # Retry privacy scraper with discovered domain
                        if self.privacy_scraper:
                            logger.info("LEVEL 5: Retrying privacy scraper with discovered domain...")
                            result = await self.privacy_scraper.find_nip(clean_name, city, domain)
                            if result.found:
                                # Validate
                                validation = await self.validator.validate(result.nip, company_name, domain)
                                result.validation = validation
                                await self._cache_result(result)
                                result.processing_time_ms = int((time.time() - start_time) * 1000)
                                logger.info("✅ LEVEL 5: AI Domain Discovery + Privacy SUCCESS (NIP=%s)", result.nip)
                                return result

                        # Retry homepage scraper with discovered domain
                        if self.homepage_scraper:
                            logger.info("LEVEL 5: Retrying homepage scraper with discovered domain...")
                            result = await self.homepage_scraper.find_nip(clean_name, city, domain)
                            if result.found:
                                # Validate
                                validation = await self.validator.validate(result.nip, company_name, domain)
                                result.validation = validation
                                await self._cache_result(result)
                                result.processing_time_ms = int((time.time() - start_time) * 1000)
                                logger.info("✅ LEVEL 5: AI Domain Discovery + Homepage SUCCESS (NIP=%s)", result.nip)
                                return result

            logger.info("Level 5: AI Domain Discovery didn't find NIP")

        # ============================================
        # LEVEL 6-7: Brave Search
        # ============================================
        if self.brave_search:
            logger.info("LEVEL 6-7: Brave Search...")

            result = await self.brave_search.find_nip(clean_name, city, domain)

            if result.found:
                # Add cost
                self.total_cost += result.cost_usd

                # Validate
                validation = await self.validator.validate(result.nip, company_name, domain)
                result.validation = validation

                # STRICT MODE: Reject if no domain OR domain validation failed
                # domain_valid: True=OK, False=FAIL, None=skipped (registry domain)
                if self.settings.require_domain_for_acceptance:
                    if not domain:
                        logger.warning("⚠️ STRICT MODE: Rejecting Brave NIP - no domain available for validation")
                        # Continue to next strategy (or NOT FOUND)
                    elif validation.domain_valid is False:
                        logger.warning("⚠️ STRICT MODE: Rejecting Brave NIP - domain validation FAILED")
                        # Continue to next strategy
                    else:
                        # Domain validated successfully
                        await self._cache_result(result)
                        result.processing_time_ms = int((time.time() - start_time) * 1000)
                        logger.info("✅ LEVEL 6-7: Brave Search SUCCESS (NIP=%s, cost=$%.4f)",
                                  result.nip, result.cost_usd)
                        return result
                else:
                    # Non-strict: accept anyway
                    await self._cache_result(result)
                    result.processing_time_ms = int((time.time() - start_time) * 1000)
                    logger.info("✅ LEVEL 6-7: Brave Search SUCCESS (NIP=%s, cost=$%.4f)",
                              result.nip, result.cost_usd)
                    return result

            logger.info("Level 5-6: Brave Search nie znalazł NIP")

        # ============================================
        # LEVEL 7: Deep AI Search (OPTIONAL)
        # ============================================
        # TODO: Implement if needed
        logger.info("LEVEL 7: Deep AI search (not implemented - skipping)")

        # ============================================
        # NOT FOUND
        # ============================================
        logger.warning("❌ NIP NOT FOUND for '%s' (%s)", company_name, city)

        result = NIPResult(
            company_name=company_name,
            city=city,
            found=False,
            nip=None,
            confidence=0.0,
            processing_time_ms=int((time.time() - start_time) * 1000),
        )

        # Cache negative result
        await self._cache_result(result)

        return result

    async def find_nip_from_request(self, request: NIPRequest) -> NIPResult:
        """
        Find NIP from NIPRequest.

        Args:
            request: NIPRequest

        Returns:
            NIPResult
        """
        return await self.find_nip(
            company_name=request.company_name,
            city=request.city,
            email=request.email,
        )

    async def _cache_result(self, result: NIPResult):
        """
        Cache result (if cache enabled).

        Args:
            result: NIPResult to cache
        """
        if not self.cache:
            return

        try:
            await self.cache.set(
                company_name=result.company_name,
                city=result.city,
                nip=result.nip,
                confidence=result.confidence,
                strategy=result.strategy_used.value if result.strategy_used else "none",
                validation=result.validation,
            )
        except Exception as e:
            logger.error("Failed to cache result: %s", e)
