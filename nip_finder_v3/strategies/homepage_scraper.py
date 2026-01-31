"""
Homepage Scraper - wyciąga NIP ze stopki strony głównej.

Firmy często publikują NIP w stopce (<footer>).
Success rate: 70%
Cost: FREE
Time: 1-3s

Dodatkowo zbiera: email, telefon, adres, social links.
"""

import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from ..config import NIPFinderV3Settings, get_settings
from ..models import NIPResult, ScrapedCompanyData, SearchStrategy
from ..utils import (
    extract_addresses_from_text,
    extract_emails_from_text,
    extract_nip_from_text,
    extract_phones_from_text,
    extract_social_links,
    format_nip,
)
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
        Dodatkowo zbiera dane kontaktowe (email, telefon, adres, social).

        Args:
            company_name: Nazwa firmy
            city: Miasto (nieużywane)
            domain: Domena firmowa (REQUIRED)

        Returns:
            NIPResult z scraped_data
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

        # Agregowane dane
        aggregated_scraped = ScrapedCompanyData(domain=domain)

        for url in urls:
            try:
                response = await self.http_client.get(url)

                if response.status_code == 200:
                    # Parse HTML
                    soup = BeautifulSoup(response.text, "lxml")
                    full_text = soup.get_text()

                    # Zbierz dane kontaktowe
                    page_scraped = self._extract_scraped_data(soup, full_text, url, domain)
                    aggregated_scraped = aggregated_scraped.merge(page_scraped)

                    # Strategia 1: Szukaj w <footer>
                    footer = soup.find("footer")
                    if footer:
                        footer_text = footer.get_text()
                        nip = extract_nip_from_text(footer_text)
                        if nip:
                            logger.info("✅ Homepage scraper: NIP znaleziony w <footer> na %s", url)
                            logger.info(
                                "Homepage scraper: zebrano %d email, %d tel, %d social",
                                len(aggregated_scraped.emails),
                                len(aggregated_scraped.phones),
                                len(aggregated_scraped.social_links),
                            )

                            return NIPResult(
                                company_name=company_name,
                                city=city,
                                found=True,
                                nip=nip,
                                nip_formatted=format_nip(nip),
                                confidence=0.85,  # High confidence
                                strategy_used=SearchStrategy.HOMEPAGE_SCRAPER,
                                scraped_data=aggregated_scraped,
                                warnings=[],
                            )

                    # Strategia 2: Szukaj w całym tekście (fallback)
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
                            scraped_data=aggregated_scraped,
                            warnings=["NIP znaleziony poza <footer> - wymaga weryfikacji"],
                        )

            except Exception as e:
                logger.debug("Homepage scraper: błąd dla %s: %s", url, e)
                continue

        # Nie znaleziono NIP, ale może mamy jakieś dane
        logger.info("❌ Homepage scraper: NIP nie znaleziony dla %s", company_name)

        result = self._create_not_found_result(company_name, city)
        # Dołącz zebrane dane nawet jeśli nie znaleziono NIP
        if aggregated_scraped.emails or aggregated_scraped.phones or aggregated_scraped.social_links:
            result.scraped_data = aggregated_scraped
        return result

    def _extract_scraped_data(
        self,
        soup: BeautifulSoup,
        text: str,
        url: str,
        domain: str,
    ) -> ScrapedCompanyData:
        """Wyciąga dane kontaktowe ze strony."""
        return ScrapedCompanyData(
            domain=domain,
            emails=extract_emails_from_text(text),
            phones=extract_phones_from_text(text),
            addresses=extract_addresses_from_text(text),
            social_links=extract_social_links(soup),
            website_title=soup.title.string.strip() if soup.title and soup.title.string else None,
            source_urls=[url],
        )
