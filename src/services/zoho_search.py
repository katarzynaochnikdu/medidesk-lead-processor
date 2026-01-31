"""
Serwis Zoho CRM - wyszukiwanie duplikatów.
Przeszukuje moduły Contacts, Accounts, Leads.
Algorytm tier-based matching dla decyzji "czy rekord istnieje".
"""

import logging
import time
import urllib.parse
from typing import Any, Optional, List, Dict

import httpx

from ..config import Settings, get_settings
from ..models.lead_output import (
    DuplicateMatch,
    DuplicatesResult,
    MatchSignals,
    ContactExistsResult,
    AccountExistsResult,
    ZohoFieldUpdate,
    NormalizedData,
    ScrapedContactData,
)
from ..utils.validators import extract_email_domain, is_public_email_domain, normalize_phone
from ..utils.phone_formatter import PhoneFormatter

logger = logging.getLogger(__name__)


def normalize_polish_chars(text: str) -> str:
    """Normalizuje polskie znaki diakrytyczne dla lepszego matchingu."""
    if not text:
        return text
    
    replacements = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
        'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z'
    }
    
    for polish, latin in replacements.items():
        text = text.replace(polish, latin)
    
    return text

# Pola telefonów w Zoho CRM
PHONE_FIELDS = [
    "Home_Phone", "Mobile", "Telefon_komorkowy_3",
    "Phone", "Other_Phone", "Telefon_stacjonarny_3"
]

# Pola email w Zoho CRM
EMAIL_FIELDS = ["Email", "Secondary_Email", "Email_3"]

# Pola do pobrania przy wyszukiwaniu kontaktów
CONTACT_SEARCH_FIELDS = [
    "id", "First_Name", "Last_Name",
    "Email", "Secondary_Email", "Email_3",
    "Phone", "Mobile", "Home_Phone", "Other_Phone",
    "Telefon_komorkowy_3", "Telefon_stacjonarny_3",
    "Account_Name"
]

# Pola do pobrania przy wyszukiwaniu firm
ACCOUNT_SEARCH_FIELDS = [
    "id", "Account_Name", "Firma_NIP", "Website", "Domena_z_www",
    "Parent_Account", "Billing_City", "Billing_Street",
    "Phone", "Fax",
]


# ============================================
# Funkcje wykrywania nowych pól
# ============================================


def detect_new_contact_fields(
    existing_record: dict,
    incoming_data: NormalizedData,
) -> list[ZohoFieldUpdate]:
    """
    Porównuje dane z Zoho Contact z nowymi danymi OSOBY.
    Zwraca listę pól do uzupełnienia.

    UWAGA: Dane ze scrapingu (email firmy, telefon z footera) to dane FIRMY (Account),
    nie osoby (Contact)! Nie mieszamy.

    Args:
        existing_record: Rekord Contact z Zoho
        incoming_data: Znormalizowane dane osoby z leada

    Returns:
        Lista ZohoFieldUpdate z polami do aktualizacji
    """
    updates: list[ZohoFieldUpdate] = []
    phone_formatter = PhoneFormatter()

    # Śledź które pola już zostały zaproponowane do aktualizacji
    assigned_fields: set[str] = set()

    # === EMAIL OSOBY (z leada) ===
    zoho_emails = set()
    for field in EMAIL_FIELDS:
        val = existing_record.get(field)
        if val and isinstance(val, str):
            zoho_emails.add(val.lower().strip())

    # Email z leada - to email osoby
    if incoming_data.email:
        email_lower = incoming_data.email.lower().strip()
        if email_lower not in zoho_emails:
            target_field = None
            for field in EMAIL_FIELDS:
                if not existing_record.get(field) and field not in assigned_fields:
                    target_field = field
                    break
            if target_field:
                updates.append(ZohoFieldUpdate(
                    field_name=target_field,
                    new_value=incoming_data.email,
                    reason="nowy email osoby z leada",
                ))
                assigned_fields.add(target_field)

    # === TELEFON OSOBY (z leada) ===
    zoho_phones = set()
    for field in PHONE_FIELDS:
        val = existing_record.get(field)
        if val:
            normalized = phone_formatter.normalize_for_comparison(val)
            if normalized:
                zoho_phones.add(normalized)

    # Telefon z leada - to telefon osoby
    if incoming_data.phone:
        phone_normalized = phone_formatter.normalize_for_comparison(incoming_data.phone)
        if phone_normalized and phone_normalized not in zoho_phones:
            target_field = None
            for field in PHONE_FIELDS:
                if not existing_record.get(field) and field not in assigned_fields:
                    target_field = field
                    break
            if target_field:
                updates.append(ZohoFieldUpdate(
                    field_name=target_field,
                    new_value=incoming_data.phone_formatted or incoming_data.phone,
                    reason="nowy telefon osoby z leada",
                ))
                assigned_fields.add(target_field)

    # Mobile z leada
    if incoming_data.mobile:
        phone_normalized = phone_formatter.normalize_for_comparison(incoming_data.mobile)
        if phone_normalized and phone_normalized not in zoho_phones:
            if not existing_record.get("Mobile") and "Mobile" not in assigned_fields:
                updates.append(ZohoFieldUpdate(
                    field_name="Mobile",
                    new_value=incoming_data.mobile,
                    reason="nowy telefon komórkowy osoby z leada",
                ))
                assigned_fields.add("Mobile")

    return updates


def detect_new_account_fields(
    existing_record: dict,
    incoming_data: NormalizedData,
    scraped_data: Optional[ScrapedContactData] = None,
) -> list[ZohoFieldUpdate]:
    """
    Porównuje dane z Zoho Account z nowymi danymi FIRMY.
    Zwraca listę pól do uzupełnienia.

    scraped_data zawiera dane FIRMY (email kontaktowy, telefon z footera, adres) -
    to są dane firmowe, nie osobowe!

    Args:
        existing_record: Rekord Account z Zoho
        incoming_data: Znormalizowane dane firmy z leada
        scraped_data: Dane FIRMY zebrane podczas crawlowania

    Returns:
        Lista ZohoFieldUpdate z polami do aktualizacji
    """
    updates: list[ZohoFieldUpdate] = []

    # === DOMENA / WEBSITE ===
    zoho_website = existing_record.get("Website") or ""
    zoho_domain = existing_record.get("Domena_z_www") or ""

    if scraped_data and scraped_data.domain:
        domain = scraped_data.domain.lower().replace("www.", "")
        if not zoho_domain and domain not in zoho_website.lower():
            updates.append(ZohoFieldUpdate(
                field_name="Domena_z_www",
                new_value=domain,
                reason="domena ze strony firmy",
            ))
        if not zoho_website:
            updates.append(ZohoFieldUpdate(
                field_name="Website",
                new_value=f"https://{domain}",
                reason="strona www ze scrapingu",
            ))

    # === TELEFON FIRMOWY (ze scrapingu - to telefon FIRMY, np. z footera) ===
    zoho_phone = existing_record.get("Phone") or ""
    if not zoho_phone and scraped_data and scraped_data.phones:
        updates.append(ZohoFieldUpdate(
            field_name="Phone",
            new_value=scraped_data.phones[0],
            reason="telefon firmowy ze strony www",
        ))

    # === EMAIL FIRMOWY (ze scrapingu - kontakt@firma.pl, rejestracja@firma.pl) ===
    # To są emaile FIRMY, nie osoby! Mogą iść do pola np. "Email_firmowy" w Account
    # (jeśli takie pole istnieje w Zoho)

    # === NIP ===
    zoho_nip = existing_record.get("Firma_NIP") or ""
    if not zoho_nip and incoming_data.nip:
        updates.append(ZohoFieldUpdate(
            field_name="Firma_NIP",
            new_value=incoming_data.nip,
            reason="NIP znaleziony przez NIPFinderV3",
        ))

    # === ADRES SIEDZIBY (jeśli brak w Zoho) ===
    zoho_city = existing_record.get("Billing_City") or ""
    if not zoho_city and incoming_data.city:
        updates.append(ZohoFieldUpdate(
            field_name="Billing_City",
            new_value=incoming_data.city,
            reason="miasto firmy z leada",
        ))

    zoho_street = existing_record.get("Billing_Street") or ""
    if not zoho_street and incoming_data.street:
        updates.append(ZohoFieldUpdate(
            field_name="Billing_Street",
            new_value=incoming_data.street,
            reason="ulica firmy z leada",
        ))

    # === ADRES ZE SCRAPINGU (jeśli brak w Zoho i mamy ze strony) ===
    if scraped_data and scraped_data.addresses:
        if not zoho_street:
            # Już dodaliśmy z leada? Sprawdź
            street_already_added = any(u.field_name == "Billing_Street" for u in updates)
            if not street_already_added:
                updates.append(ZohoFieldUpdate(
                    field_name="Billing_Street",
                    new_value=scraped_data.addresses[0],
                    reason="adres firmy ze strony www",
                ))

    return updates


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
    
    def _calculate_signals_and_tier(
        self,
        record: dict,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        target_account_id: Optional[str] = None,
    ) -> tuple[MatchSignals, int, bool, str]:
        """
        Oblicza sygnały dopasowania i tier dla tier-based matching.
        
        Args:
            record: Rekord z Zoho
            email: Email wejściowy
            phone: Telefon wejściowy
            first_name: Imię wejściowe
            last_name: Nazwisko wejściowe
            target_account_id: ID firmy (z NIP)
        
        Returns:
            Tuple (signals, tier, conflict_first_name, reason)
        """
        phone_formatter = PhoneFormatter()
        
        # === Oblicz sygnały ===
        
        # E - Email match
        record_emails = [
            (record.get(field) or "").lower().strip()
            for field in EMAIL_FIELDS
        ]
        record_emails = [e for e in record_emails if e]
        E = bool(email and email.lower().strip() in record_emails)
        
        # P - Phone match (porównaj znormalizowane)
        incoming_phone_clean = phone_formatter.normalize_for_comparison(phone)
        record_phones = [
            phone_formatter.normalize_for_comparison(record.get(field))
            for field in PHONE_FIELDS
        ]
        record_phones = [p for p in record_phones if p]
        P = bool(incoming_phone_clean and incoming_phone_clean in record_phones)
        
        # L - Last name match (case-insensitive, normalizacja polskich znaków)
        record_last = normalize_polish_chars((record.get("Last_Name") or "").lower().strip())
        incoming_last = normalize_polish_chars((last_name or "").lower().strip()) if last_name else ""
        L = bool(incoming_last and incoming_last == record_last)
        
        # F - First name match (case-insensitive, normalizacja polskich znaków)
        record_first = normalize_polish_chars((record.get("First_Name") or "").lower().strip())
        incoming_first = normalize_polish_chars((first_name or "").lower().strip()) if first_name else ""
        
        # F jest True tylko jeśli obie strony mają imię i się zgadzają
        F = bool(incoming_first and record_first and incoming_first == record_first)
        
        # Konflikt imienia: obie strony mają imię, ale się nie zgadzają
        conflict_first_name = bool(
            incoming_first and record_first and incoming_first != record_first
        )
        
        # A - Account match (po ID, nie po nazwie)
        record_account = record.get("Account_Name")
        if isinstance(record_account, dict):
            record_account_id = record_account.get("id")
        else:
            record_account_id = None
        A = bool(target_account_id and record_account_id == target_account_id)
        
        signals = MatchSignals(E=E, P=P, L=L, F=F, A=A)
        
        # === Oblicz tier ===
        # Jeśli konflikt imienia - odpada (tier 0)
        if conflict_first_name:
            tier = 0
            reason = "konflikt imienia"
        # Tier 4: najmocniejsze (3+ sygnały z kontaktem)
        elif (E and P and L) or (P and L and A) or (E and L and A) or (F and L and (E or P)):
            tier = 4
            reason = self._build_reason(signals)
        # Tier 3: bardzo mocne (2 sygnały z kontaktem)
        elif (P and A) or (E and L) or (P and L) or (E and A):
            tier = 3
            reason = self._build_reason(signals)
        # Tier 2: tylko kandydaci (bez email/tel)
        elif (L and A) or (F and L):
            tier = 2
            reason = self._build_reason(signals)
        else:
            tier = 1
            reason = self._build_reason(signals) or "słabe dopasowanie"
        
        return signals, tier, conflict_first_name, reason
    
    def _build_reason(self, signals: MatchSignals) -> str:
        """Buduje string z powodu dopasowania (np. 'E+L+A')."""
        parts = []
        if signals.E:
            parts.append("E")
        if signals.P:
            parts.append("P")
        if signals.L:
            parts.append("L")
        if signals.F:
            parts.append("F")
        if signals.A:
            parts.append("A")
        return "+".join(parts) if parts else ""
    
    def _calculate_record_quality(self, record: dict) -> float:
        """
        Oblicza jakość rekordu (kompletność pól).
        
        Returns:
            Score 0-100
        """
        score = 0.0
        
        # Podstawowe dane
        if record.get("First_Name"):
            score += 10
        if record.get("Last_Name"):
            score += 10
        if record.get("Email"):
            score += 15
        if record.get("Phone") or record.get("Mobile"):
            score += 15
        
        # Powiązanie z firmą
        if record.get("Account_Name"):
            score += 20
        
        # Dodatkowe pola
        if record.get("Secondary_Email"):
            score += 5
        if record.get("Home_Phone"):
            score += 5
        if record.get("Title"):
            score += 5
        
        return min(score, 100.0)
    
    # Legacy - dla kompatybilności wstecznej
    def _calculate_match_score(
        self,
        record: dict,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        company: Optional[str] = None,
    ) -> tuple[float, str]:
        """[Legacy] Oblicza score dopasowania. Używaj _calculate_signals_and_tier."""
        signals, tier, conflict, reason = self._calculate_signals_and_tier(
            record, email, phone, first_name, last_name
        )
        
        # Konwersja tier na score (dla kompatybilności)
        tier_to_score = {4: 0.95, 3: 0.75, 2: 0.5, 1: 0.25, 0: 0.0}
        score = tier_to_score.get(tier, 0.0)
        
        return score, reason
    
    async def search_contact_duplicates(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        target_account_id: Optional[str] = None,
    ) -> list[DuplicateMatch]:
        """
        Wyszukuje potencjalne duplikaty w Contacts z tier-based matching.
        
        Zwraca max 2 poziomy kandydatów (wszystkie z remisu na danym poziomie).
        Stosuje regułę konfliktu imienia (Adam vs Jan = odpada).
        """
        phone_formatter = PhoneFormatter()
        all_records: Dict[str, dict] = {}  # id -> record (deduplikacja)
        
        # === Candidate generation (zbierz szeroko) ===
        
        # Strategia 1: Szukaj po emailu (wszystkie pola email)
        if email:
            for email_field in EMAIL_FIELDS:
                criteria = f"({email_field}:equals:{email})"
                records = await self._search_module("Contacts", criteria, fields=CONTACT_SEARCH_FIELDS)
                for r in records:
                    all_records[r.get("id")] = r
        
        # Strategia 2: Szukaj po telefonie (wszystkie formaty)
        if phone:
            phone_clean = phone_formatter.normalize_for_comparison(phone)
            if phone_clean:
                # Szukaj w każdym polu telefonicznym z różnymi formatami
                formats = phone_formatter.get_all_formats(phone)
                for phone_field in PHONE_FIELDS:
                    for fmt_name, fmt_value in formats.items():
                        if fmt_value:
                            criteria = f"({phone_field}:equals:{fmt_value})"
                            records = await self._search_module("Contacts", criteria, fields=CONTACT_SEARCH_FIELDS)
                            for r in records:
                                all_records[r.get("id")] = r
        
        # Strategia 3: Nazwisko + Account (jeśli mamy account_id)
        if last_name and target_account_id:
            criteria = f"((Last_Name:equals:{last_name})and(Account_Name:equals:{target_account_id}))"
            records = await self._search_module("Contacts", criteria, fields=CONTACT_SEARCH_FIELDS)
            for r in records:
                all_records[r.get("id")] = r
        
        # Strategia 4: Imię + Nazwisko (fallback)
        if first_name and last_name:
            criteria = f"((First_Name:equals:{first_name})and(Last_Name:equals:{last_name}))"
            records = await self._search_module("Contacts", criteria, fields=CONTACT_SEARCH_FIELDS)
            for r in records:
                all_records[r.get("id")] = r
        
        # === Ewaluacja kandydatów (tier-based) ===
        candidates: List[DuplicateMatch] = []
        
        for record_id, record in all_records.items():
            signals, tier, conflict, reason = self._calculate_signals_and_tier(
                record=record,
                email=email,
                phone=phone,
                first_name=first_name,
                last_name=last_name,
                target_account_id=target_account_id,
            )
            
            # Pomiń rekordy z konfliktem imienia
            if conflict:
                logger.debug("Kontakt %s odrzucony: konflikt imienia", record_id)
                continue
            
            # Pomiń rekordy z tier < 2 (za słabe)
            if tier < 2:
                continue
            
            quality = self._calculate_record_quality(record)
            
            # Wyciągnij account_id
            account_name = record.get("Account_Name")
            account_id = None
            company_name = None
            if isinstance(account_name, dict):
                account_id = account_name.get("id")
                company_name = account_name.get("name")
            elif isinstance(account_name, str):
                company_name = account_name
            
            candidates.append(DuplicateMatch(
                id=record_id,
                name=f"{record.get('First_Name', '')} {record.get('Last_Name', '')}".strip(),
                score=tier / 4.0,  # Konwersja tier na score 0-1
                match_reason=reason,
                tier=tier,
                signals=signals,
                conflict_first_name=False,
                record_quality_score=quality,
                email=record.get("Email"),
                phone=record.get("Phone") or record.get("Mobile"),
                company=company_name,
                account_id=account_id,
            ))
        
        # === Sortowanie i zwracanie max 2 poziomów ===
        # Sortuj: tier DESC, quality DESC
        candidates.sort(key=lambda x: (x.tier, x.record_quality_score), reverse=True)
        
        if not candidates:
            return []
        
        # Znajdź top1 tier
        top1_tier = candidates[0].tier
        top1_candidates = [c for c in candidates if c.tier == top1_tier]
        
        # Jeśli top1 to 1 rekord, dodaj top2
        if len(top1_candidates) == 1:
            remaining = [c for c in candidates if c.tier < top1_tier]
            if remaining:
                top2_tier = remaining[0].tier
                top2_candidates = [c for c in remaining if c.tier == top2_tier]
                return top1_candidates + top2_candidates
        
        return top1_candidates
    
    async def search_account_duplicates(
        self,
        company_name: Optional[str] = None,
        nip: Optional[str] = None,
        email_domain: Optional[str] = None,
    ) -> list[DuplicateMatch]:
        """
        Wyszukuje potencjalne duplikaty w Accounts.
        NIP jest kluczem grupy - siedziba (parent) vs placówki (children).
        """
        duplicates = []
        
        # Strategia 1: NIP - najsilniejszy identyfikator (klucz grupy)
        if nip:
            clean_nip = "".join(c for c in nip if c.isdigit())
            if len(clean_nip) == 10:
                criteria = f"(Firma_NIP:equals:{clean_nip})"
                records = await self._search_module(
                    "Accounts",
                    criteria,
                    fields=ACCOUNT_SEARCH_FIELDS
                )
                
                for record in records:
                    # Sprawdź czy to parent (siedziba) czy child (placówka)
                    parent_account = record.get("Parent_Account")
                    is_parent = parent_account is None
                    
                    # Jakość rekordu - parent ma wyższy priorytet
                    quality = 100.0 if is_parent else 50.0
                    if record.get("Billing_City"):
                        quality += 10
                    if record.get("Website"):
                        quality += 5
                    
                    duplicates.append(DuplicateMatch(
                        id=record.get("id", ""),
                        name=record.get("Account_Name", "Nieznana firma"),
                        score=1.0,  # NIP to 100% dopasowanie
                        match_reason="NIP" + (" (siedziba)" if is_parent else " (placówka)"),
                        tier=4,  # NIP = Tier 4
                        record_quality_score=quality,
                    ))
        
        # Strategia 2: Domena email (tylko jeśli nie publiczna)
        if email_domain and not is_public_email_domain(email_domain):
            criteria = f"(Domena_z_www:equals:{email_domain})"
            records = await self._search_module(
                "Accounts",
                criteria,
                fields=ACCOUNT_SEARCH_FIELDS
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
                    tier=3,
                    record_quality_score=70.0,
                ))
        
        # Strategia 3: Nazwa firmy (częściowe dopasowanie) - tylko jeśli brak NIP/domeny
        if company_name and not duplicates:
            # Usuń formę prawną dla lepszego dopasowania
            search_name = company_name.lower()
            for suffix in ["sp. z o.o.", "sp.z o.o.", "spółka z o.o.", "s.a.", "sp.k.", "sp.j.", "s.c."]:
                search_name = search_name.replace(suffix, "").strip()
            
            if len(search_name) >= 3:
                criteria = f"(Account_Name:contains:{search_name})"
                records = await self._search_module(
                    "Accounts",
                    criteria,
                    fields=ACCOUNT_SEARCH_FIELDS
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
                        tier=2,  # Tylko kandydat
                        record_quality_score=30.0,
                    ))
        
        # Sortuj: tier DESC, quality DESC
        duplicates.sort(key=lambda x: (x.tier, x.record_quality_score), reverse=True)
        return duplicates[:10]
    
    def _select_parent_account(self, accounts: list[DuplicateMatch]) -> Optional[str]:
        """
        Wybiera siedzibę (parent) spośród firm z tym samym NIP.
        Siedziba = rekord bez Parent_Account, z najwyższą jakością.
        """
        # Filtruj tylko te z NIP (tier 4)
        nip_accounts = [a for a in accounts if a.tier == 4 and "siedziba" in a.match_reason]
        
        if nip_accounts:
            # Zwróć pierwszy (najwyższa jakość po sortowaniu)
            return nip_accounts[0].id
        
        # Fallback - pierwszy z listy
        return accounts[0].id if accounts else None
    
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
        Wyszukuje duplikaty we wszystkich modułach z tier-based matching.
        
        Returns:
            DuplicatesResult z ContactExistsResult i AccountExistsResult
        """
        import asyncio
        
        # Wyciągnij domenę z emaila
        email_domain = extract_email_domain(email) if email else None
        
        # === KROK 1: Najpierw szukaj firmy (potrzebujemy account_id dla kontaktów) ===
        accounts = await self.search_account_duplicates(
            company_name=company_name, nip=nip, email_domain=email_domain
        )
        
        if isinstance(accounts, Exception):
            logger.error("Błąd wyszukiwania Accounts: %s", accounts)
            accounts = []
        
        # Wybierz parent account (siedzibę)
        parent_account_id = self._select_parent_account(accounts) if accounts else None
        
        # Buduj AccountExistsResult
        account_exists = bool(accounts and accounts[0].tier >= 3)
        account_result = AccountExistsResult(
            exists=account_exists,
            parent_id=parent_account_id,
            child_id=None,  # TODO: identyfikacja konkretnej placówki po adresie
            candidates=accounts,
        )
        
        # === KROK 2: Szukaj kontaktów (z account_id jeśli mamy) ===
        contacts_task = self.search_contact_duplicates(
            email=email, phone=phone, 
            first_name=first_name, last_name=last_name,
            target_account_id=parent_account_id,
        )
        leads_task = self.search_lead_duplicates(
            email=email, phone=phone,
            first_name=first_name, last_name=last_name
        )
        
        contacts, leads = await asyncio.gather(
            contacts_task, leads_task,
            return_exceptions=True
        )
        
        # Obsłuż wyjątki
        if isinstance(contacts, Exception):
            logger.error("Błąd wyszukiwania Contacts: %s", contacts)
            contacts = []
        if isinstance(leads, Exception):
            logger.error("Błąd wyszukiwania Leads: %s", leads)
            leads = []
        
        # Buduj ContactExistsResult
        contact_exists = bool(contacts and contacts[0].tier >= 3)
        primary_contact_id = None
        needs_review = False
        
        if contacts:
            top_tier = contacts[0].tier
            top_tier_count = sum(1 for c in contacts if c.tier == top_tier)
            
            if top_tier >= 3:
                if top_tier_count == 1:
                    # Jednoznaczne dopasowanie
                    primary_contact_id = contacts[0].id
                else:
                    # Remis na top1 - wymaga przeglądu
                    needs_review = True
        
        contact_result = ContactExistsResult(
            exists=contact_exists,
            primary_id=primary_contact_id,
            candidates=contacts,
            needs_review=needs_review,
        )
        
        # === Buduj odpowiedź ===
        return DuplicatesResult(
            # Nowy format
            contact=contact_result,
            account=account_result,
            # Legacy (dla kompatybilności)
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
        return DuplicatesResult(
            contact=ContactExistsResult(),
            account=AccountExistsResult(),
        )
    
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
