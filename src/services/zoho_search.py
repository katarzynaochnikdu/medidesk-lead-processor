"""
Serwis Zoho CRM - wyszukiwanie duplikatów.
Przeszukuje moduły Contacts, Accounts, Leads.
"""

import logging
import time
import urllib.parse
from typing import Any, Optional

import httpx

from ..config import Settings, get_settings
from ..models.lead_output import DuplicateMatch, DuplicatesResult
from ..utils.validators import extract_email_domain, is_public_email_domain, normalize_phone

logger = logging.getLogger(__name__)


class ZohoSearchService:
    """
    Serwis do wyszukiwania duplikatów w Zoho CRM.
    Obsługuje autoryzację OAuth, cache tokena i różne strategie wyszukiwania.
    """
    
    # Timeouty
    REQUEST_TIMEOUT = 30
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None
        # Cache tokenu - na poziomie instancji
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
    
    @property
    def api_base(self) -> str:
        return f"{self.settings.zoho_api_base}/crm/v2"
    
    @property
    def oauth_base(self) -> str:
        return self.settings.zoho_oauth_base
    
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
    
    def _is_placeholder(self, value: str) -> bool:
        """Sprawdza czy wartość to placeholder."""
        if not value:
            return True
        placeholders = ["your-", "xxx", "placeholder", "changeme"]
        return any(p in value.lower() for p in placeholders)
    
    async def _refresh_access_token(self) -> Optional[str]:
        """Odświeża access token używając refresh tokena."""
        
        # Sprawdź czy mamy wszystkie wymagane dane
        if not self.settings.zoho_refresh_token:
            logger.warning("Zoho: Brak refresh tokena - deduplikacja wyłączona")
            return None
        
        if self._is_placeholder(self.settings.zoho_client_id):
            logger.warning("Zoho: Client ID to placeholder - deduplikacja wyłączona")
            return None
        
        if self._is_placeholder(self.settings.zoho_client_secret):
            logger.warning("Zoho: Client Secret to placeholder - deduplikacja wyłączona")
            return None
        
        if self._is_placeholder(self.settings.zoho_refresh_token):
            logger.warning("Zoho: Refresh Token to placeholder - deduplikacja wyłączona")
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
            
            logger.debug("Zoho: Odświeżam access token...")
            response = await client.post(url, data=data)
            result = response.json()
            
            if "access_token" in result:
                self._access_token = result["access_token"]
                expires_in = int(result.get("expires_in", 3600))
                self._token_expires_at = time.time() + expires_in - 60  # 60s buffer
                logger.info("Zoho: Token odświeżony, wygasa za %ds", expires_in)
                return self._access_token
            else:
                error = result.get("error", "unknown")
                error_desc = result.get("error_description", "")
                if error == "invalid_client":
                    logger.error("Zoho: Nieprawidłowe client_id lub client_secret")
                elif error == "invalid_code":
                    logger.error("Zoho: Refresh token wygasł lub jest nieprawidłowy")
                else:
                    logger.error("Zoho: Błąd odświeżania tokena: %s - %s", error, error_desc)
                return None
                
        except httpx.TimeoutException:
            logger.error("Zoho: Timeout podczas odświeżania tokena")
            return None
        except Exception as e:
            logger.error("Zoho: Wyjątek podczas odświeżania tokena: %s", e)
            return None
    
    async def _get_access_token(self) -> Optional[str]:
        """Zwraca ważny access token (odświeża jeśli trzeba)."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        
        return await self._refresh_access_token()
    
    async def _api_request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> Optional[dict]:
        """Wykonuje autoryzowane żądanie do Zoho API."""
        token = await self._get_access_token()
        if not token:
            return None
        
        client = await self._get_client()
        url = f"{self.api_base}/{path.lstrip('/')}"
        
        headers = {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json",
        }
        
        try:
            if method.upper() == "GET":
                response = await client.get(url, params=params, headers=headers)
            elif method.upper() == "POST":
                response = await client.post(url, params=params, headers=headers, json=json_body)
            else:
                response = await client.request(method, url, params=params, headers=headers, json=json_body)
            
            if response.status_code == 204:
                return {"data": []}
            
            return response.json()
            
        except Exception as e:
            logger.error("Zoho API error: %s", e)
            return None
    
    async def _search_module(
        self,
        module: str,
        criteria: str,
        fields: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Wyszukuje rekordy w module Zoho.
        
        Args:
            module: Nazwa modułu (Contacts, Accounts, Leads)
            criteria: Kryteria wyszukiwania w formacie Zoho
            fields: Lista pól do pobrania
        
        Returns:
            Lista znalezionych rekordów
        """
        params = {"criteria": criteria}
        if fields:
            params["fields"] = ",".join(fields)
        
        encoded_criteria = urllib.parse.quote(criteria)
        path = f"{module}/search?criteria={encoded_criteria}"
        if fields:
            path += f"&fields={','.join(fields)}"
        
        result = await self._api_request("GET", path)
        
        if not result:
            return []
        
        return result.get("data", []) or []
    
    def _calculate_match_score(
        self,
        record: dict,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        company: Optional[str] = None,
    ) -> tuple[float, str]:
        """
        Oblicza score dopasowania rekordu.
        
        Returns:
            Tuple (score 0-1, powód dopasowania)
        """
        score = 0.0
        reasons = []
        
        # Email - najsilniejszy sygnał
        record_emails = [
            record.get("Email", "").lower(),
            record.get("Secondary_Email", "").lower(),
            record.get("Email_3", "").lower(),
        ]
        if email and email.lower() in record_emails:
            score += 0.4
            reasons.append("email")
        
        # Telefon
        record_phones = [
            normalize_phone(record.get("Phone")),
            normalize_phone(record.get("Mobile")),
            normalize_phone(record.get("Home_Phone")),
            normalize_phone(record.get("Telefon_komorkowy")),
        ]
        normalized_phone = normalize_phone(phone)
        if normalized_phone and normalized_phone in record_phones:
            score += 0.3
            reasons.append("telefon")
        
        # Imię i nazwisko
        record_first = (record.get("First_Name") or "").lower()
        record_last = (record.get("Last_Name") or "").lower()
        
        if first_name and first_name.lower() == record_first:
            score += 0.1
            reasons.append("imię")
        
        if last_name and last_name.lower() == record_last:
            score += 0.15
            reasons.append("nazwisko")
        
        # Firma
        record_company = (record.get("Account_Name") or record.get("Company") or "").lower()
        if company and company.lower() in record_company:
            score += 0.1
            reasons.append("firma")
        
        return min(score, 1.0), " + ".join(reasons) if reasons else "podobny rekord"
    
    async def search_contact_duplicates(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> list[DuplicateMatch]:
        """
        Wyszukuje potencjalne duplikaty w Contacts.
        """
        duplicates = []
        
        # Strategia 1: Szukaj po emailu
        if email:
            criteria = f"((Email:equals:{email})or(Secondary_Email:equals:{email}))"
            records = await self._search_module(
                "Contacts",
                criteria,
                fields=["id", "First_Name", "Last_Name", "Email", "Phone", "Mobile", "Account_Name"]
            )
            
            for record in records:
                score, reason = self._calculate_match_score(
                    record, email=email, phone=phone, 
                    first_name=first_name, last_name=last_name
                )
                duplicates.append(DuplicateMatch(
                    id=record.get("id", ""),
                    name=f"{record.get('First_Name', '')} {record.get('Last_Name', '')}".strip(),
                    score=score,
                    match_reason=reason,
                    email=record.get("Email"),
                    phone=record.get("Phone") or record.get("Mobile"),
                    company=record.get("Account_Name"),
                ))
        
        # Strategia 2: Szukaj po telefonie
        if phone:
            normalized = normalize_phone(phone)
            if normalized:
                # Szukaj bez prefixu kraju
                phone_digits = normalized.lstrip("+")
                if phone_digits.startswith("48"):
                    phone_digits = phone_digits[2:]
                
                criteria = f"(Phone:contains:{phone_digits})"
                records = await self._search_module(
                    "Contacts",
                    criteria,
                    fields=["id", "First_Name", "Last_Name", "Email", "Phone", "Mobile", "Account_Name"]
                )
                
                for record in records:
                    # Sprawdź czy nie mamy już tego ID
                    existing_ids = [d.id for d in duplicates]
                    if record.get("id") in existing_ids:
                        continue
                    
                    score, reason = self._calculate_match_score(
                        record, email=email, phone=phone,
                        first_name=first_name, last_name=last_name
                    )
                    duplicates.append(DuplicateMatch(
                        id=record.get("id", ""),
                        name=f"{record.get('First_Name', '')} {record.get('Last_Name', '')}".strip(),
                        score=score,
                        match_reason=reason,
                        email=record.get("Email"),
                        phone=record.get("Phone") or record.get("Mobile"),
                        company=record.get("Account_Name"),
                    ))
        
        # Strategia 3: Imię + Nazwisko (jeśli oba są dostępne)
        if first_name and last_name and not duplicates:
            criteria = f"((First_Name:equals:{first_name})and(Last_Name:equals:{last_name}))"
            records = await self._search_module(
                "Contacts",
                criteria,
                fields=["id", "First_Name", "Last_Name", "Email", "Phone", "Mobile", "Account_Name"]
            )
            
            for record in records[:5]:  # Limit do 5 wyników dla słabszego dopasowania
                existing_ids = [d.id for d in duplicates]
                if record.get("id") in existing_ids:
                    continue
                
                score, reason = self._calculate_match_score(
                    record, email=email, phone=phone,
                    first_name=first_name, last_name=last_name
                )
                duplicates.append(DuplicateMatch(
                    id=record.get("id", ""),
                    name=f"{record.get('First_Name', '')} {record.get('Last_Name', '')}".strip(),
                    score=score,
                    match_reason=reason,
                    email=record.get("Email"),
                    phone=record.get("Phone") or record.get("Mobile"),
                    company=record.get("Account_Name"),
                ))
        
        # Sortuj po score malejąco
        duplicates.sort(key=lambda x: x.score, reverse=True)
        
        return duplicates[:10]  # Max 10 wyników
    
    async def search_account_duplicates(
        self,
        company_name: Optional[str] = None,
        nip: Optional[str] = None,
        email_domain: Optional[str] = None,
    ) -> list[DuplicateMatch]:
        """
        Wyszukuje potencjalne duplikaty w Accounts.
        """
        duplicates = []
        
        # Strategia 1: NIP - najsilniejszy identyfikator
        if nip:
            clean_nip = "".join(c for c in nip if c.isdigit())
            if len(clean_nip) == 10:
                criteria = f"(Firma_NIP:equals:{clean_nip})"
                records = await self._search_module(
                    "Accounts",
                    criteria,
                    fields=["id", "Account_Name", "Firma_NIP", "Website", "Domena_z_www"]
                )
                
                for record in records:
                    duplicates.append(DuplicateMatch(
                        id=record.get("id", ""),
                        name=record.get("Account_Name", "Nieznana firma"),
                        score=1.0,  # NIP to 100% dopasowanie
                        match_reason="NIP",
                    ))
        
        # Strategia 2: Domena email
        if email_domain and not is_public_email_domain(email_domain):
            criteria = f"(Domena_z_www:equals:{email_domain})"
            records = await self._search_module(
                "Accounts",
                criteria,
                fields=["id", "Account_Name", "Firma_NIP", "Website", "Domena_z_www"]
            )
            
            for record in records:
                existing_ids = [d.id for d in duplicates]
                if record.get("id") in existing_ids:
                    continue
                
                duplicates.append(DuplicateMatch(
                    id=record.get("id", ""),
                    name=record.get("Account_Name", "Nieznana firma"),
                    score=0.8,
                    match_reason="domena email",
                ))
        
        # Strategia 3: Nazwa firmy (częściowe dopasowanie)
        if company_name and not duplicates:
            # Usuń formę prawną dla lepszego dopasowania
            search_name = company_name.lower()
            for suffix in ["sp. z o.o.", "sp.z o.o.", "s.a.", "sp.k.", "sp.j.", "s.c."]:
                search_name = search_name.replace(suffix, "").strip()
            
            if len(search_name) >= 3:
                criteria = f"(Account_Name:contains:{search_name})"
                records = await self._search_module(
                    "Accounts",
                    criteria,
                    fields=["id", "Account_Name", "Firma_NIP", "Website"]
                )
                
                for record in records[:5]:
                    existing_ids = [d.id for d in duplicates]
                    if record.get("id") in existing_ids:
                        continue
                    
                    duplicates.append(DuplicateMatch(
                        id=record.get("id", ""),
                        name=record.get("Account_Name", "Nieznana firma"),
                        score=0.5,
                        match_reason="podobna nazwa",
                    ))
        
        duplicates.sort(key=lambda x: x.score, reverse=True)
        return duplicates[:10]
    
    async def search_lead_duplicates(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> list[DuplicateMatch]:
        """
        Wyszukuje potencjalne duplikaty w Leads.
        """
        duplicates = []
        
        # Szukaj po emailu
        if email:
            criteria = f"(Email:equals:{email})"
            records = await self._search_module(
                "Leads",
                criteria,
                fields=["id", "First_Name", "Last_Name", "Email", "Phone", "Company"]
            )
            
            for record in records:
                duplicates.append(DuplicateMatch(
                    id=record.get("id", ""),
                    name=f"{record.get('First_Name', '')} {record.get('Last_Name', '')}".strip() or record.get("Company", ""),
                    score=0.9,
                    match_reason="email w Leads",
                    email=record.get("Email"),
                    phone=record.get("Phone"),
                    company=record.get("Company"),
                ))
        
        return duplicates[:5]
    
    async def find_all_duplicates(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        company_name: Optional[str] = None,
        nip: Optional[str] = None,
    ) -> DuplicatesResult:
        """
        Wyszukuje duplikaty we wszystkich modułach.
        
        Returns:
            DuplicatesResult z listami duplikatów dla każdego modułu
        """
        # Wyciągnij domenę z emaila
        email_domain = extract_email_domain(email) if email else None
        
        # Równoległe wyszukiwanie we wszystkich modułach
        import asyncio
        
        contacts_task = self.search_contact_duplicates(
            email=email, phone=phone, 
            first_name=first_name, last_name=last_name
        )
        accounts_task = self.search_account_duplicates(
            company_name=company_name, nip=nip, email_domain=email_domain
        )
        leads_task = self.search_lead_duplicates(
            email=email, phone=phone,
            first_name=first_name, last_name=last_name
        )
        
        contacts, accounts, leads = await asyncio.gather(
            contacts_task, accounts_task, leads_task,
            return_exceptions=True
        )
        
        # Obsłuż ewentualne wyjątki
        if isinstance(contacts, Exception):
            logger.error("Błąd wyszukiwania Contacts: %s", contacts)
            contacts = []
        if isinstance(accounts, Exception):
            logger.error("Błąd wyszukiwania Accounts: %s", accounts)
            accounts = []
        if isinstance(leads, Exception):
            logger.error("Błąd wyszukiwania Leads: %s", leads)
            leads = []
        
        return DuplicatesResult(
            contacts=contacts,
            accounts=accounts,
            leads=leads,
        )


class ZohoSearchServiceMock:
    """
    Mock serwisu Zoho do testów lokalnych.
    """
    
    async def find_all_duplicates(self, **kwargs) -> DuplicatesResult:
        """Zwraca puste wyniki."""
        return DuplicatesResult()
    
    async def search_contact_duplicates(self, **kwargs) -> list[DuplicateMatch]:
        return []
    
    async def search_account_duplicates(self, **kwargs) -> list[DuplicateMatch]:
        return []
    
    async def search_lead_duplicates(self, **kwargs) -> list[DuplicateMatch]:
        return []
    
    async def close(self):
        pass


def get_zoho_search_service(
    settings: Optional[Settings] = None, 
    use_mock: bool = False
) -> ZohoSearchService:
    """
    Factory function - zwraca odpowiedni serwis Zoho.
    """
    if use_mock:
        return ZohoSearchServiceMock()
    
    settings = settings or get_settings()
    
    # Jeśli brak konfiguracji Zoho, użyj mocka
    if not settings.zoho_refresh_token:
        logger.warning("Brak ZOHO_REFRESH_TOKEN - używam mocka Zoho")
        return ZohoSearchServiceMock()
    
    return ZohoSearchService(settings)
