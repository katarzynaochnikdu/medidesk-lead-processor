"""
Klient GUS/REGON - pobieranie danych firm z rejestru.
Port sprawdzonego kodu z wFirma/APIV1/app.py.
"""

import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from ..config import Settings, get_settings
from ..models.lead_output import GUSData
from ..utils.validators import is_valid_nip, normalize_nip

logger = logging.getLogger(__name__)


class GUSClient:
    """
    Klient do komunikacji z API GUS/REGON (BIR).
    Obsługuje logowanie SOAP, wyszukiwanie podmiotów i parsowanie odpowiedzi.
    """
    
    # Timeouty
    LOGIN_TIMEOUT = 10
    SEARCH_TIMEOUT = 15
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None
    
    @property
    def api_key(self) -> str:
        return self.settings.gus_api_key
    
    @property
    def bir_host(self) -> str:
        """Host API GUS - test lub produkcja."""
        if self.settings.gus_use_test or self.api_key == "abcde12345abcde12345":
            return "wyszukiwarkaregontest.stat.gov.pl"
        return "wyszukiwarkaregon.stat.gov.pl"
    
    @property
    def bir_url(self) -> str:
        return f"https://{self.bir_host}/wsBIR/UslugaBIRzewnPubl.svc"
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy initialization klienta HTTP."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
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
    
    def _escape_xml(self, unsafe: str) -> str:
        """Bezpieczne wstawianie wartości do SOAP XML."""
        if not isinstance(unsafe, str):
            return ""
        return (
            unsafe.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )
    
    def _decode_bir_inner_xml(self, encoded: str) -> str:
        """Dekodowanie wewnętrznego XML zwracanego przez GUS."""
        if not isinstance(encoded, str):
            return ""
        
        return (
            encoded.lstrip("\ufeff")
            .replace("&amp;amp;", "&amp;")
            .replace("&#xD;", "\r")
            .replace("&#xA;", "\n")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&apos;", "'")
            .replace("&amp;", "&")
            .strip()
        )
    
    def _build_login_envelope(self) -> str:
        """Buduje envelope SOAP do logowania."""
        safe_api_key = self._escape_xml(self.api_key)
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:ns="http://CIS/BIR/PUBL/2014/07">'
            '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            f'<wsa:To>{self.bir_url}</wsa:To>'
            '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Zaloguj</wsa:Action>'
            '</soap:Header>'
            '<soap:Body>'
            '<ns:Zaloguj>'
            f'<ns:pKluczUzytkownika>{safe_api_key}</ns:pKluczUzytkownika>'
            '</ns:Zaloguj>'
            '</soap:Body>'
            '</soap:Envelope>'
        )
    
    def _build_search_envelope(self, nip: str, sid: str) -> str:
        """Buduje envelope SOAP do wyszukiwania po NIP."""
        safe_nip = self._escape_xml(nip)
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:ns="http://CIS/BIR/PUBL/2014/07" '
            'xmlns:q1="http://CIS/BIR/PUBL/2014/07/DataContract" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            f'<wsa:To>{self.bir_url}</wsa:To>'
            '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DaneSzukajPodmioty</wsa:Action>'
            '</soap:Header>'
            '<soap:Body>'
            '<ns:DaneSzukajPodmioty>'
            '<ns:pParametryWyszukiwania>'
            '<q1:Krs xsi:nil="true"/>'
            '<q1:Krsy xsi:nil="true"/>'
            f'<q1:Nip>{safe_nip}</q1:Nip>'
            '<q1:Nipy xsi:nil="true"/>'
            '<q1:Regon xsi:nil="true"/>'
            '<q1:Regony14zn xsi:nil="true"/>'
            '<q1:Regony9zn xsi:nil="true"/>'
            '</ns:pParametryWyszukiwania>'
            '</ns:DaneSzukajPodmioty>'
            '</soap:Body>'
            '</soap:Envelope>'
        )
    
    async def _post_soap(
        self, 
        envelope: str, 
        sid: Optional[str] = None,
        timeout: float = 10.0
    ) -> httpx.Response:
        """Wysyła żądanie SOAP do GUS."""
        client = await self._get_client()
        
        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8",
            "Accept": "application/soap+xml",
        }
        if sid:
            headers["sid"] = sid
        
        response = await client.post(
            self.bir_url,
            content=envelope.encode("utf-8"),
            headers=headers,
            timeout=timeout,
        )
        return response
    
    async def _login(self) -> Optional[str]:
        """Logowanie do GUS - zwraca SID lub None."""
        try:
            envelope = self._build_login_envelope()
            response = await self._post_soap(envelope, timeout=self.LOGIN_TIMEOUT)
            
            # Wyciągnij SID z odpowiedzi
            sid_match = re.search(
                r'<ZalogujResult>([^<]*)</ZalogujResult>', 
                response.text or ''
            )
            sid = sid_match.group(1).strip() if sid_match else None
            
            if sid:
                logger.debug("GUS: Zalogowano, SID otrzymany")
            else:
                logger.warning("GUS: Logowanie nie zwróciło SID")
            
            return sid
            
        except Exception as e:
            logger.error("GUS: Błąd logowania: %s", e)
            return None
    
    def _parse_search_response(self, response_text: str) -> list[dict]:
        """Parsuje odpowiedź wyszukiwania GUS."""
        soap_part = response_text
        
        # Obsługa multipart response
        if 'Content-Type: application/xop+xml' in soap_part:
            match = re.search(
                r'Content-Type: application/xop\+xml[^\r\n]*\r?\n\r?\n([\s\S]*?)\r?\n--uuid:',
                soap_part,
                re.MULTILINE | re.DOTALL,
            )
            if match:
                soap_part = match.group(1)
        
        # Pusty wynik
        if re.search(r'<DaneSzukajResult\s*/>', soap_part):
            return []
        
        # Wyciągnij wynik
        result_match = re.search(
            r'<DaneSzukajPodmiotyResult>([\s\S]*?)</DaneSzukajPodmiotyResult>',
            soap_part,
            re.MULTILINE | re.DOTALL,
        )
        inner_xml = result_match.group(1) if result_match else ''
        
        if not inner_xml:
            return []
        
        # Dekoduj
        decoded_xml = self._decode_bir_inner_xml(inner_xml)
        if not decoded_xml:
            return []
        
        # Parsuj XML
        try:
            root = ET.fromstring(decoded_xml)
        except ET.ParseError as e:
            logger.error("GUS: Błąd parsowania XML: %s", e)
            return []
        
        # Wyciągnij dane
        data_list = []
        for dane in root.findall('.//dane'):
            def get_text(tag: str) -> Optional[str]:
                el = dane.find(tag)
                return el.text if el is not None else None
            
            # Sprawdź czy to błąd
            error_code = get_text('ErrorCode')
            if error_code:
                logger.warning("GUS: ErrorCode=%s: %s", error_code, get_text('ErrorMessagePl'))
                continue
            
            mapped = {
                'regon': get_text('Regon'),
                'nip': get_text('Nip'),
                'nazwa': get_text('Nazwa'),
                'wojewodztwo': get_text('Wojewodztwo'),
                'powiat': get_text('Powiat'),
                'gmina': get_text('Gmina'),
                'miejscowosc': get_text('Miejscowosc'),
                'kodPocztowy': get_text('KodPocztowy'),
                'ulica': get_text('Ulica'),
                'nrNieruchomosci': get_text('NrNieruchomosci'),
                'nrLokalu': get_text('NrLokalu'),
                'typ': get_text('Typ'),
                'silosId': get_text('SilosID'),
                'miejscowoscPoczty': get_text('MiejscowoscPoczty'),
                'krs': get_text('Krs'),
            }
            
            if mapped.get('nazwa'):
                data_list.append(mapped)
        
        return data_list
    
    async def lookup_nip(self, nip: str) -> GUSData:
        """
        Wyszukuje firmę po NIP w rejestrze GUS.
        
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
        
        # Sprawdź czy mamy klucz API
        if not self.api_key:
            return GUSData(found=False, error="Brak klucza GUS_API_KEY")
        
        logger.info("GUS: Wyszukuję NIP=%s (host=%s)", clean_nip, self.bir_host)
        
        try:
            # Logowanie
            sid = await self._login()
            if not sid:
                return GUSData(found=False, error="Logowanie do GUS nie powiodło się")
            
            # Wyszukiwanie
            envelope = self._build_search_envelope(clean_nip, sid)
            response = await self._post_soap(envelope, sid=sid, timeout=self.SEARCH_TIMEOUT)
            
            # Parsowanie
            data_list = self._parse_search_response(response.text or '')
            
            if not data_list:
                logger.info("GUS: NIP %s nie znaleziony", clean_nip)
                return GUSData(found=False, error=None)  # Nie błąd, po prostu nie znaleziono
            
            # Weź pierwszy rekord
            data = data_list[0]
            
            # Zbuduj adres
            address_parts = []
            if data.get('ulica'):
                addr = data['ulica']
                if data.get('nrNieruchomosci'):
                    addr += f" {data['nrNieruchomosci']}"
                if data.get('nrLokalu'):
                    addr += f"/{data['nrLokalu']}"
                address_parts.append(addr)
            
            logger.info(
                "GUS: Znaleziono firmę: %s (REGON: %s)",
                data.get('nazwa', 'N/A'),
                data.get('regon', 'N/A')
            )
            
            return GUSData(
                found=True,
                regon=data.get('regon'),
                full_name=data.get('nazwa'),
                street=data.get('ulica'),
                building_number=data.get('nrNieruchomosci'),
                apartment_number=data.get('nrLokalu'),
                city=data.get('miejscowosc'),
                zip_code=data.get('kodPocztowy'),
                voivodeship=data.get('wojewodztwo'),
                county=data.get('powiat'),
                commune=data.get('gmina'),
                status="active",  # GUS zwraca tylko aktywne podmioty
            )
            
        except httpx.TimeoutException:
            logger.error("GUS: Timeout podczas wyszukiwania NIP=%s", clean_nip)
            return GUSData(found=False, error="Timeout komunikacji z GUS")
        except Exception as e:
            logger.error("GUS: Błąd wyszukiwania NIP=%s: %s", clean_nip, e)
            return GUSData(found=False, error=f"Błąd komunikacji z GUS: {str(e)}")


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
    if not settings.gus_api_key:
        logger.warning("Brak GUS_API_KEY - używam mocka GUS")
        return GUSClientMock()
    
    return GUSClient(settings)
