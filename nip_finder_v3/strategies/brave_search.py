"""
Brave Search - wyszukuje NIP przez Brave Search API.

Brave Search API pozwala na wyszukiwanie w internecie.
Success rate: 60% (with domain), 30% (by name)
Cost: $0.002/query
Time: 1-2s
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

from ..config import NIPFinderV3Settings, get_settings
from ..models import NIPResult, SearchStrategy
from ..utils import RateLimiter, extract_nip_from_text, format_nip
from .base import BaseStrategy

logger = logging.getLogger(__name__)


class BraveSearchStrategy(BaseStrategy):
    """
    Strategia: Wyszukiwanie przez Brave Search API.

    Dwie metody:
    1. find_nip_with_domain(): "NIP site:domain.pl" (60% success, high confidence)
    2. find_nip_by_name(): "Company Name NIP" (30% success, low confidence)
    """

    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None
        self.rate_limiter = RateLimiter(rate=self.settings.brave_rate_limit_per_sec)
        self._last_request_time: Optional[float] = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self):
        """Close HTTP client."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _get_headers(self) -> dict:
        """Nagłówki dla Brave API."""
        return {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.settings.brave_search_api_key,
        }

    async def search(self, query: str, count: int = 5) -> list[dict]:
        """
        Wykonuje wyszukiwanie w Brave.

        Args:
            query: Zapytanie
            count: Liczba wyników

        Returns:
            Lista wyników
        """
        if not self.settings.brave_search_api_key:
            logger.warning("Brave: brak API key")
            return []

        # Small delay between requests to avoid 429 (burst protection)
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < 1.0:  # Wait at least 1 second between requests
                wait_time = 1.0 - elapsed
                logger.debug("Brave: waiting %.2fs to avoid rate limit", wait_time)
                await asyncio.sleep(wait_time)

        try:
            params = {
                "q": query,
                "count": min(count, 20),
                "country": "pl",
                "search_lang": "pl",
                "safesearch": "off",
            }

            self._last_request_time = time.time()

            response = await self.http_client.get(
                self.BASE_URL,
                params=params,
                headers=self._get_headers(),
            )

            if response.status_code == 429:
                logger.warning("Brave: limit zapytań przekroczony")
                return []

            response.raise_for_status()
            data = response.json()

            # Wyciągnij wyniki
            web_results = data.get("web", {}).get("results", [])
            return web_results

        except httpx.HTTPStatusError as e:
            logger.error("Brave HTTP error: %s", e)
            return []
        except Exception as e:
            logger.error("Brave error: %s", e)
            return []

    async def find_nip(
        self,
        company_name: str,
        city: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> NIPResult:
        """
        Główna metoda - próbuje oba warianty.

        Args:
            company_name: Nazwa firmy
            city: Miasto
            domain: Domena (opcjonalna)

        Returns:
            NIPResult
        """
        # Najpierw próbuj z domeną (jeśli dostępna)
        if domain:
            result = await self.find_nip_with_domain(company_name, city, domain)
            if result.found:
                return result

        # Fallback: szukaj po nazwie
        return await self.find_nip_by_name(company_name, city)

    async def find_nip_with_domain(
        self,
        company_name: str,
        city: Optional[str],
        domain: str,
    ) -> NIPResult:
        """
        Wyszukuje NIP przez Brave Search z domeną.

        Query: "NIP site:domain.pl"

        Args:
            company_name: Nazwa firmy
            city: Miasto
            domain: Domena firmowa

        Returns:
            NIPResult
        """
        logger.info("Brave search (domain): szukam NIP dla %s na domenie %s", company_name, domain)

        # Queries z domeną
        queries = [
            f"NIP site:{domain}",
            f'"{company_name}" NIP site:{domain}',
        ]

        for query in queries:
            results = await self.search(query, count=5)

            for result in results:
                url = result.get("url", "")

                # Priorytet dla wyników z właściwej domeny
                if domain in url:
                    text = f"{result.get('title', '')} {result.get('description', '')}"
                    nip = extract_nip_from_text(text)

                    if nip:
                        logger.info("✅ Brave search (domain): NIP znaleziony")

                        return NIPResult(
                            company_name=company_name,
                            city=city,
                            found=True,
                            nip=nip,
                            nip_formatted=format_nip(nip),
                            confidence=0.75,
                            strategy_used=SearchStrategy.BRAVE_SEARCH_DOMAIN,
                            warnings=[],
                            cost_usd=0.002,  # $0.002 per query
                        )

        # Nie znaleziono
        logger.info("❌ Brave search (domain): NIP nie znaleziony")
        return self._create_not_found_result(company_name, city)

    async def find_nip_by_name(
        self,
        company_name: str,
        city: Optional[str],
    ) -> NIPResult:
        """
        Wyszukuje NIP przez Brave Search po nazwie (bez domeny).

        Query: "Company Name" NIP

        UWAGA: Ryzykowna strategia - może znaleźć NIP innej firmy!

        Args:
            company_name: Nazwa firmy
            city: Miasto

        Returns:
            NIPResult
        """
        logger.info("Brave search (name): szukam NIP dla %s", company_name)

        # Import ekstraktora bazowej nazwy
        from ..utils import extract_company_base_name

        # Przygotuj warianty nazwy
        base_name = extract_company_base_name(company_name)

        # Multiple query variants (try most specific first)
        queries = []

        # Variant 1: Full name + city (most specific)
        if city:
            queries.append(f'"{company_name}" "{city}" NIP')

        # Variant 2: Full name alone
        queries.append(f'"{company_name}" NIP')

        # Variant 3: Base name + city (remove generic prefixes)
        if base_name and base_name != company_name.lower():
            if city:
                queries.append(f'"{base_name}" "{city}" NIP')
            # Variant 4: Base name alone
            queries.append(f'"{base_name}" NIP')

        logger.info("Brave search: próbuję %d wariantów query", len(queries))

        # Try each query variant
        for i, query in enumerate(queries, 1):
            logger.info("Brave search: wariant %d/%d: %s", i, len(queries), query)

            results = await self.search(query, count=10)

            # Search in results
            for result in results:
                text = f"{result.get('title', '')} {result.get('description', '')}"
                nip = extract_nip_from_text(text)

                if nip:
                    logger.info("Brave search (name): NIP znaleziony wariantem %d: %s (wymaga weryfikacji)", i, query)

                    return NIPResult(
                        company_name=company_name,
                        city=city,
                        found=True,
                        nip=nip,
                        nip_formatted=format_nip(nip),
                        confidence=0.50,  # LOW confidence - no domain validation
                        strategy_used=SearchStrategy.BRAVE_SEARCH_NAME,
                        warnings=[
                            "NIP znaleziony bez weryfikacji domeny - może należeć do innej firmy",
                            "Wymagana ręczna weryfikacja",
                        ],
                        cost_usd=0.002 * len(queries),  # Cost for all query attempts
                    )

            logger.info("Brave search: wariant %d nie znalazł NIP", i)

        # Nie znaleziono żadnym wariantem
        logger.info("Brave search (name): NIP nie znaleziony żadnym z %d wariantów", len(queries))
        return self._create_not_found_result(company_name, city)
