"""
Homepage Scraper - wyciąga NIP ze stopki strony głównej.

Firmy często publikują NIP w stopce (<footer>).
Success rate: 70%
Cost: FREE
Time: 1-3s
"""

import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from ..config import NIPFinderV3Settings, get_settings
from ..models import NIPResult, SearchStrategy
from ..utils import extract_nip_from_text, format_nip
from .base import BaseStrategy

logger = logging.getLogger(__name__)


class HomepageScraperStrategy(BaseStrategy):
    """
    Strategia: Scraping stopki strony głównej.

    Szuka NIP w <footer> lub w całym tekście strony głównej.
    """

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.settings.scraping_timeout_sec,
                follow_redirects=True,
                headers={"User-Agent": self.settings.user_agent},
            )
        return self._http_client

    async def close(self):
        """Close HTTP client."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def find_nip(
        self,
        company_name: str,
        city: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> NIPResult:
        """
        Szuka NIP na stronie głównej firmy.

        Args:
            company_name: Nazwa firmy
            city: Miasto (nieużywane)
            domain: Domena firmowa (REQUIRED)

        Returns:
            NIPResult
        """
        if not domain:
            logger.debug("Homepage scraper: brak domeny - pomijam")
            return self._create_not_found_result(company_name, city)

        logger.info("Homepage scraper: szukam NIP dla %s na stronie %s", company_name, domain)

        # Warianty URL strony głównej
        urls = [
            f"https://{domain}",
            f"https://www.{domain}",
        ]

        for url in urls:
            try:
                response = await self.http_client.get(url)

                if response.status_code == 200:
                    # Parse HTML
                    soup = BeautifulSoup(response.text, 'lxml')

                    # Strategia 1: Szukaj w <footer>
                    footer = soup.find('footer')
                    if footer:
                        footer_text = footer.get_text()
                        nip = extract_nip_from_text(footer_text)
                        if nip:
                            logger.info("✅ Homepage scraper: NIP znaleziony w <footer> na %s", url)

                            return NIPResult(
                                company_name=company_name,
                                city=city,
                                found=True,
                                nip=nip,
                                nip_formatted=format_nip(nip),
                                confidence=0.85,  # High confidence
                                strategy_used=SearchStrategy.HOMEPAGE_SCRAPER,
                                warnings=[],
                            )

                    # Strategia 2: Szukaj w całym tekście (fallback)
                    full_text = soup.get_text()
                    nip = extract_nip_from_text(full_text)
                    if nip:
                        logger.info("✅ Homepage scraper: NIP znaleziony na stronie %s", url)

                        return NIPResult(
                            company_name=company_name,
                            city=city,
                            found=True,
                            nip=nip,
                            nip_formatted=format_nip(nip),
                            confidence=0.75,  # Lower confidence (może być NIP innej firmy)
                            strategy_used=SearchStrategy.HOMEPAGE_SCRAPER,
                            warnings=["NIP znaleziony poza <footer> - wymaga weryfikacji"],
                        )

            except Exception as e:
                logger.debug("Homepage scraper: błąd dla %s: %s", url, e)
                continue

        # Nie znaleziono
        logger.info("❌ Homepage scraper: NIP nie znaleziony dla %s", company_name)
        return self._create_not_found_result(company_name, city)
