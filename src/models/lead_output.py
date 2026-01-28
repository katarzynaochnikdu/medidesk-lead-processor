"""
Modele wyjściowe - ustrukturyzowane dane zwracane do Zoho CRM.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class NormalizedData(BaseModel):
    """Znormalizowane dane osobowe i firmowe."""
    
    # Dane osobowe
    first_name: Optional[str] = Field(None, description="Imię - poprawiona wielkość liter")
    last_name: Optional[str] = Field(None, description="Nazwisko - poprawiona wielkość liter")
    title: Optional[str] = Field(None, description="Tytuł naukowy/zawodowy (dr, prof., lek., mgr)")
    gender: Optional[Literal["male", "female", "unknown"]] = Field(
        None, description="Płeć wykryta z imienia"
    )
    salutation: Optional[str] = Field(None, description="Zwrot grzecznościowy (Pan/Pani)")
    role: Optional[str] = Field(None, description="Stanowisko/funkcja")
    
    # Dane firmowe
    company_name: Optional[str] = Field(None, description="Nazwa firmy bez formy prawnej")
    company_legal_form: Optional[str] = Field(
        None, description="Forma prawna (sp. z o.o., S.A., etc.)"
    )
    company_full_name: Optional[str] = Field(None, description="Pełna nazwa z formą prawną")
    company_keyword: Optional[str] = Field(
        None, description="1-2 słowa kluczowe do wyszukiwania firmy w CRM"
    )
    website: Optional[str] = Field(None, description="Domena firmowa")
    
    # Kontakt - znormalizowany format
    email: Optional[str] = Field(None, description="Email - lowercase")
    phone: Optional[str] = Field(None, description="Telefon służbowy w formacie +48XXXXXXXXX")
    mobile: Optional[str] = Field(None, description="Telefon komórkowy w formacie +48XXXXXXXXX")
    phone_formatted: Optional[str] = Field(
        None, description="Telefon sformatowany (+48 XXX XXX XXX)"
    )
    
    # Identyfikatory
    nip: Optional[str] = Field(None, description="NIP - tylko cyfry (10 znaków)")
    nip_formatted: Optional[str] = Field(None, description="NIP sformatowany (XXX-XXX-XX-XX)")
    nip_valid: Optional[bool] = Field(None, description="Czy NIP przeszedł walidację checksum")
    
    # Adres
    street: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None


class GUSData(BaseModel):
    """Dane pobrane z rejestru GUS/REGON."""
    
    found: bool = Field(False, description="Czy znaleziono firmę w GUS")
    
    # Podstawowe dane
    regon: Optional[str] = Field(None, description="Numer REGON")
    full_name: Optional[str] = Field(None, description="Pełna nazwa z rejestru")
    short_name: Optional[str] = Field(None, description="Nazwa skrócona")
    
    # Adres z rejestru (format GUS)
    street: Optional[str] = None
    building_number: Optional[str] = None
    apartment_number: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    voivodeship: Optional[str] = Field(None, description="Województwo")
    county: Optional[str] = Field(None, description="Powiat")
    commune: Optional[str] = Field(None, description="Gmina")
    
    # Status
    status: Optional[Literal["active", "inactive", "unknown"]] = None
    termination_date: Optional[str] = Field(None, description="Data zakończenia działalności")
    
    # Dodatkowe
    legal_form: Optional[str] = Field(None, description="Forma prawna wg GUS")
    pkd_main: Optional[str] = Field(None, description="Główny kod PKD")
    
    # Błąd (jeśli wystąpił)
    error: Optional[str] = Field(None, description="Komunikat błędu z GUS")
    
    def to_billing_fields(self) -> dict:
        """
        Mapuje dane GUS do pól Billing (siedziba) w Zoho CRM.
        
        Returns:
            Dict z polami Billing_* gotowymi do zapisu w Zoho
        """
        if not self.found:
            return {}
        
        # Złóż pełną ulicę z komponentów
        street_parts = []
        if self.street:
            street_parts.append(self.street)
        if self.building_number:
            street_parts.append(self.building_number)
        if self.apartment_number:
            street_parts.append(f"/{self.apartment_number}")
        
        full_street = " ".join(street_parts) if street_parts else None
        
        return {
            # Pełny adres (jako jest w GUS)
            "Billing_Street": full_street,
            
            # Komponenty adresu
            "Billing_Street_Name": self.street,
            "Billing_Building_Number": self.building_number,
            "Billing_Local_Number": self.apartment_number,
            
            # Lokalizacja
            "Billing_Code": self.zip_code,
            "Billing_City": self.city,
            "Billing_Gmina": self.commune,
            "Billing_Powiat": self.county,
            "Billing_State": self.voivodeship,
            "Billing_Country": "Polska",
        }


class MatchSignals(BaseModel):
    """Sygnały dopasowania dla tier-based matching."""
    
    E: bool = Field(False, description="Email match")
    P: bool = Field(False, description="Phone match")
    L: bool = Field(False, description="Last name match")
    F: bool = Field(False, description="First name match")
    A: bool = Field(False, description="Account match")


class DuplicateMatch(BaseModel):
    """Pojedynczy potencjalny duplikat z tier-based matching."""
    
    id: str = Field(..., description="ID rekordu w Zoho")
    name: str = Field(..., description="Nazwa/imię i nazwisko")
    score: float = Field(..., ge=0.0, le=1.0, description="Pewność dopasowania (0-1)")
    match_reason: str = Field(..., description="Powód dopasowania (np. E+L+A)")
    
    # Tier-based matching
    tier: int = Field(0, ge=0, le=4, description="Tier dopasowania (4=najsilniejszy, 2=kandydat)")
    signals: MatchSignals = Field(default_factory=MatchSignals, description="Sygnały dopasowania")
    conflict_first_name: bool = Field(False, description="Czy jest konflikt imienia (Adam vs Jan)")
    record_quality_score: float = Field(0.0, description="Jakość rekordu (kompletność)")
    
    # Dodatkowe dane dla kontekstu
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    account_id: Optional[str] = Field(None, description="ID powiązanego Account")


class ContactExistsResult(BaseModel):
    """Wynik sprawdzenia 'czy kontakt istnieje' (tier-based)."""
    
    exists: bool = Field(False, description="Czy kontakt istnieje (Tier >= 3)")
    primary_id: Optional[str] = Field(None, description="ID jednoznacznie dopasowanego kontaktu")
    candidates: list[DuplicateMatch] = Field(
        default_factory=list, description="Kandydaci (max 2 poziomy, wszystkie z remisu)"
    )
    needs_review: bool = Field(False, description="Czy wymaga ręcznego przeglądu (remis top1)")


class AccountExistsResult(BaseModel):
    """Wynik sprawdzenia 'czy firma istnieje' (po NIP/domenie)."""
    
    exists: bool = Field(False, description="Czy firma istnieje")
    parent_id: Optional[str] = Field(None, description="ID siedziby (parent Account)")
    child_id: Optional[str] = Field(None, description="ID placówki podległej (child Account)")
    candidates: list[DuplicateMatch] = Field(
        default_factory=list, description="Znalezione firmy"
    )


class DuplicatesResult(BaseModel):
    """Wyniki wyszukiwania duplikatów z tier-based matching."""
    
    # Nowy format - tier-based
    contact: ContactExistsResult = Field(
        default_factory=ContactExistsResult, description="Wynik szukania kontaktu"
    )
    account: AccountExistsResult = Field(
        default_factory=AccountExistsResult, description="Wynik szukania firmy"
    )
    
    # Legacy - dla kompatybilności wstecznej
    contacts: list[DuplicateMatch] = Field(
        default_factory=list, description="[Legacy] Znalezione duplikaty w Contacts"
    )
    accounts: list[DuplicateMatch] = Field(
        default_factory=list, description="[Legacy] Znalezione duplikaty w Accounts"
    )
    leads: list[DuplicateMatch] = Field(
        default_factory=list, description="Znalezione duplikaty w Leads"
    )
    
    @property
    def has_duplicates(self) -> bool:
        return self.contact.exists or self.account.exists or bool(self.leads)
    
    @property
    def best_contact_match(self) -> Optional[DuplicateMatch]:
        """Zwraca najlepsze dopasowanie w Contacts."""
        if self.contact.candidates:
            return self.contact.candidates[0]
        if not self.contacts:
            return None
        return max(self.contacts, key=lambda x: x.score)
    
    @property
    def best_account_match(self) -> Optional[DuplicateMatch]:
        """Zwraca najlepsze dopasowanie w Accounts."""
        if self.account.candidates:
            return self.account.candidates[0]
        if not self.accounts:
            return None
        return max(self.accounts, key=lambda x: x.score)


class ProcessingRecommendation(BaseModel):
    """Rekomendacja działania na podstawie analizy."""
    
    action: Literal[
        "create_new",           # Utwórz nowy rekord
        "link_to_existing",     # Powiąż z istniejącym
        "merge_required",       # Wymaga ręcznego scalenia
        "discard_duplicate",    # Odrzuć jako duplikat
        "review_required",      # Wymaga przeglądu
    ] = Field(..., description="Rekomendowane działanie")
    
    confidence: float = Field(..., ge=0.0, le=1.0, description="Pewność rekomendacji")
    reason: str = Field(..., description="Uzasadnienie rekomendacji")
    
    # ID powiązanych rekordów
    contact_id: Optional[str] = Field(None, description="ID kontaktu do powiązania")
    account_id: Optional[str] = Field(None, description="ID firmy do powiązania")
    
    # Dodatkowe sugestie
    suggestions: list[str] = Field(default_factory=list, description="Dodatkowe sugestie")


class LeadOutput(BaseModel):
    """
    Pełna odpowiedź z przetworzenia leada.
    Zwracana do Zoho CRM.
    """
    
    success: bool = Field(True, description="Czy przetwarzanie zakończyło się sukcesem")
    
    # Znormalizowane dane
    normalized: NormalizedData = Field(
        default_factory=NormalizedData,
        description="Dane po normalizacji AI"
    )
    
    # Dane z GUS
    gus_data: GUSData = Field(
        default_factory=GUSData,
        description="Dane z rejestru GUS/REGON"
    )
    
    # Duplikaty
    duplicates: DuplicatesResult = Field(
        default_factory=DuplicatesResult,
        description="Znalezione potencjalne duplikaty"
    )
    
    # Rekomendacja
    recommendation: ProcessingRecommendation = Field(
        default_factory=lambda: ProcessingRecommendation(
            action="create_new",
            confidence=0.5,
            reason="Brak wystarczających danych do analizy"
        ),
        description="Rekomendowane działanie"
    )
    
    # Metadane przetwarzania
    processing_time_ms: Optional[int] = Field(None, description="Czas przetwarzania w ms")
    warnings: list[str] = Field(default_factory=list, description="Ostrzeżenia")
    errors: list[str] = Field(default_factory=list, description="Błędy (niekrytyczne)")
