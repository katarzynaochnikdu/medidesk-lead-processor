"""
NIP Lookup - wyszukiwanie danych firmy po NIP.

Workflow:
1. NIP -> GUS API (przez wspólny GUSClient z src/) -> nazwa firmy, adres siedziby
2. Nazwa firmy -> Google Search -> strona WWW
3. Strona WWW -> normalna analiza

UWAGA: GUS lookup jest delegowany do src/services/gus_client.py
żeby uniknąć duplikacji kodu i zapewnić re-używanie wyników.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional, List
from urllib.parse import urlparse

import httpx

from .config import CompanyIntelSettings, get_settings

# Import wspólnego GUSClient z src/
try:
    from src.services.gus_client import GUSClient as SharedGUSClient, get_gus_client
    from src.config import get_settings as get_src_settings
    SHARED_GUS_AVAILABLE = True
except ImportError:
    SHARED_GUS_AVAILABLE = False
    SharedGUSClient = None
    get_gus_client = None
    get_src_settings = None

logger = logging.getLogger(__name__)


@dataclass
class GUSCompanyData:
    """Dane firmy z GUS."""
    nip: str
    regon: Optional[str] = None
    full_name: Optional[str] = None
    short_name: Optional[str] = None
    street: Optional[str] = None
    building_number: Optional[str] = None
    apartment_number: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    voivodeship: Optional[str] = None
    found: bool = False
    error: Optional[str] = None


@dataclass
class NIPLookupResult:
    """Wynik wyszukiwania po NIP."""
    nip: str
    gus_data: Optional[GUSCompanyData] = None
    company_name: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    found: bool = False
    error: Optional[str] = None


def normalize_nip(nip: str) -> Optional[str]:
    """Normalizuje NIP do 10 cyfr."""
    if not nip:
        return None
    # Usuń wszystko poza cyframi
    clean = re.sub(r'\D', '', str(nip))
    if len(clean) == 10:
        return clean
    return None


def validate_nip_checksum(nip: str) -> bool:
    """Sprawdza sumę kontrolną NIP."""
    if not nip or len(nip) != 10:
        return False
    
    weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    try:
        checksum = sum(int(nip[i]) * weights[i] for i in range(9)) % 11
        return checksum == int(nip[9])
    except (ValueError, IndexError):
        return False


class NIPLookup:
    """
    Wyszukuje dane firmy po NIP.
    
    Używa:
    1. GUS API (przez wspólny GUSClient z src/services/)
    2. Google Search (przez Apify) jako fallback
    
    UWAGA: GUS lookup jest delegowany do src/services/gus_client.py
    żeby uniknąć duplikacji kodu i zapewnić re-używanie wyników.
    """
    
    # GUS API na Render (fallback jeśli SharedGUSClient niedostępny)
    GUS_API_URL = "https://wfirma-api.onrender.com"
    
    def __init__(self, settings: Optional[CompanyIntelSettings] = None):
        self.settings = settings or get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._apify_client = None
        self._apify_initialized = False
        
        # Wspólny GUSClient (jeśli dostępny)
        self._shared_gus_client = None
        if SHARED_GUS_AVAILABLE:
            try:
                src_settings = get_src_settings()
                self._shared_gus_client = get_gus_client(src_settings)
                logger.info("NIPLookup: Używam wspólnego GUSClient z src/services/")
            except Exception as e:
                logger.warning("NIPLookup: Nie udało się zainicjalizować wspólnego GUSClient: %s", e)
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy init HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30),
                headers={"User-Agent": "CompanyIntel/1.0"},
            )
        return self._http_client
    
    def _init_apify(self) -> bool:
        """Initialize Apify client."""
        if self._apify_initialized:
            return self._apify_client is not None
        
        try:
            from apify_client import ApifyClient
            
            if not self.settings.apify_api_token:
                logger.warning("NIPLookup: brak Apify API token")
                self._apify_initialized = True
                return False
            
            self._apify_client = ApifyClient(self.settings.apify_api_token)
            self._apify_initialized = True
            return True
        except Exception as e:
            logger.error("NIPLookup: Apify init error: %s", e)
            self._apify_initialized = True
            return False
    
    async def lookup_gus(self, nip: str) -> GUSCompanyData:
        """
        Wyszukuje firmę w GUS po NIP.
        
        Deleguje do wspólnego GUSClient z src/services/ jeśli dostępny.
        Fallback do własnej implementacji jeśli nie.
        
        Args:
            nip: NIP (10 cyfr)
        
        Returns:
            GUSCompanyData z danymi firmy
        """
        clean_nip = normalize_nip(nip)
        
        if not clean_nip:
            return GUSCompanyData(nip=nip, found=False, error="Nieprawidłowy format NIP")
        
        if not validate_nip_checksum(clean_nip):
            return GUSCompanyData(nip=clean_nip, found=False, error="NIP nie przechodzi walidacji sumy kontrolnej")
        
        # Użyj wspólnego GUSClient jeśli dostępny
        if self._shared_gus_client is not None:
            try:
                gus_data = await self._shared_gus_client.lookup_nip(clean_nip)
                
                # Konwertuj GUSData (z src/) na GUSCompanyData (lokalny format)
                return GUSCompanyData(
                    nip=clean_nip,
                    regon=gus_data.regon,
                    full_name=gus_data.full_name,
                    short_name=gus_data.short_name,
                    street=gus_data.street,
                    building_number=gus_data.building_number,
                    apartment_number=gus_data.apartment_number,
                    city=gus_data.city,
                    zip_code=gus_data.zip_code,
                    voivodeship=gus_data.voivodeship,
                    found=gus_data.found,
                    error=gus_data.error,
                )
            except Exception as e:
                logger.warning("NIPLookup: Wspólny GUSClient failed, using fallback: %s", e)
        
        # Fallback: własna implementacja
        return await self._lookup_gus_fallback(clean_nip)
    
    async def _lookup_gus_fallback(self, clean_nip: str) -> GUSCompanyData:
        """
        Fallback implementacja GUS lookup (używana jeśli wspólny GUSClient niedostępny).
        """
        # Sprawdź czy mamy klucz GUS API
        gus_api_key = getattr(self.settings, 'gus_api_key', None)
        if not gus_api_key:
            logger.warning("NIPLookup: Brak GUS_API_KEY - pomijam GUS lookup")
            return GUSCompanyData(nip=clean_nip, found=False, error="Brak klucza GUS_API_KEY")
        
        logger.info("NIPLookup: Szukam NIP=%s w GUS (fallback)", clean_nip)
        
        try:
            client = await self._get_http_client()
            
            response = await client.post(
                f"{self.GUS_API_URL}/api/gus/name-by-nip",
                json={"nip": clean_nip},
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": gus_api_key,
                },
            )
            
            if response.status_code == 401:
                return GUSCompanyData(nip=clean_nip, found=False, error="Nieprawidłowy token GUS API")
            
            if response.status_code == 404:
                logger.info("NIPLookup: NIP %s nie znaleziony w GUS", clean_nip)
                return GUSCompanyData(nip=clean_nip, found=False)
            
            if response.status_code != 200:
                return GUSCompanyData(nip=clean_nip, found=False, error=f"GUS API error: {response.status_code}")
            
            data = response.json()
            
            # API zwraca {"data": [...]} lub bezpośredni obiekt
            if isinstance(data, dict) and "data" in data:
                data_list = data.get("data", [])
                if data_list:
                    data = data_list[0]
                else:
                    return GUSCompanyData(nip=clean_nip, found=False)
            
            logger.info("NIPLookup: GUS znalazł: %s", data.get('nazwa', 'N/A')[:60])
            
            return GUSCompanyData(
                nip=clean_nip,
                regon=data.get('regon'),
                full_name=data.get('nazwa') or data.get('full_name'),
                short_name=data.get('short_name'),
                street=data.get('ulica') or data.get('street'),
                building_number=data.get('nrNieruchomosci') or data.get('building_number'),
                apartment_number=data.get('nrLokalu') or data.get('apartment_number'),
                city=data.get('miejscowosc') or data.get('city'),
                zip_code=data.get('kodPocztowy') or data.get('zip_code'),
                voivodeship=data.get('wojewodztwo') or data.get('voivodeship'),
                found=True,
            )
            
        except httpx.TimeoutException:
            logger.error("NIPLookup: GUS timeout dla NIP=%s", clean_nip)
            return GUSCompanyData(nip=clean_nip, found=False, error="GUS API timeout")
        except Exception as e:
            logger.error("NIPLookup: GUS error dla NIP=%s: %s", clean_nip, e)
            return GUSCompanyData(nip=clean_nip, found=False, error=str(e))
    
    async def find_website_google(self, company_name: str, city: Optional[str] = None) -> Optional[str]:
        """
        Wyszukuje stronę WWW firmy przez Google Search.
        
        Args:
            company_name: Nazwa firmy
            city: Miasto (opcjonalne)
        
        Returns:
            URL strony WWW lub None
        """
        if not self._init_apify():
            logger.warning("NIPLookup: Apify niedostępne - nie można szukać strony")
            return None
        
        # Przygotuj query
        query = company_name
        if city:
            query = f"{company_name} {city}"
        
        # Dodaj "strona" żeby preferować oficjalną stronę
        query = f"{query} strona oficjalna"
        
        logger.info("NIPLookup: Google Search query='%s'", query)
        
        try:
            import asyncio
            
            # Apify Google Search
            run_input = {
                "queries": query,
                "maxPagesPerQuery": 1,
                "resultsPerPage": 10,
                "languageCode": "pl",
                "countryCode": "pl",
            }
            
            # Run Apify actor
            run = await asyncio.to_thread(
                lambda: self._apify_client.actor("apify/google-search-scraper").call(
                    run_input=run_input,
                    timeout_secs=60,
                    memory_mbytes=256,
                )
            )
            
            # Get results
            items = list(self._apify_client.dataset(run["defaultDatasetId"]).iterate_items())
            
            if not items:
                logger.info("NIPLookup: Google nie zwrócił wyników")
                return None
            
            # Znajdź najlepszy URL
            organic_results = items[0].get("organicResults", [])
            
            # Filtruj wyniki - szukamy strony firmy, nie katalogów
            blacklist_domains = [
                "facebook.com", "linkedin.com", "instagram.com", "twitter.com",
                "youtube.com", "tiktok.com", "znany lekarz", "znanylekarz.pl",
                "google.com", "google.pl", "gov.pl", "wikipedia.org",
                "krs-online.com.pl", "rejestr.io", "panoramafirm.pl",
                "pkt.pl", "aleo.com", "firmy.net", "gowork.pl",
                "krs-pobierz.pl", "krs.pl", "infoveriti.pl", "emis.com",
                "opencorporates.com", "companywall.pl", "baza-firm.com.pl",
                "biznes.gov.pl", "ceidg.gov.pl", "prod.ceidg.gov.pl",
                "regon.stat.gov.pl", "stat.gov.pl", "bip.",
            ]
            
            for result in organic_results[:5]:
                url = result.get("url", "")
                if not url:
                    continue
                
                # Sprawdź czy to nie blacklisted domain
                domain = urlparse(url).netloc.lower()
                if any(bl in domain for bl in blacklist_domains):
                    continue
                
                # Sprawdź czy nazwa firmy jest w tytule lub URL
                title = result.get("title", "").lower()
                company_lower = company_name.lower()
                
                # Wyciągnij słowa kluczowe z nazwy firmy
                keywords = [w for w in company_lower.split() if len(w) > 3]
                
                # Czy tytuł lub domena zawiera słowa kluczowe?
                if any(kw in title or kw in domain for kw in keywords):
                    logger.info("NIPLookup: Znaleziono stronę: %s", url)
                    return url
            
            # Fallback - weź pierwszy nieblacklisted wynik
            for result in organic_results[:3]:
                url = result.get("url", "")
                domain = urlparse(url).netloc.lower()
                if not any(bl in domain for bl in blacklist_domains):
                    logger.info("NIPLookup: Fallback strona: %s", url)
                    return url
            
            logger.info("NIPLookup: Nie znaleziono pasującej strony")
            return None
            
        except Exception as e:
            logger.error("NIPLookup: Google Search error: %s", e)
            return None
    
    async def search_by_nip_google(self, nip: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Wyszukuje firmę przez Google po NIP.
        Wyciąga nazwę firmy i stronę WWW z wyników wyszukiwania.
        
        Returns:
            (company_name, website, city)
        """
        if not self._init_apify():
            return None, None, None
        
        # Szukaj NIP w Google
        query = f'"{nip}" firma'  # Cudzysłów wymusza dokładne dopasowanie NIP
        
        logger.info("NIPLookup: Google Search for NIP='%s'", nip)
        
        try:
            import asyncio
            
            run_input = {
                "queries": query,
                "maxPagesPerQuery": 1,
                "resultsPerPage": 10,
                "languageCode": "pl",
                "countryCode": "pl",
            }
            
            run = await asyncio.to_thread(
                lambda: self._apify_client.actor("apify/google-search-scraper").call(
                    run_input=run_input,
                    timeout_secs=60,
                    memory_mbytes=256,
                )
            )
            
            items = list(self._apify_client.dataset(run["defaultDatasetId"]).iterate_items())
            
            if not items:
                return None, None, None
            
            organic_results = items[0].get("organicResults", [])
            
            # Blacklist domen
            blacklist_domains = [
                "facebook.com", "linkedin.com", "instagram.com", "twitter.com",
                "youtube.com", "tiktok.com", "znanylekarz.pl", "docplanner",
                "google.com", "google.pl", "gov.pl", "wikipedia.org",
                "krs-online.com.pl", "rejestr.io", "panoramafirm.pl",
                "pkt.pl", "aleo.com", "firmy.net", "gowork.pl",
                "krs-pobierz.pl", "krs.pl", "infoveriti.pl", "emis.com",
                "opencorporates.com", "companywall.pl", "baza-firm.com.pl",
                "biznes.gov.pl", "ceidg.gov.pl", "prod.ceidg.gov.pl",
                "regon.stat.gov.pl", "stat.gov.pl", "bip.", "praca.pl",
            ]
            
            company_name = None
            website = None
            city = None
            
            for result in organic_results[:7]:
                url = result.get("url", "")
                title = result.get("title", "")
                description = result.get("description", "")
                
                if not url:
                    continue
                
                domain = urlparse(url).netloc.lower()
                
                # Pomijaj blacklisted
                if any(bl in domain for bl in blacklist_domains):
                    continue
                
                # Znaleziono potencjalną stronę firmy
                if not website:
                    website = url
                    logger.info("NIPLookup: Znaleziono potencjalną stronę: %s", url)
                
                # Wyciągnij nazwę firmy z tytułu
                if not company_name and title:
                    # Usuń typowe suffiksy z tytułu
                    name = title
                    for suffix in [" - strona główna", " - oficjalna strona", " | Facebook", " - Kontakt", " - Home"]:
                        name = name.replace(suffix, "").replace(suffix.lower(), "")
                    company_name = name.strip()[:100]
                
                # Wyciągnij miasto z opisu jeśli jest
                if not city and description:
                    import re
                    city_match = re.search(r'\b(Warszawa|Kraków|Wrocław|Poznań|Gdańsk|Łódź|Katowice|Szczecin|Bydgoszcz|Lublin|Białystok|Olsztyn|Toruń|Rzeszów|Kielce|Częstochowa|Radom|Sosnowiec|Gliwice|Zabrze|Bytom|Ruda Śląska|Rybnik|Tychy|Dąbrowa Górnicza|Płock|Elbląg|Opole|Gorzów)\b', description, re.IGNORECASE)
                    if city_match:
                        city = city_match.group(1).title()
                
                if company_name and website:
                    break
            
            logger.info("NIPLookup: Z Google: nazwa='%s', www='%s', miasto='%s'", 
                       company_name[:50] if company_name else None, website, city)
            
            return company_name, website, city
            
        except Exception as e:
            logger.error("NIPLookup: Google Search error: %s", e)
            return None, None, None
    
    async def lookup(self, nip: str) -> NIPLookupResult:
        """
        Pełne wyszukiwanie firmy po NIP.
        
        Próbuje najpierw GUS, potem Google.
        
        Args:
            nip: NIP (10 cyfr)
        
        Returns:
            NIPLookupResult z danymi firmy i stroną WWW
        """
        clean_nip = normalize_nip(nip)
        
        if not clean_nip:
            return NIPLookupResult(nip=nip, found=False, error="Nieprawidłowy format NIP")
        
        if not validate_nip_checksum(clean_nip):
            return NIPLookupResult(nip=clean_nip, found=False, error="NIP nie przechodzi walidacji")
        
        logger.info("=" * 60)
        logger.info("NIPLookup: Rozpoczynam wyszukiwanie NIP=%s", clean_nip)
        
        # Step 1: GUS lookup
        gus_data = await self.lookup_gus(clean_nip)
        
        if gus_data.found:
            # GUS zadziałał - szukamy strony przez Google
            company_name = gus_data.short_name or gus_data.full_name
            city = gus_data.city
            
            website = await self.find_website_google(company_name, city)
            
            logger.info(
                "NIPLookup: GUS + Google: nazwa='%s', miasto='%s', www='%s'",
                company_name[:50] if company_name else None, city, website
            )
            
            return NIPLookupResult(
                nip=clean_nip,
                gus_data=gus_data,
                company_name=company_name,
                website=website,
                city=city,
                found=True,
            )
        
        # Step 2: GUS nie zadziałał - szukamy wszystkiego przez Google
        logger.info("NIPLookup: GUS niedostępny, szukam przez Google NIP=%s", clean_nip)
        
        company_name, website, city = await self.search_by_nip_google(clean_nip)
        
        if website or company_name:
            return NIPLookupResult(
                nip=clean_nip,
                gus_data=gus_data,
                company_name=company_name,
                website=website,
                city=city,
                found=True,
            )
        
        # Nic nie znaleziono
        return NIPLookupResult(
            nip=clean_nip,
            gus_data=gus_data,
            company_name=None,
            website=None,
            city=None,
            found=False,
            error="Nie znaleziono firmy dla podanego NIP",
        )
    
    async def close(self):
        """Zamyka zasoby."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
