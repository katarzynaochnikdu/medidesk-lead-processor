"""
NIP Validator - walidacja NIP przez:
1. Checksum (suma kontrolna)
2. Biała Lista VAT (API)
3. GUS cross-reference (czy nazwa pasuje)
"""

import logging
from typing import Optional

import httpx
from fuzzywuzzy import fuzz

from .models import ValidationResult

logger = logging.getLogger(__name__)


class NIPValidator:
    """
    Validator NIP - sprawdza poprawność i aktywność NIP.
    
    3-poziomowa walidacja:
    1. Checksum (matematyczna suma kontrolna)
    2. Biała Lista VAT (czy aktywny podatnik)
    3. GUS nazwa (czy nazwa pasuje do firmy)
    """
    
    # Wagi dla sumy kontrolnej NIP
    NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    
    def __init__(self, settings: Optional[object] = None):
        """
        Args:
            settings: NIPFinderSettings (opcjonalne)
        """
        self.settings = settings
        self._http_client: Optional[httpx.AsyncClient] = None
        self._gus_client = None
    
    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy init HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    @property
    def gus_client(self):
        """Lazy init GUS client (z głównego projektu)."""
        if self._gus_client is None:
            from src.services.gus_client import get_gus_client
            self._gus_client = get_gus_client(self.settings)
        return self._gus_client
    
    async def validate(
        self,
        nip: str,
        company_name: Optional[str] = None,
    ) -> ValidationResult:
        """
        Pełna walidacja NIP.
        
        Args:
            nip: NIP do walidacji (10 cyfr)
            company_name: Nazwa firmy do cross-reference (opcjonalne)
        
        Returns:
            ValidationResult z wynikami walidacji
        """
        logger.info("[OK] Walidacja NIP: %s (firma: %s)", nip, company_name or "brak")
        
        errors = []
        
        # === 1. CHECKSUM ===
        valid_checksum = self._validate_checksum(nip)
        if not valid_checksum:
            errors.append("Niepoprawna suma kontrolna NIP")
            logger.warning("[ERROR] Checksum failed")
        else:
            logger.info("[OK] Checksum OK")
        
        # === 2. BIAŁA LISTA VAT ===
        vat_active = None
        if valid_checksum:  # Nie sprawdzaj VAT jeśli checksum błędny
            vat_active = await self._check_vat_whitelist(nip)
            if vat_active is False:
                errors.append("NIP nieaktywny w Białej Liście VAT")
                logger.warning("[ERROR] VAT nieaktywny")
            elif vat_active is True:
                logger.info("[OK] VAT aktywny")
            else:
                logger.warning("[WARN] Nie udało się sprawdzić VAT")
        
        # === 3. GUS CROSS-REFERENCE ===
        gus_found = False
        gus_name = None
        name_match_score = None
        
        if valid_checksum and company_name:
            try:
                gus_data = await self.gus_client.lookup_nip(nip)
                gus_found = gus_data.found
                
                if gus_found and gus_data.full_name:
                    gus_name = gus_data.full_name
                    name_match_score = self._fuzzy_match_names(
                        company_name,
                        gus_data.full_name
                    )
                    
                    threshold = self.settings.fuzzy_match_threshold if self.settings else 0.8
                    if name_match_score < threshold:
                        errors.append(
                            f"Nazwa z GUS nie pasuje (match: {name_match_score:.2f})"
                        )
                        logger.warning(
                            "[WARN] Nazwa nie pasuje: '%s' vs '%s' (score: %.2f)",
                            company_name, gus_name, name_match_score
                        )
                    else:
                        logger.info("[OK] Nazwa pasuje (score: %.2f)", name_match_score)
                else:
                    errors.append("NIP nie znaleziony w GUS")
                    logger.warning("[ERROR] NIP nie w GUS")
                    
            except Exception as e:
                logger.warning("[WARN] Błąd sprawdzania GUS: %s", e)
                errors.append(f"Błąd GUS: {str(e)[:50]}")
        
        # === WYNIK ===
        validated = (
            valid_checksum
            and (vat_active is True or vat_active is None)  # OK jeśli aktywny lub nie sprawdzono
            and (name_match_score is None or name_match_score >= (self.settings.fuzzy_match_threshold if self.settings else 0.8))
        )
        
        result = ValidationResult(
            valid_checksum=valid_checksum,
            vat_active=vat_active,
            gus_found=gus_found,
            gus_name=gus_name,
            name_match_score=name_match_score,
            validated=validated,
            validation_errors=errors,
        )
        
        logger.info("[OK] Walidacja zakończona: validated=%s, errors=%d", validated, len(errors))
        
        return result
    
    def _validate_checksum(self, nip: str) -> bool:
        """
        Walidacja sumy kontrolnej NIP.
        
        Algorytm:
        1. Pomnóż każdą z pierwszych 9 cyfr przez wagę
        2. Zsumuj wyniki
        3. Podziel przez 11, weź resztę
        4. Reszta musi być równa 10. cyfrze
        
        Args:
            nip: NIP (10 cyfr)
        
        Returns:
            True jeśli checksum poprawny
        """
        if not nip or len(nip) != 10 or not nip.isdigit():
            return False
        
        try:
            digits = [int(d) for d in nip]
            
            # Oblicz sumę kontrolną
            checksum = sum(d * w for d, w in zip(digits[:9], self.NIP_WEIGHTS)) % 11
            
            # Suma kontrolna nie może być 10
            if checksum == 10:
                return False
            
            # Porównaj z ostatnią cyfrą
            return checksum == digits[9]
            
        except (ValueError, IndexError):
            return False
    
    async def _check_vat_whitelist(self, nip: str) -> Optional[bool]:
        """
        Sprawdza czy NIP jest aktywny w Białej Liście VAT.
        
        API: https://wl-api.mf.gov.pl/
        
        Args:
            nip: NIP (10 cyfr)
        
        Returns:
            True - aktywny, False - nieaktywny, None - błąd sprawdzania
        """
        if not nip or len(nip) != 10:
            return None
        
        try:
            url_template = self.settings.vat_whitelist_api_url if self.settings else \
                "https://wl-api.mf.gov.pl/api/search/nip/{nip}"
            
            url = url_template.format(nip=nip)
            
            # Parametry API: date - data sprawdzenia (format YYYY-MM-DD)
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            
            params = {"date": today}
            
            logger.debug("Sprawdzam Białą Listę VAT: %s", url)
            
            response = await self.http_client.get(url, params=params)
            
            if response.status_code == 404:
                # NIP nie znaleziony w bazie
                logger.info("NIP nie w Białej Liście VAT (404)")
                return False
            
            if response.status_code != 200:
                logger.warning("Biała Lista VAT HTTP %d", response.status_code)
                return None
            
            data = response.json()
            
            # Struktura odpowiedzi: {"result": {"subject": {...}, "entries": [...]}}
            result = data.get("result")
            if not result:
                return False
            
            subject = result.get("subject")
            if not subject:
                return False
            
            # Sprawdź statusVat
            status_vat = subject.get("statusVat")
            
            # statusVat: "Czynny" - aktywny, "Nieczynny" - nieaktywny
            is_active = status_vat == "Czynny"
            
            logger.info("Biała Lista VAT: status=%s", status_vat)
            
            return is_active
            
        except httpx.HTTPStatusError as e:
            logger.warning("Biała Lista VAT HTTP error: %s", e)
            return None
        except Exception as e:
            logger.warning("Błąd sprawdzania Białej Listy VAT: %s", e)
            return None
    
    def _fuzzy_match_names(self, name1: str, name2: str) -> float:
        """
        Fuzzy matching nazw firm.
        
        Używa fuzzywuzzy (Levenshtein distance).
        
        Args:
            name1: Nazwa 1
            name2: Nazwa 2
        
        Returns:
            Score 0-1 (0 = brak match, 1 = identyczne)
        """
        if not name1 or not name2:
            return 0.0
        
        # Normalizuj
        name1 = name1.lower().strip()
        name2 = name2.lower().strip()
        
        # Usuń formy prawne (zakłócają matching)
        legal_forms = [
            "spółka z ograniczoną odpowiedzialnością",
            "sp. z o.o.", "sp.z o.o.", "sp z oo", "sp zoo",
            "spółka akcyjna", "s.a.", "sa",
            "spółka komandytowa", "sp.k.", "spk",
            "spółka jawna", "sp.j.", "spj",
        ]
        
        for form in legal_forms:
            name1 = name1.replace(form, "")
            name2 = name2.replace(form, "")
        
        name1 = " ".join(name1.split())  # Usuń multiple spaces
        name2 = " ".join(name2.split())
        
        # Partial ratio - najlepszy dla różnych długości
        score = fuzz.partial_ratio(name1, name2)
        
        # Konwersja 0-100 -> 0-1
        return score / 100.0
    
    async def close(self):
        """Zamknij połączenia."""
        if self._http_client:
            await self._http_client.aclose()
        if self._gus_client:
            await self._gus_client.close()
