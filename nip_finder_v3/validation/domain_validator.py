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


# Registry/portal domains - walidacja domeny nie ma sensu, NIP musi być walidowany przez GUS
REGISTRY_DOMAINS = {
    # Portale z opiniami/danymi firm
    "gowork.pl",
    "oferteo.pl",
    "aleo.com",
    "panoramafirm.pl",
    "pkt.pl",
    "firmy.net",
    "baza-firm.com.pl",
    "branżowiec.pl",
    "owg.pl",  # Ogólnopolski Wykaz Gabinetów
    "hipokrates.org",
    "medigo.pl",
    # Rejestry KRS/NIP
    "krs-online.com.pl",
    "rejestr.io",
    "infoveriti.pl",
    "krs.pl",
    "ceidg.gov.pl",
    "mojepanstwo.pl",
    "biznes-polska.pl",
    "companywall.pl",
    "regon.stat.gov.pl",
    "prod.ceidg.gov.pl",
    # Portale biznesowe
    "businessinsight.pl",
    "okredo.com",
    "dun.com",
    "bisnode.pl",
    "emis.com",
    "firmypolskie.pl",
    # Social / mapy / opinie
    "facebook.com",
    "linkedin.com",
    "google.com",
    "google.pl",
    "znany.pl",
    "znanylekarz.pl",
    "znamylekarza.pl",
    "trustpilot.com",
    "yelp.com",
    # Portale gov
    "gov.pl",
    "stat.gov.pl",
}


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

    def is_registry_domain(self, domain: str, company_name: str = None) -> bool:
        """
        Sprawdza czy domena to portal/rejestr (nie oficjalna strona firmy).
        
        Dla takich domen walidacja NIP na stronie nie ma sensu,
        bo portale nie publikują NIPów firm w standardowy sposób.
        
        Heurystyka:
        1. Sprawdź czy domena jest na liście znanych rejestrów
        2. Jeśli podano company_name, sprawdź czy domena "pasuje" do nazwy firmy
           (np. awodent -> awodent.pl pasuje, owg.pl nie pasuje)
        """
        domain_lower = domain.lower().strip()
        
        # Sprawdź czy domena jest na liście znanych rejestrów
        for registry in REGISTRY_DOMAINS:
            if domain_lower == registry or domain_lower.endswith("." + registry):
                return True
        
        # Heurystyka: sprawdź czy domena pasuje do nazwy firmy
        if company_name:
            company_lower = company_name.lower().strip()
            # Wyciągnij główną część domeny (bez TLD)
            domain_base = domain_lower.split('.')[0].replace('-', '').replace('_', '')
            company_base = company_lower.split()[0].replace('-', '').replace('_', '')
            
            # Jeśli domena NIE zawiera nazwy firmy -> prawdopodobnie portal
            if company_base and len(company_base) >= 3:
                if company_base not in domain_base and domain_base not in company_base:
                    logger.debug("Registry heuristic: '%s' doesn't match company '%s' -> treating as registry", 
                               domain, company_name)
                    return True
        
        return False

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
            True jeśli NIP znaleziony na domenie, lub None jeśli registry domain
        """
        # Dla registry domen (portale, rejestry) - skip walidacji
        if self.is_registry_domain(domain):
            logger.info("⏭️ Domain validator: %s to registry/portal - pomijam walidację domeny", domain)
            return None  # None = nie sprawdzono (nie False!)
        
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
