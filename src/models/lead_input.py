"""
Modele wejściowe - dane leada otrzymywane z Zoho CRM.
Obsługuje różne formaty danych (chaotyczne dane z formularzy).
"""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class LeadInputRaw(BaseModel):
    """
    Surowe dane leada - bez walidacji, przyjmuje wszystko.
    Używane gdy dane są bardzo chaotyczne.
    """
    
    # Dane osobowe - mogą być w różnych formatach
    raw_name: Optional[str] = Field(None, description="Pełne imię i nazwisko razem")
    first_name: Optional[str] = Field(None, alias="First_Name")
    last_name: Optional[str] = Field(None, alias="Last_Name")
    imie: Optional[str] = Field(None, alias="Imie")
    nazwisko: Optional[str] = Field(None, alias="Nazwisko")
    name: Optional[str] = Field(None, alias="Name")
    
    # Firma
    company: Optional[str] = Field(None, description="Nazwa firmy")
    firma: Optional[str] = Field(None, alias="Firma")
    account_name: Optional[str] = Field(None, alias="Account_Name")
    
    # Kontakt
    email: Optional[str] = Field(None, alias="Email")
    phone: Optional[str] = Field(None, description="Dowolny telefon")
    telefon_komorkowy: Optional[str] = Field(None, alias="Telefon_komorkowy")
    telefon_stacjonarny: Optional[str] = Field(None, alias="Telefon_stacjonarny")
    mobile: Optional[str] = Field(None, alias="Mobile")
    
    # Identyfikatory firmowe
    nip: Optional[str] = Field(None, alias="NIP")
    regon: Optional[str] = Field(None, alias="REGON")
    
    # Adres
    street: Optional[str] = Field(None, alias="Street")
    city: Optional[str] = Field(None, alias="City")
    zip_code: Optional[str] = Field(None, alias="Zip_Code")
    
    # Metadane Zoho
    id: Optional[str] = Field(None, description="ID rekordu w Zoho")
    owner: Optional[Any] = Field(None, alias="Owner")
    lead_source: Optional[str] = Field(None, alias="Lead_Source")
    
    # Dodatkowe pola - elastyczne
    extra_fields: dict[str, Any] = Field(default_factory=dict)
    
    model_config = {
        "populate_by_name": True,
        "extra": "allow",  # Pozwól na dodatkowe pola
    }
    
    def get_best_name(self) -> Optional[str]:
        """Zwraca najlepsze dostępne imię/nazwisko."""
        if self.raw_name:
            return self.raw_name
        
        parts = []
        first = self.first_name or self.imie
        last = self.last_name or self.nazwisko
        
        if first:
            parts.append(first)
        if last:
            parts.append(last)
        
        if parts:
            return " ".join(parts)
        
        return self.name
    
    def get_best_company(self) -> Optional[str]:
        """Zwraca najlepszą dostępną nazwę firmy."""
        return self.company or self.firma or self.account_name
    
    def get_best_phone(self) -> Optional[str]:
        """Zwraca najlepszy dostępny telefon."""
        return (
            self.phone
            or self.telefon_komorkowy
            or self.mobile
            or self.telefon_stacjonarny
        )
    
    def get_clean_nip(self) -> Optional[str]:
        """Zwraca NIP bez formatowania (tylko cyfry)."""
        if not self.nip:
            return None
        return "".join(c for c in self.nip if c.isdigit())


class LeadInput(BaseModel):
    """
    Uproszczony model wejściowy - po wstępnej normalizacji.
    Używany gdy dane są już częściowo ustrukturyzowane.
    """
    
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    
    company_name: Optional[str] = None
    
    email: Optional[str] = None
    phone: Optional[str] = None
    
    nip: Optional[str] = None
    
    street: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    
    zoho_id: Optional[str] = None
    lead_source: Optional[str] = None
    
    @field_validator("nip", mode="before")
    @classmethod
    def clean_nip(cls, v: Optional[str]) -> Optional[str]:
        """Usuń formatowanie z NIP."""
        if not v:
            return None
        return "".join(c for c in str(v) if c.isdigit())
    
    @field_validator("phone", mode="before")
    @classmethod
    def clean_phone(cls, v: Optional[str]) -> Optional[str]:
        """Usuń formatowanie z telefonu."""
        if not v:
            return None
        # Zachowaj + na początku
        cleaned = "".join(c for c in str(v) if c.isdigit() or c == "+")
        return cleaned if cleaned else None
    
    @classmethod
    def from_raw(cls, raw: LeadInputRaw) -> "LeadInput":
        """Konwertuje surowe dane na ustrukturyzowany model."""
        return cls(
            first_name=raw.first_name or raw.imie,
            last_name=raw.last_name or raw.nazwisko,
            full_name=raw.get_best_name(),
            company_name=raw.get_best_company(),
            email=raw.email,
            phone=raw.get_best_phone(),
            nip=raw.get_clean_nip(),
            street=raw.street,
            city=raw.city,
            zip_code=raw.zip_code,
            zoho_id=raw.id,
            lead_source=raw.lead_source,
        )
