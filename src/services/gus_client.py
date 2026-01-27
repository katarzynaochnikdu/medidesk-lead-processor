"""
Klient GUS/REGON - proxy do zewnętrznego API na Render (wfirma-api).
"""

import logging
from typing import Optional

import httpx

from ..config import Settings, get_settings
from ..models.lead_output import GUSData
from ..utils.validators import is_valid_nip, normalize_nip

logger = logging.getLogger(__name__)


class GUSClient:
    """
    Klient do komunikacji z API GUS przez zewnętrzny serwis wfirma-api na Render.
    Prostsze i bardziej niezawodne niż bezpośrednia komunikacja SOAP.
    """
    
    # Timeouty
    REQUEST_TIMEOUT = 15
    
    # URL API na Render
    DEFAULT_API_URL = "https://wfirma-api.onrender.com"
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None
    
    @property
    def api_url(self) -> str:
        """URL API GUS na Render."""
        return getattr(self.settings, 'gus_api_url', None) or self.DEFAULT_API_URL
    
    @property
    def api_token(self) -> str:
        """Token do autoryzacji API na Render."""
        return self.settings.gus_api_key
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy initialization klienta HTTP."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.REQUEST_TIMEOUT),
                headers={
                    "User-Agent": "LeadProcessor/1.0",
                },
            )
        return self._http_client
    
    async def close(self):
        """Zamknij klienta HTTP."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def lookup_nip(self, nip: str) -> GUSData:
        """
        Wyszukuje firmę po NIP przez API na Render.
        
        Args:
            nip: NIP (10 cyfr)
        
        Returns:
            GUSData z danymi firmy lub informacją o błędzie
        """
        # Normalizuj NIP
        clean_nip = normalize_nip(nip)
        
        if not clean_nip:
            return GUSData(found=False, error="Nieprawidłowy format NIP")
        
        # Walidacja sumy kontrolnej
        if not is_valid_nip(clean_nip):
            return GUSData(found=False, error="NIP nie przechodzi walidacji sumy kontrolnej")
        
        # Sprawdź czy mamy token API
        if not self.api_token or self.api_token.startswith("your-"):
            logger.warning("GUS: Brak tokenu API - pomijam wyszukiwanie")
            return GUSData(found=False, error="Brak klucza GUS_API_KEY")
        
        logger.info("GUS: Wyszukuję NIP=%s przez %s", clean_nip, self.api_url)
        
        try:
            client = await self._get_client()
            
            # Wywołaj API na Render
            response = await client.post(
                f"{self.api_url}/api/gus/name-by-nip",
                json={"nip": clean_nip},
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": self.api_token,
                },
            )
            
            # Sprawdź odpowiedź
            if response.status_code == 401:
                logger.error("GUS: Nieprawidłowy token API")
                return GUSData(found=False, error="Nieprawidłowy token API GUS")
            
            if response.status_code == 404:
                logger.info("GUS: NIP %s nie znaleziony", clean_nip)
                return GUSData(found=False, error=None)
            
            if response.status_code != 200:
                logger.error("GUS: Błąd API: %s", response.status_code)
                return GUSData(found=False, error=f"Błąd API GUS: {response.status_code}")
            
            # Parsuj odpowiedź
            data = response.json()
            
            # Sprawdź czy znaleziono
            if not data.get("found") and not data.get("nazwa"):
                return GUSData(found=False, error=None)
            
            logger.info(
                "GUS: Znaleziono firmę: %s (REGON: %s)",
                data.get('nazwa', 'N/A'),
                data.get('regon', 'N/A')
            )
            
            # Mapuj odpowiedź z Render API na GUSData
            return GUSData(
                found=True,
                regon=data.get('regon'),
                full_name=data.get('nazwa') or data.get('full_name'),
                short_name=data.get('short_name'),
                street=data.get('ulica') or data.get('street'),
                building_number=data.get('nrNieruchomosci') or data.get('building_number'),
                apartment_number=data.get('nrLokalu') or data.get('apartment_number'),
                city=data.get('miejscowosc') or data.get('city'),
                zip_code=data.get('kodPocztowy') or data.get('zip_code'),
                voivodeship=data.get('wojewodztwo') or data.get('voivodeship'),
                county=data.get('powiat') or data.get('county'),
                commune=data.get('gmina') or data.get('commune'),
                status="active",  # API zwraca tylko aktywne podmioty
            )
            
        except httpx.TimeoutException:
            logger.error("GUS: Timeout podczas wyszukiwania NIP=%s", clean_nip)
            return GUSData(found=False, error="Timeout komunikacji z API GUS")
        except Exception as e:
            logger.error("GUS: Błąd wyszukiwania NIP=%s: %s", clean_nip, e)
            return GUSData(found=False, error=f"Błąd komunikacji z API GUS: {str(e)}")


class GUSClientMock:
    """
    Mock klienta GUS do testów lokalnych.
    Zwraca przykładowe dane bez faktycznej komunikacji z API.
    """
    
    # Przykładowe dane testowe
    TEST_DATA = {
        "1234567890": {
            "regon": "123456789",
            "full_name": "TESTOWA FIRMA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
            "short_name": "TESTOWA FIRMA SP. Z O.O.",
            "street": "ul. Testowa",
            "building_number": "1",
            "city": "Warszawa",
            "zip_code": "00-001",
            "voivodeship": "MAZOWIECKIE",
            "status": "active",
        }
    }
    
    async def lookup_nip(self, nip: str) -> GUSData:
        """Mock wyszukiwania NIP."""
        clean_nip = normalize_nip(nip)
        
        if not clean_nip:
            return GUSData(found=False, error="Nieprawidłowy format NIP")
        
        if not is_valid_nip(clean_nip):
            return GUSData(found=False, error="NIP nie przechodzi walidacji sumy kontrolnej")
        
        # Sprawdź czy mamy dane testowe
        if clean_nip in self.TEST_DATA:
            data = self.TEST_DATA[clean_nip]
            return GUSData(found=True, **data)
        
        # Generuj przykładowe dane dla dowolnego poprawnego NIP
        return GUSData(
            found=True,
            regon=f"{clean_nip[:9]}",
            full_name=f"FIRMA TESTOWA NIP {clean_nip}",
            city="Warszawa",
            zip_code="00-000",
            status="active",
        )
    
    async def close(self):
        """Mock close - nic nie robi."""
        pass


def get_gus_client(settings: Optional[Settings] = None, use_mock: bool = False) -> GUSClient:
    """
    Factory function - zwraca odpowiedni klient GUS.
    
    Args:
        settings: Ustawienia aplikacji
        use_mock: Czy użyć mocka (do testów)
    
    Returns:
        GUSClient lub GUSClientMock
    """
    if use_mock:
        return GUSClientMock()
    
    settings = settings or get_settings()
    
    # Jeśli brak klucza API, użyj mocka
    if not settings.gus_api_key or settings.gus_api_key.startswith("your-"):
        logger.warning("Brak GUS_API_KEY - używam mocka GUS")
        return GUSClientMock()
    
    return GUSClient(settings)
