"""
Homepage Scraper - ostatecznosc, tylko strona glowna firmy.

Wchodzi TYLKO na oficjalna strone firmy (nie katalogi typu ZnanyLekarz).
Scrapuje homepage i /kontakt.
"""

import logging
from typing import Optional, List
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .config import get_settings, NIPFinderV2Settings
from .utils import extract_nips_from_text

logger = logging.getLogger(__name__)


# Domeny katalogow - pomijamy je
DIRECTORY_DOMAINS = [
    "znanylekarz.pl",
    "kliniki.pl",
    "panoramafirm.pl",
    "pkt.pl",
    "yelp.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "youtube.com",
    "google.com",
    "maps.google",
    "krs-online.com",
    "bizraport.pl",
    "rejestr.io",
    "aleo.com",
    "okredo.com",
]


@dataclass
class ScraperResult:
    """Wynik scrapera."""
    nip: str
    source_url: str
    confidence: float


class HomepageScraper:
    """
    Prosty scraper dla stron firmowych.
    
    Strategia:
    1. Znajdz oficjalna strone firmy przez Google
    2. Wejdz tylko na homepage i /kontakt
    3. Wyciagnij NIP z tekstu
    """
    
    def __init__(self, settings: Optional[NIPFinderV2Settings] = None):
        self.settings = settings or get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy init HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.scrape_timeout_sec),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
                follow_redirects=True,
            )
        return self._http_client
    
    def _is_directory(self, url: str) -> bool:
        """Sprawdza czy URL to katalog/portal."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in DIRECTORY_DOMAINS)
    
    def _extract_domain(self, url: str) -> str:
        """Wyciaga domene z URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc
    
    async def _scrape_url(self, url: str) -> Optional[str]:
        """Scrapuje pojedynczy URL i zwraca tekst."""
        try:
            client = await self._get_client()
            response = await client.get(url)
            
            if response.status_code != 200:
                logger.warning("[SCRAPER] HTTP %d: %s", response.status_code, url)
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Usun script, style, nav
            for tag in soup(["script", "style", "nav", "header", "aside", "iframe"]):
                tag.decompose()
            
            text = soup.get_text(separator=" ")
            return text
            
        except Exception as e:
            logger.warning("[SCRAPER] Blad scrapingu %s: %s", url, e)
            return None
    
    async def _find_homepage_url(
        self,
        company_name: str,
        city: Optional[str] = None,
    ) -> Optional[str]:
        """
        Znajduje oficjalna strone firmy przez Google.
        Zwraca pierwszy wynik ktory nie jest katalogiem.
        """
        if not self.settings.has_apify_credentials:
            return None
        
        try:
            from apify_client import ApifyClient
            client = ApifyClient(self.settings.apify_api_token)
            
            # Query
            query = f'"{company_name}"'
            if city:
                query += f' "{city}"'
            query += " strona oficjalna"
            
            run_input = {
                "queries": query,
                "maxPagesPerQuery": 1,
                "resultsPerPage": 10,
                "countryCode": "pl",
                "languageCode": "pl",
            }
            
            run = client.actor(self.settings.apify_google_actor_id).call(
                run_input=run_input,
                timeout_secs=30,
            )
            
            if run.get("status") != "SUCCEEDED":
                return None
            
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                return None
            
            items = list(client.dataset(dataset_id).iterate_items())
            
            for item in items:
                for result in item.get("organicResults", []):
                    url = result.get("url", "")
                    
                    # Pomin katalogi
                    if self._is_directory(url):
                        continue
                    
                    logger.info("[SCRAPER] Znaleziono homepage: %s", url)
                    return url
            
            return None
            
        except Exception as e:
            logger.error("[SCRAPER] Blad szukania homepage: %s", e)
            return None
    
    async def scrape_homepage(
        self,
        company_name: str,
        city: Optional[str] = None,
    ) -> Optional[ScraperResult]:
        """
        Scrapuje strone glowna firmy i szuka NIP.
        
        Args:
            company_name: Nazwa firmy
            city: Miasto (opcjonalne)
        
        Returns:
            ScraperResult jesli znaleziono NIP
        """
        logger.info("[SCRAPER] Szukam homepage dla: %s", company_name)
        
        # Znajdz URL strony glownej
        homepage_url = await self._find_homepage_url(company_name, city)
        
        if not homepage_url:
            logger.info("[SCRAPER] Nie znaleziono oficjalnej strony")
            return None
        
        # Lista stron do sprawdzenia
        domain = self._extract_domain(homepage_url)
        urls_to_check = [
            homepage_url,
            f"https://{domain}/kontakt",
            f"https://{domain}/kontakt/",
            f"https://{domain}/contact",
            f"https://{domain}/o-nas",
            f"https://{domain}/polityka-prywatnosci",
        ]
        
        # Scrapuj strony
        for url in urls_to_check:
            text = await self._scrape_url(url)
            
            if not text:
                continue
            
            # Szukaj NIP
            nips = extract_nips_from_text(text)
            
            if nips:
                logger.info("[SCRAPER] Znaleziono NIP na %s: %s", url, nips[0])
                return ScraperResult(
                    nip=nips[0],
                    source_url=url,
                    confidence=0.6,  # Nizszy confidence niz GUS/Snippets
                )
        
        logger.info("[SCRAPER] Nie znaleziono NIP na stronie firmy")
        return None
    
    async def close(self):
        """Zamyka klienta HTTP."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
