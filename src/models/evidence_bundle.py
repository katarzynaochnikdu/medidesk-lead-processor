"""
EvidenceBundle - kanoniczny model przenoszony między etapami przetwarzania.

Zapewnia zasadę "nie płacimy 2x":
- Każdy etap najpierw sprawdza, czy dane są już w EvidenceBundle
- Wyniki GUS/scraping/AI są cache'owane i re-używane
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceSource(str, Enum):
    """Źródło danych w EvidenceBundle."""
    
    INPUT = "input"  # Dane wejściowe z leada
    AI_NORMALIZATION = "ai_normalization"  # Normalizacja AI
    GUS = "gus"  # Rejestr GUS
    NIP_FINDER = "nip_finder"  # NIPFinderV3
    WEBSITE_SCRAPER = "website_scraper"  # Scraping strony WWW
    GOOGLE_MAPS = "google_maps"  # Google Maps API
    ZOHO = "zoho"  # Zoho CRM
    BRAVE_SEARCH = "brave_search"  # Brave Search API
    SOCIAL_SCRAPER = "social_scraper"  # Scraping social media


class EvidenceItem(BaseModel):
    """Pojedynczy fakt z informacją o źródle."""
    
    value: Any = Field(..., description="Wartość faktu")
    source: EvidenceSource = Field(..., description="Źródło danych")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Pewność (0-1)")
    source_url: Optional[str] = Field(None, description="URL źródła (jeśli dotyczy)")
    collected_at: datetime = Field(default_factory=datetime.utcnow)


class ContactEvidence(BaseModel):
    """Dane kontaktowe z informacją o źródłach."""
    
    emails: list[EvidenceItem] = Field(default_factory=list)
    phones: list[EvidenceItem] = Field(default_factory=list)
    addresses: list[EvidenceItem] = Field(default_factory=list)
    
    def get_emails(self) -> list[str]:
        """Zwraca unikalne emaile (bez duplikatów)."""
        return list(dict.fromkeys(item.value for item in self.emails if item.value))
    
    def get_phones(self) -> list[str]:
        """Zwraca unikalne telefony (bez duplikatów)."""
        return list(dict.fromkeys(item.value for item in self.phones if item.value))
    
    def get_addresses(self) -> list[str]:
        """Zwraca unikalne adresy (bez duplikatów)."""
        return list(dict.fromkeys(item.value for item in self.addresses if item.value))
    
    def has_from_source(self, source: EvidenceSource) -> bool:
        """Sprawdza czy są dane z danego źródła."""
        all_items = self.emails + self.phones + self.addresses
        return any(item.source == source for item in all_items)


class IdentityEvidence(BaseModel):
    """Dane identyfikacyjne organizacji."""
    
    nip: Optional[EvidenceItem] = Field(None, description="NIP (10 cyfr)")
    regon: Optional[EvidenceItem] = Field(None, description="REGON")
    krs: Optional[EvidenceItem] = Field(None, description="KRS")
    domain: Optional[EvidenceItem] = Field(None, description="Domena firmowa")
    
    # Nazwy (może być kilka wariantów z różnych źródeł)
    names: list[EvidenceItem] = Field(default_factory=list, description="Nazwy firmy")
    
    def get_nip(self) -> Optional[str]:
        """Zwraca NIP jeśli jest."""
        return self.nip.value if self.nip else None
    
    def get_domain(self) -> Optional[str]:
        """Zwraca domenę jeśli jest."""
        return self.domain.value if self.domain else None
    
    def get_best_name(self) -> Optional[str]:
        """Zwraca najlepszą nazwę (najwyższy confidence)."""
        if not self.names:
            return None
        best = max(self.names, key=lambda x: x.confidence)
        return best.value


class LocationEvidence(BaseModel):
    """Dane o pojedynczej lokalizacji/placówce."""
    
    name: Optional[str] = Field(None, description="Nazwa placówki")
    address: Optional[str] = Field(None, description="Pełny adres")
    city: Optional[str] = Field(None, description="Miasto")
    postal_code: Optional[str] = Field(None, description="Kod pocztowy")
    street: Optional[str] = Field(None, description="Ulica")
    
    phone: Optional[str] = Field(None, description="Telefon placówki")
    email: Optional[str] = Field(None, description="Email placówki")
    
    # Google Maps
    google_place_id: Optional[str] = Field(None, description="Google Maps Place ID")
    google_rating: Optional[float] = Field(None, description="Ocena Google Maps")
    google_reviews_count: Optional[int] = Field(None, description="Liczba recenzji")
    
    # Źródło
    source: EvidenceSource = Field(EvidenceSource.INPUT)
    source_url: Optional[str] = Field(None)


class SocialLinksEvidence(BaseModel):
    """Linki do social media."""
    
    website: Optional[EvidenceItem] = None
    facebook: Optional[EvidenceItem] = None
    instagram: Optional[EvidenceItem] = None
    linkedin: Optional[EvidenceItem] = None
    tiktok: Optional[EvidenceItem] = None
    twitter: Optional[EvidenceItem] = None
    
    def get_all_urls(self) -> dict[str, str]:
        """Zwraca słownik platform -> URL."""
        result = {}
        for platform in ["website", "facebook", "instagram", "linkedin", "tiktok", "twitter"]:
            item = getattr(self, platform)
            if item and item.value:
                result[platform] = item.value
        return result
    
    def has_any(self) -> bool:
        """Sprawdza czy są jakiekolwiek linki."""
        return bool(self.get_all_urls())


class AIOutputs(BaseModel):
    """Wyniki AI (opcjonalne, tylko jeśli uruchomione)."""
    
    # Normalizacja
    normalization_done: bool = Field(False)
    normalized_first_name: Optional[str] = None
    normalized_last_name: Optional[str] = None
    normalized_company_name: Optional[str] = None
    detected_gender: Optional[Literal["male", "female", "unknown"]] = None
    
    # Kategoryzacja organizacji
    categorization_done: bool = Field(False)
    specialization: list[str] = Field(default_factory=list)
    payer_type: list[str] = Field(default_factory=list)  # NFZ, Komercyjne, etc.
    ownership_type: Optional[str] = None  # Prywatny, Publiczny
    industry: Optional[str] = None
    
    # Confidence i reasoning
    confidence: float = Field(0.0)
    reasoning: Optional[str] = None


class ProcessingCost(BaseModel):
    """Koszty przetwarzania."""
    
    ai_tokens_used: int = Field(0)
    ai_cost_usd: float = Field(0.0)
    api_calls: dict[str, int] = Field(default_factory=dict)  # source -> count
    total_time_ms: int = Field(0)


class EvidenceBundle(BaseModel):
    """
    Kanoniczny model przenoszony między etapami przetwarzania.
    
    Zapewnia:
    - Jednokrotne wykonywanie kosztownych operacji (GUS, scraping, AI)
    - Re-używanie wyników między etapami
    - Śledzenie źródeł danych
    """
    
    # Identyfikator sesji przetwarzania
    session_id: Optional[str] = Field(None, description="ID sesji przetwarzania")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # === CORE DATA ===
    
    # Tożsamość organizacji
    identity: IdentityEvidence = Field(default_factory=IdentityEvidence)
    
    # Dane kontaktowe (z różnych źródeł)
    contacts: ContactEvidence = Field(default_factory=ContactEvidence)
    
    # Placówki/lokalizacje
    locations: list[LocationEvidence] = Field(default_factory=list)
    
    # Social media linki
    social_links: SocialLinksEvidence = Field(default_factory=SocialLinksEvidence)
    
    # === DANE OSOBY (dla Lead Core) ===
    
    person_first_name: Optional[str] = None
    person_last_name: Optional[str] = None
    person_email: Optional[str] = None
    person_phone: Optional[str] = None
    person_title: Optional[str] = None
    person_role: Optional[str] = None
    
    # === METADANE ===
    
    # Źródła które już zostały odpytane (żeby nie robić 2x)
    sources_queried: list[EvidenceSource] = Field(default_factory=list)
    
    # Wyniki AI (opcjonalne)
    ai_outputs: AIOutputs = Field(default_factory=AIOutputs)
    
    # Koszty
    costs: ProcessingCost = Field(default_factory=ProcessingCost)
    
    # Ostrzeżenia i błędy
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    
    # === METODY POMOCNICZE ===
    
    def has_queried(self, source: EvidenceSource) -> bool:
        """Sprawdza czy źródło było już odpytane."""
        return source in self.sources_queried
    
    def mark_queried(self, source: EvidenceSource) -> None:
        """Oznacza źródło jako odpytane."""
        if source not in self.sources_queried:
            self.sources_queried.append(source)
    
    def has_nip(self) -> bool:
        """Sprawdza czy mamy NIP."""
        return self.identity.nip is not None
    
    def has_domain(self) -> bool:
        """Sprawdza czy mamy domenę."""
        return self.identity.domain is not None
    
    def has_company_name(self) -> bool:
        """Sprawdza czy mamy nazwę firmy."""
        return bool(self.identity.names)
    
    def get_entry_point(self) -> Literal["nip", "domain", "name", "none"]:
        """
        Określa najlepszy punkt wejścia do wyszukiwania.
        Zgodnie z zasadą 'prefer_best_available'.
        """
        if self.has_nip():
            return "nip"
        if self.has_domain():
            return "domain"
        if self.has_company_name():
            return "name"
        return "none"
    
    def add_email(self, email: str, source: EvidenceSource, confidence: float = 1.0, source_url: Optional[str] = None) -> None:
        """Dodaje email z informacją o źródle."""
        # Sprawdź czy już nie mamy tego emaila
        existing = [item.value.lower() for item in self.contacts.emails if item.value]
        if email.lower() not in existing:
            self.contacts.emails.append(EvidenceItem(
                value=email.lower(),
                source=source,
                confidence=confidence,
                source_url=source_url,
            ))
    
    def add_phone(self, phone: str, source: EvidenceSource, confidence: float = 1.0, source_url: Optional[str] = None) -> None:
        """Dodaje telefon z informacją o źródle."""
        # Normalizuj do porównania
        phone_clean = "".join(c for c in phone if c.isdigit())[-9:]
        existing = ["".join(c for c in item.value if c.isdigit())[-9:] for item in self.contacts.phones if item.value]
        if phone_clean not in existing:
            self.contacts.phones.append(EvidenceItem(
                value=phone,
                source=source,
                confidence=confidence,
                source_url=source_url,
            ))
    
    def add_address(self, address: str, source: EvidenceSource, confidence: float = 1.0, source_url: Optional[str] = None) -> None:
        """Dodaje adres z informacją o źródle."""
        existing = [item.value.lower() for item in self.contacts.addresses if item.value]
        if address.lower() not in existing:
            self.contacts.addresses.append(EvidenceItem(
                value=address,
                source=source,
                confidence=confidence,
                source_url=source_url,
            ))
    
    def set_nip(self, nip: str, source: EvidenceSource, confidence: float = 1.0, source_url: Optional[str] = None) -> None:
        """Ustawia NIP (tylko jeśli nie mamy lub nowy ma wyższy confidence)."""
        if self.identity.nip is None or confidence > self.identity.nip.confidence:
            self.identity.nip = EvidenceItem(
                value=nip,
                source=source,
                confidence=confidence,
                source_url=source_url,
            )
    
    def set_domain(self, domain: str, source: EvidenceSource, confidence: float = 1.0, source_url: Optional[str] = None) -> None:
        """Ustawia domenę (tylko jeśli nie mamy lub nowa ma wyższy confidence)."""
        # Normalizuj domenę
        domain_clean = domain.lower().replace("www.", "").strip("/")
        if self.identity.domain is None or confidence > self.identity.domain.confidence:
            self.identity.domain = EvidenceItem(
                value=domain_clean,
                source=source,
                confidence=confidence,
                source_url=source_url,
            )
    
    def add_company_name(self, name: str, source: EvidenceSource, confidence: float = 1.0) -> None:
        """Dodaje nazwę firmy."""
        existing = [item.value.lower() for item in self.identity.names if item.value]
        if name.lower() not in existing:
            self.identity.names.append(EvidenceItem(
                value=name,
                source=source,
                confidence=confidence,
            ))
    
    def add_location(self, location: LocationEvidence) -> None:
        """Dodaje lokalizację (z deduplikacją po adresie)."""
        # Deduplikacja po adresie
        existing_addresses = [
            (loc.city or "").lower() + "|" + (loc.address or "").lower()
            for loc in self.locations
        ]
        new_key = (location.city or "").lower() + "|" + (location.address or "").lower()
        if new_key not in existing_addresses:
            self.locations.append(location)
    
    def merge_scraped_data(self, scraped_data: Any, source: EvidenceSource, source_url: Optional[str] = None) -> None:
        """
        Merguje dane ze ScrapedCompanyData (z NIPFinderV3 lub WebsiteScraper).
        """
        if scraped_data is None:
            return
        
        # Emails
        for email in getattr(scraped_data, 'emails', []) or []:
            self.add_email(email, source, confidence=0.9, source_url=source_url)
        
        # Phones
        for phone in getattr(scraped_data, 'phones', []) or []:
            self.add_phone(phone, source, confidence=0.9, source_url=source_url)
        
        # Addresses
        for address in getattr(scraped_data, 'addresses', []) or []:
            self.add_address(address, source, confidence=0.8, source_url=source_url)
        
        # Domain
        if getattr(scraped_data, 'domain', None):
            self.set_domain(scraped_data.domain, source, confidence=0.95, source_url=source_url)
        
        # Social links
        social_links = getattr(scraped_data, 'social_links', {}) or {}
        for platform, url in social_links.items():
            if url:
                item = EvidenceItem(value=url, source=source, confidence=0.95, source_url=source_url)
                if platform == "facebook" and not self.social_links.facebook:
                    self.social_links.facebook = item
                elif platform == "instagram" and not self.social_links.instagram:
                    self.social_links.instagram = item
                elif platform == "linkedin" and not self.social_links.linkedin:
                    self.social_links.linkedin = item
                elif platform == "tiktok" and not self.social_links.tiktok:
                    self.social_links.tiktok = item
                elif platform in ("twitter", "x") and not self.social_links.twitter:
                    self.social_links.twitter = item


# === KONTRAKTY API ===

class LeadNormalizeRequest(BaseModel):
    """Request dla /lead/normalize."""
    
    data: dict = Field(..., description="Surowe dane leada z Zoho")
    skip_ai: bool = Field(False, description="Pomiń normalizację AI")


class LeadNormalizeResponse(BaseModel):
    """Response z /lead/normalize."""
    
    success: bool = True
    normalized_data: Optional[dict] = None
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    processing_time_ms: int = 0


class LeadEnrichCoreRequest(BaseModel):
    """Request dla /lead/enrich-core."""
    
    data: dict = Field(..., description="Surowe dane leada z Zoho")
    evidence: Optional[EvidenceBundle] = Field(None, description="Istniejący EvidenceBundle (opcjonalnie)")
    skip_ai: bool = Field(False, description="Pomiń normalizację AI")
    skip_nip_search: bool = Field(False, description="Pomiń wyszukiwanie NIP")
    skip_gus: bool = Field(False, description="Pomiń lookup GUS")


class LeadEnrichCoreResponse(BaseModel):
    """Response z /lead/enrich-core."""
    
    success: bool = True
    normalized_data: Optional[dict] = None
    gus_data: Optional[dict] = None
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    processing_time_ms: int = 0


class LeadDedupeRequest(BaseModel):
    """Request dla /lead/dedupe."""
    
    evidence: EvidenceBundle = Field(..., description="EvidenceBundle z danymi do deduplikacji")
    # Lub alternatywnie pojedyncze pola:
    email: Optional[str] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    nip: Optional[str] = None


class LeadDedupeResponse(BaseModel):
    """Response z /lead/dedupe."""
    
    success: bool = True
    duplicates: Optional[dict] = None
    recommendation: Optional[dict] = None
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    processing_time_ms: int = 0


class OrgEnrichCoreRequest(BaseModel):
    """Request dla /org/enrich-core."""
    
    # Można podać EvidenceBundle lub pojedyncze pola
    evidence: Optional[EvidenceBundle] = None
    
    # Alternatywne wejście (jeśli nie ma evidence)
    nip: Optional[str] = None
    website: Optional[str] = None
    company_name: Optional[str] = None
    city: Optional[str] = None
    
    # Flagi
    skip_ai_categorization: bool = Field(False, description="Pomiń kategoryzację AI")
    skip_locations: bool = Field(False, description="Pomiń wyszukiwanie placówek")


class OrgEnrichCoreResponse(BaseModel):
    """Response z /org/enrich-core."""
    
    success: bool = True
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    
    # Dane organizacji
    company_name: Optional[str] = None
    nip: Optional[str] = None
    regon: Optional[str] = None
    
    # Kategoryzacja
    specialization: list[str] = Field(default_factory=list)
    payer_type: list[str] = Field(default_factory=list)
    ownership_type: Optional[str] = None
    
    # Placówki (bez recenzji/opinii - to jest w social)
    locations_count: int = 0
    locations: list[dict] = Field(default_factory=list)
    
    # Kontakty
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    processing_time_ms: int = 0


class OrgEnrichSocialRequest(BaseModel):
    """Request dla /org/enrich-social."""
    
    evidence: EvidenceBundle = Field(..., description="EvidenceBundle z linkami social")
    
    # Alternatywnie można podać linki bezpośrednio
    facebook_url: Optional[str] = None
    instagram_url: Optional[str] = None
    tiktok_url: Optional[str] = None
    
    # Flagi
    include_reviews: bool = Field(False, description="Czy zbierać recenzje (Google Maps/ZnanyLekarz)")


class OrgEnrichSocialResponse(BaseModel):
    """Response z /org/enrich-social."""
    
    success: bool = True
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    
    # Social media stats
    social_profiles: list[dict] = Field(default_factory=list)
    
    # Activity Score
    activity_score: int = Field(0, ge=0, le=100)
    activity_recommendation: Optional[str] = None  # HOT_LEAD, LUKEWARM, COLD
    
    # Recenzje (tylko jeśli include_reviews=True)
    reviews_insights: Optional[dict] = None
    
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    processing_time_ms: int = 0
