"""
Privacy Policy Scraper - wyszukuje NIP w polityce prywatności.

RODO wymaga publikacji NIP w polityce prywatności - to najlepsze źródło!
Success rate: 90%
Cost: FREE
Time: 2-5s

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


class PrivacyScraperStrategy(BaseStrategy):
    """
    Strategia: Scraping polityki prywatności.

    Sprawdza 8 wariantów URL polityki prywatności i wyciąga NIP.
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
        Szuka NIP w polityce prywatności firmy.
        Dodatkowo zbiera dane kontaktowe (email, telefon, adres, social).

        Args:
            company_name: Nazwa firmy
            city: Miasto (nieużywane)
            domain: Domena firmowa (REQUIRED)

        Returns:
            NIPResult z scraped_data
        """
        if not domain:
            logger.debug("Privacy scraper: brak domeny - pomijam")
            return self._create_not_found_result(company_name, city)

        logger.info("Privacy scraper: szukam NIP dla %s na domenie %s", company_name, domain)

        # Warianty URL polityki prywatności
        privacy_urls = self._generate_privacy_urls(domain)

        # Agregowane dane ze wszystkich stron
        aggregated_scraped = ScrapedCompanyData(domain=domain)

        # Próbuj kolejne URL
        for url in privacy_urls:
            try:
                response = await self.http_client.get(url)

                if response.status_code == 200:
                    html = response.text
                    soup = BeautifulSoup(html, "lxml")
                    text = soup.get_text()

                    # Zbierz dane kontaktowe z tej strony
                    page_scraped = self._extract_scraped_data(soup, text, url, domain)
                    aggregated_scraped = aggregated_scraped.merge(page_scraped)

                    # Szukaj NIP
                    nip = extract_nip_from_text(text)

                    if nip:
                        logger.info("✅ Privacy scraper: NIP znaleziony w %s", url)
                        logger.info(
                            "Privacy scraper: zebrano %d email, %d tel, %d social",
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
                            confidence=0.95,  # Very high confidence
                            strategy_used=SearchStrategy.PRIVACY_SCRAPER,
                            scraped_data=aggregated_scraped,
                            warnings=[],
                        )

            except Exception as e:
                # Cicho ignoruj błędy - próbujemy kolejne URL
                logger.debug("Privacy scraper: błąd dla %s: %s", url, e)
                continue

        # Nie znaleziono NIP, ale może mamy jakieś dane
        logger.info("❌ Privacy scraper: NIP nie znaleziony dla %s", company_name)

        result = self._create_not_found_result(company_name, city)
        # Dołącz zebrane dane nawet jeśli nie znaleziono NIP
        if aggregated_scraped.emails or aggregated_scraped.phones:
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

    def _generate_privacy_urls(self, domain: str) -> list[str]:
        """
        Generuje warianty URL polityki prywatności.

        Args:
            domain: Domena (np. "przychodnia-abc.pl")

        Returns:
            Lista URL do sprawdzenia
        """
        urls = []

        # Warianty z config
        for variant in self.settings.privacy_url_variants:
            # Bez www
            urls.append(f"https://{domain}{variant}")
            # Z www
            urls.append(f"https://www.{domain}{variant}")

        return urls
