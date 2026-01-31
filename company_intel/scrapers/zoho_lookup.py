"""
Zoho CRM Lookup - weryfikacja czy lokalizacja istnieje w CRM.

Sprawdza po:
- NIP (najsilniejsze dopasowanie)
- Adres (ulica + miasto)
- Domena www

Zwraca status klienta i typ lokalizacji (Siedziba/Filia).
"""

import logging
import time
import urllib.parse
from typing import Optional, List

import httpx

from ..config import CompanyIntelSettings, get_settings
from ..models import ZohoMatch, Adres


logger = logging.getLogger(__name__)


# Pola do pobrania przy wyszukiwaniu
ACCOUNT_SEARCH_FIELDS = [
    "id",
    "Account_Name",
    "Firma_NIP",
    "Website",
    "Domena_z_www",
    # Adres siedziby
    "Billing_Street",
    "Billing_Street_Name",
    "Billing_Building_Number",
    "Billing_Local_Number",
    "Billing_City",
    "Billing_Code",
    # Adres filii
    "Shipping_Street",
    "Shipping_Street_Name",
    "Shipping_Building_Number",
    "Shipping_Local_Number",
    "Shipping_City",
    "Shipping_Code",
    # Status i typ
    "Status_klienta",
    "Adres_w_rekordzie",
    "Siedziba_tick",
    "Filia_tick",
    "Siedziba_i_Filia_tick",
    # Relacje
    "Parent_Account",
]


class ZohoLookupScraper:
    """
    Scraper do weryfikacji lokalizacji w Zoho CRM.
    """
    
    REQUEST_TIMEOUT = 30
    
    def __init__(self, settings: Optional[CompanyIntelSettings] = None):
        self.settings = settings or get_settings()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._http_client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
    
    @property
    def api_base(self) -> str:
        return f"{self.settings.zoho_api_base}/crm/v2"
    
    @property
    def oauth_base(self) -> str:
        return self.settings.zoho_oauth_base
    
    def _has_credentials(self) -> bool:
        """Sprawdza czy mamy credentials do Zoho."""
        if not self.settings.zoho_refresh_token:
            return False
        if not self.settings.zoho_client_id:
            return False
        if not self.settings.zoho_client_secret:
            return False
        # Sprawdź czy to nie placeholdery
        placeholders = ["your-", "xxx", "placeholder", "changeme"]
        for val in [self.settings.zoho_client_id, self.settings.zoho_client_secret, self.settings.zoho_refresh_token]:
            if any(p in val.lower() for p in placeholders):
                return False
        return True
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy initialization klienta HTTP."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.REQUEST_TIMEOUT),
            )
        return self._http_client
    
    async def close(self):
        """Zamknij klienta HTTP."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def _refresh_access_token(self) -> Optional[str]:
        """Odświeża access token używając refresh tokena."""
        if not self._has_credentials():
            self.logger.warning("Zoho: Brak credentials - lookup wyłączony")
            return None
        
        client = await self._get_client()
        
        try:
            url = f"{self.oauth_base}/oauth/v2/token"
            data = {
                "grant_type": "refresh_token",
                "client_id": self.settings.zoho_client_id,
                "client_secret": self.settings.zoho_client_secret,
                "refresh_token": self.settings.zoho_refresh_token,
            }
            
            self.logger.debug("Zoho: Odświeżam access token...")
            response = await client.post(url, data=data)
            result = response.json()
            
            if "access_token" in result:
                self._access_token = result["access_token"]
                expires_in = int(result.get("expires_in", 3600))
                self._token_expires_at = time.time() + expires_in - 60
                self.logger.info("Zoho: Token odświeżony, wygasa za %ds", expires_in)
                return self._access_token
            else:
                error = result.get("error", "unknown")
                self.logger.error("Zoho: Błąd odświeżania tokena: %s", error)
                return None
                
        except Exception as e:
            self.logger.error("Zoho: Wyjątek podczas odświeżania tokena: %s", e)
            return None
    
    async def _get_access_token(self) -> Optional[str]:
        """Zwraca ważny access token."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        return await self._refresh_access_token()
    
    async def _search_accounts(self, criteria: str) -> List[dict]:
        """Wyszukuje rekordy Accounts."""
        token = await self._get_access_token()
        if not token:
            return []
        
        client = await self._get_client()
        
        try:
            encoded_criteria = urllib.parse.quote(criteria)
            fields = ",".join(ACCOUNT_SEARCH_FIELDS)
            url = f"{self.api_base}/Accounts/search?criteria={encoded_criteria}&fields={fields}"
            
            headers = {
                "Authorization": f"Zoho-oauthtoken {token}",
                "Content-Type": "application/json",
            }
            
            response = await client.get(url, headers=headers)
            
            if response.status_code == 204:
                return []
            
            result = response.json()
            return result.get("data", []) or []
            
        except Exception as e:
            self.logger.error("Zoho search error: %s", e)
            return []
    
    def _build_zoho_match(self, record: dict, match_reason: str) -> ZohoMatch:
        """Buduje ZohoMatch z rekordu Zoho."""
        # Wyciągnij parent info
        parent_account = record.get("Parent_Account")
        parent_id = None
        parent_name = None
        if isinstance(parent_account, dict):
            parent_id = parent_account.get("id")
            parent_name = parent_account.get("name")
        
        # Typ adresu
        adres_w_rekordzie = record.get("Adres_w_rekordzie")
        is_siedziba = bool(record.get("Siedziba_tick"))
        is_filia = bool(record.get("Filia_tick"))
        is_siedziba_i_filia = bool(record.get("Siedziba_i_Filia_tick"))
        
        # Jeśli checkboxy nie są ustawione, spróbuj z pola picklist
        if not is_siedziba and not is_filia and adres_w_rekordzie:
            if "Siedziba i Filia" in adres_w_rekordzie:
                is_siedziba = True
                is_filia = True
            elif "Siedziba" in adres_w_rekordzie:
                is_siedziba = True
            elif "Filia" in adres_w_rekordzie:
                is_filia = True
        
        if is_siedziba_i_filia:
            is_siedziba = True
            is_filia = True
        
        return ZohoMatch(
            found=True,
            zoho_id=record.get("id"),
            zoho_name=record.get("Account_Name"),
            nip=record.get("Firma_NIP"),  # NIP firmy z Zoho
            status_klienta=record.get("Status_klienta"),
            adres_w_rekordzie=adres_w_rekordzie,
            is_siedziba=is_siedziba,
            is_filia=is_filia,
            parent_id=parent_id,
            parent_name=parent_name,
            match_reason=match_reason,
        )
    
    async def lookup_by_nip(self, nip: str) -> List[ZohoMatch]:
        """
        Szuka rekordów po NIP.
        Zwraca wszystkie dopasowania (siedziba + filie).
        """
        if not nip:
            return []
        
        clean_nip = "".join(c for c in nip if c.isdigit())
        if len(clean_nip) != 10:
            return []
        
        self.logger.info("Zoho lookup by NIP: %s", clean_nip)
        
        criteria = f"(Firma_NIP:equals:{clean_nip})"
        records = await self._search_accounts(criteria)
        
        matches = []
        for record in records:
            match = self._build_zoho_match(record, "NIP")
            matches.append(match)
        
        self.logger.info("Zoho: Znaleziono %d rekordów po NIP", len(matches))
        return matches
    
    async def lookup_by_address(self, ulica: str, miasto: str) -> List[ZohoMatch]:
        """
        Szuka rekordów po adresie.
        Sprawdza zarówno adres siedziby jak i filii.
        """
        if not ulica or not miasto:
            return []
        
        self.logger.info("Zoho lookup by address: %s, %s", ulica, miasto)
        
        # Normalizuj ulicę - usuń "ul." i podobne
        ulica_clean = ulica.lower().strip()
        for prefix in ["ul.", "ul ", "ulica "]:
            if ulica_clean.startswith(prefix):
                ulica_clean = ulica_clean[len(prefix):].strip()
                break
        
        matches = []
        
        # Szukaj w adresie siedziby (Billing)
        criteria = f"((Billing_City:equals:{miasto})and(Billing_Street:contains:{ulica_clean}))"
        records = await self._search_accounts(criteria)
        for record in records:
            match = self._build_zoho_match(record, "adres siedziby")
            if match.zoho_id not in [m.zoho_id for m in matches]:
                matches.append(match)
        
        # Szukaj w adresie filii (Shipping)
        criteria = f"((Shipping_City:equals:{miasto})and(Shipping_Street:contains:{ulica_clean}))"
        records = await self._search_accounts(criteria)
        for record in records:
            match = self._build_zoho_match(record, "adres filii")
            if match.zoho_id not in [m.zoho_id for m in matches]:
                matches.append(match)
        
        self.logger.info("Zoho: Znaleziono %d rekordów po adresie", len(matches))
        return matches
    
    async def lookup_by_domain(self, domain: str) -> List[ZohoMatch]:
        """
        Szuka rekordów po domenie WWW.
        """
        if not domain:
            return []
        
        # Normalizuj domenę
        domain_clean = domain.lower().strip()
        domain_clean = domain_clean.replace("https://", "").replace("http://", "")
        domain_clean = domain_clean.replace("www.", "")
        domain_clean = domain_clean.rstrip("/")
        
        self.logger.info("Zoho lookup by domain: %s", domain_clean)
        
        criteria = f"(Domena_z_www:equals:{domain_clean})"
        records = await self._search_accounts(criteria)
        
        matches = []
        for record in records:
            match = self._build_zoho_match(record, "domena www")
            matches.append(match)
        
        # Jeśli nie znaleziono po domenie, spróbuj po Website
        if not matches:
            criteria = f"(Website:contains:{domain_clean})"
            records = await self._search_accounts(criteria)
            for record in records:
                match = self._build_zoho_match(record, "website")
                matches.append(match)
        
        self.logger.info("Zoho: Znaleziono %d rekordów po domenie", len(matches))
        return matches
    
    async def lookup_by_phone(self, phone: str) -> List[ZohoMatch]:
        """
        Szuka rekordów po numerze telefonu.
        Sprawdza wszystkie pola telefonów: Phone, Phone_2, Phone_3, Mobile_phone_1/2/3
        
        TANIE WYSZUKIWANIE NIP - jeśli mamy telefon ze strony, możemy znaleźć rekord w Zoho!
        """
        if not phone:
            return []
        
        # Normalizuj telefon - zostaw tylko cyfry
        import re
        phone_clean = re.sub(r'\D', '', phone)
        if len(phone_clean) < 7:  # Za krótki numer
            return []
        
        # Usuń prefix kraju (48, +48)
        if phone_clean.startswith("48") and len(phone_clean) > 9:
            phone_clean = phone_clean[2:]
        
        self.logger.info("Zoho lookup by phone: %s", phone_clean)
        
        # Szukaj we wszystkich polach telefonów
        phone_fields = ["Phone", "Phone_2", "Phone_3", "Mobile_phone_1", "Mobile_phone_2", "Mobile_phone_3"]
        
        matches = []
        for field in phone_fields:
            criteria = f"({field}:contains:{phone_clean})"
            records = await self._search_accounts(criteria)
            
            for record in records:
                match = self._build_zoho_match(record, f"telefon ({field})")
                if match.zoho_id not in [m.zoho_id for m in matches]:
                    matches.append(match)
            
            if matches:  # Early exit jeśli znaleziono
                break
        
        self.logger.info("Zoho: Znaleziono %d rekordów po telefonie", len(matches))
        return matches
    
    async def lookup_by_email_domain(self, email_domain: str) -> List[ZohoMatch]:
        """
        Szuka rekordów po domenie z emaila.
        Sprawdza pola: Domena_z_email1, Domena_z_email2, Domena_z_email3
        
        TANIE WYSZUKIWANIE NIP - jeśli mamy email ze strony, możemy znaleźć rekord w Zoho!
        """
        if not email_domain:
            return []
        
        # Normalizuj domenę
        domain_clean = email_domain.lower().strip()
        
        # Pomijaj popularne domeny (gmail, wp, onet itd.)
        public_domains = [
            "gmail.com", "wp.pl", "onet.pl", "interia.pl", "o2.pl", "poczta.fm",
            "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "me.com",
            "tlen.pl", "gazeta.pl", "op.pl", "buziaczek.pl", "go2.pl",
        ]
        if domain_clean in public_domains:
            self.logger.debug("Zoho: Pomijam publiczną domenę %s", domain_clean)
            return []
        
        self.logger.info("Zoho lookup by email domain: %s", domain_clean)
        
        # Szukaj w polach domen z emaili
        criteria = f"((Domena_z_email1:equals:{domain_clean})or(Domena_z_email2:equals:{domain_clean})or(Domena_z_email3:equals:{domain_clean}))"
        records = await self._search_accounts(criteria)
        
        matches = []
        for record in records:
            match = self._build_zoho_match(record, "domena email")
            matches.append(match)
        
        self.logger.info("Zoho: Znaleziono %d rekordów po domenie email", len(matches))
        return matches
    
    async def find_nip_by_website_data(
        self,
        domain: Optional[str] = None,
        phones: Optional[List[str]] = None,
        email_domains: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        TANI SPOSÓB na znalezienie NIP - szuka w Zoho po danych ze strony WWW.
        
        Priorytet:
        1. Domena WWW (najsilniejsze)
        2. Domena z emaila (silne - unikalna dla firmy)
        3. Telefon (słabsze - może być wiele firm z tym samym)
        
        Returns:
            NIP jeśli znaleziono rekord w Zoho, None jeśli nie
        """
        if not self._has_credentials():
            self.logger.debug("Zoho: Brak credentials - nie można szukać NIP")
            return None
        
        # 1. Szukaj po domenie WWW
        if domain:
            matches = await self.lookup_by_domain(domain)
            if matches and matches[0].nip:
                self.logger.info("Zoho FOUND NIP by domain: %s -> %s", domain, matches[0].nip)
                return matches[0].nip
        
        # 2. Szukaj po domenach z emaili
        if email_domains:
            for email_domain in email_domains:
                matches = await self.lookup_by_email_domain(email_domain)
                if matches and matches[0].nip:
                    self.logger.info("Zoho FOUND NIP by email domain: %s -> %s", email_domain, matches[0].nip)
                    return matches[0].nip
        
        # 3. Szukaj po telefonach
        if phones:
            for phone in phones:
                matches = await self.lookup_by_phone(phone)
                if matches and matches[0].nip:
                    self.logger.info("Zoho FOUND NIP by phone: %s -> %s", phone, matches[0].nip)
                    return matches[0].nip
        
        return None
    
    async def lookup_placowka(
        self,
        nip: Optional[str] = None,
        adres: Optional[Adres] = None,
        domain: Optional[str] = None,
    ) -> Optional[ZohoMatch]:
        """
        Szuka dopasowania dla placówki.
        Priorytet: NIP > Adres > Domena
        
        Zwraca najlepsze dopasowanie lub None.
        """
        if not self._has_credentials():
            self.logger.debug("Zoho: Brak credentials - pomijam lookup")
            return None
        
        # 1. Szukaj po NIP (najsilniejsze)
        if nip:
            matches = await self.lookup_by_nip(nip)
            if matches:
                # Jeśli jest adres, spróbuj znaleźć konkretną lokalizację
                if adres and adres.ulica and adres.miasto:
                    for match in matches:
                        # TODO: porównaj adres z rekordem
                        pass
                # Zwróć pierwszy (siedziba ma priorytet)
                siedziby = [m for m in matches if m.is_siedziba and not m.is_filia]
                if siedziby:
                    return siedziby[0]
                return matches[0]
        
        # 2. Szukaj po adresie
        if adres and adres.ulica and adres.miasto:
            matches = await self.lookup_by_address(adres.ulica, adres.miasto)
            if matches:
                return matches[0]
        
        # 3. Szukaj po domenie
        if domain:
            matches = await self.lookup_by_domain(domain)
            if matches:
                return matches[0]
        
        return None
    
    async def lookup_all_locations(
        self,
        nip: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> List[ZohoMatch]:
        """
        Zwraca wszystkie lokalizacje firmy w Zoho (po NIP lub domenie).
        Przydatne do porównania z znalezionymi placówkami.
        """
        if not self._has_credentials():
            return []
        
        all_matches = []
        
        if nip:
            matches = await self.lookup_by_nip(nip)
            all_matches.extend(matches)
        
        if domain and not all_matches:
            matches = await self.lookup_by_domain(domain)
            all_matches.extend(matches)
        
        return all_matches
