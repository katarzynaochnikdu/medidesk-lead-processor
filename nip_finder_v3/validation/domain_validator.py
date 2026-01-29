"""
Walidacja NIP względem domeny firmy.

Sprawdza czy znaleziony NIP faktycznie występuje na stronie firmy.
Zapobiega przypisaniu NIP innej firmy.
"""

import logging
from typing import Optional

import httpx

from ..config import NIPFinderV3Settings, get_settings
from ..utils import extract_nip_from_text

logger = logging.getLogger(__name__)


class DomainValidator:
    """
    Walidator NIP względem domeny firmowej.

    Sprawdza czy NIP występuje na stronie o podanej domenie.
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

    async def validate(self, nip: str, domain: str) -> bool:
        """
        Sprawdza czy NIP występuje na domenie firmy.

        Metody:
        1. Sprawdź stronę główną
        2. Sprawdź politykę prywatności
        3. Sprawdź czy NIP występuje w tekście

        Args:
            nip: NIP do sprawdzenia
            domain: Domena firmowa

        Returns:
            True jeśli NIP znaleziony na domenie
        """
        logger.info("Domain validator: sprawdzam NIP %s na domenie %s", nip, domain)

        # URLs do sprawdzenia
        urls = [
            f"https://{domain}",
            f"https://www.{domain}",
            f"https://{domain}/polityka-prywatnosci",
            f"https://www.{domain}/polityka-prywatnosci",
            f"https://{domain}/kontakt",
            f"https://www.{domain}/kontakt",
        ]

        for url in urls:
            try:
                response = await self.http_client.get(url)

                if response.status_code == 200:
                    # Sprawdź czy NIP występuje w tekście
                    if nip in response.text:
                        logger.info("✅ Domain validator: NIP %s znaleziony na %s", nip, url)
                        return True

                    # Sprawdź czy NIP występuje w formacie sformatowanym
                    nip_formatted = f"{nip[0:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:10]}"
                    if nip_formatted in response.text:
                        logger.info("✅ Domain validator: NIP %s znaleziony (sformatowany) na %s",
                                  nip, url)
                        return True

                    # Sprawdź czy NIP występuje z spacjami
                    nip_with_spaces = f"{nip[0:3]} {nip[3:6]} {nip[6:8]} {nip[8:10]}"
                    if nip_with_spaces in response.text:
                        logger.info("✅ Domain validator: NIP %s znaleziony (ze spacjami) na %s",
                                  nip, url)
                        return True

            except Exception as e:
                logger.debug("Domain validator: błąd dla %s: %s", url, e)
                continue

        # Nie znaleziono
        logger.warning("❌ Domain validator: NIP %s NIE znaleziony na domenie %s", nip, domain)
        return False
