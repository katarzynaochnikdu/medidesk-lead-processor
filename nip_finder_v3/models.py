"""
Modele danych dla NIP Finder V3.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SearchStrategy(str, Enum):
    """Strategie wyszukiwania NIP."""

    CACHE = "cache"
    AI_ENRICHMENT = "ai_enrichment"
    PRIVACY_SCRAPER = "privacy_scraper"
    GUS_SEARCH = "gus_search"
    REGON_SEARCH = "regon_search"
    HOMEPAGE_SCRAPER = "homepage_scraper"
    GOOGLE_SEARCH = "google_search"
    BRAVE_SEARCH_DOMAIN = "brave_search_domain"
    BRAVE_SEARCH_NAME = "brave_search_name"
    AI_DOMAIN_DISCOVERY = "ai_domain_discovery"
    AI_DEEP_SCRAPING = "ai_deep_scraping"
    AI_WEB_ANALYSIS = "ai_web_analysis"
    DEEP_AI_SEARCH = "deep_ai_search"


class NIPRequest(BaseModel):
    """Request do wyszukiwania NIP."""

    company_name: str = Field(..., description="Nazwa firmy")
    city: Optional[str] = Field(None, description="Miasto")
    email: Optional[str] = Field(None, description="Email (do ekstrakcji domeny)")


class ValidationResult(BaseModel):
    """Wynik walidacji NIP."""

    validated: bool = Field(..., description="Czy NIP przeszedł walidację")
    checksum_valid: bool = Field(..., description="Czy checksum jest poprawny")
    domain_valid: Optional[bool] = Field(None, description="Czy NIP znajduje się na domenie firmy")
    gus_found: Optional[bool] = Field(None, description="Czy NIP znaleziony w GUS")
    gus_name: Optional[str] = Field(None, description="Nazwa firmy z GUS")
    name_match_score: Optional[float] = Field(
        None, description="Score dopasowania nazwy firmy (0.0-1.0)"
    )
    errors: list[str] = Field(default_factory=list, description="Lista błędów walidacji")


class NIPCandidate(BaseModel):
    """Kandydat na NIP - alternatywna propozycja."""

    nip: str = Field(..., description="NIP (10 cyfr)")
    nip_formatted: str = Field(..., description="NIP sformatowany (XXX-XXX-XX-XX)")
    company_name_found: Optional[str] = Field(None, description="Nazwa firmy znaleziona przy NIP")
    confidence: float = Field(0.0, description="Poziom pewności (0.0-1.0)")
    source_url: Optional[str] = Field(None, description="URL źródła")
    source_domain: Optional[str] = Field(None, description="Domena źródła")
    reasoning: Optional[str] = Field(None, description="Uzasadnienie AI")


class ScrapedCompanyData(BaseModel):
    """Dane zebrane podczas crawlowania strony firmy."""

    # Domena źródłowa
    domain: Optional[str] = Field(None, description="Domena firmowa")

    # Dane kontaktowe znalezione na stronie
    emails: list[str] = Field(
        default_factory=list, description="Adresy email znalezione na stronie"
    )
    phones: list[str] = Field(
        default_factory=list, description="Numery telefonów w formacie +48XXXXXXXXX"
    )
    addresses: list[str] = Field(
        default_factory=list, description="Adresy znalezione na stronie"
    )

    # Social media
    social_links: dict[str, str] = Field(
        default_factory=dict,
        description="Linki do social media {platform: url}",
    )

    # Metadane strony
    website_title: Optional[str] = Field(None, description="Tytuł strony (<title>)")

    # Źródła danych
    source_urls: list[str] = Field(
        default_factory=list, description="URL-e z których pobrano dane"
    )

    def merge(self, other: "ScrapedCompanyData") -> "ScrapedCompanyData":
        """Łączy dane z innego ScrapedCompanyData (bez duplikatów)."""
        # Emails - unique
        all_emails = list(dict.fromkeys(self.emails + other.emails))
        # Phones - unique
        all_phones = list(dict.fromkeys(self.phones + other.phones))
        # Addresses - unique
        all_addresses = list(dict.fromkeys(self.addresses + other.addresses))
        # Social links - merge dicts (other overwrites)
        merged_social = {**self.social_links, **other.social_links}
        # Source URLs - unique
        all_sources = list(dict.fromkeys(self.source_urls + other.source_urls))

        return ScrapedCompanyData(
            domain=self.domain or other.domain,
            emails=all_emails,
            phones=all_phones,
            addresses=all_addresses,
            social_links=merged_social,
            website_title=self.website_title or other.website_title,
            source_urls=all_sources,
        )


class NIPResult(BaseModel):
    """Wynik wyszukiwania NIP."""

    # Dane wejściowe
    company_name: str = Field(..., description="Nazwa firmy (input)")
    city: Optional[str] = Field(None, description="Miasto (input)")

    # Wynik główny (best choice)
    found: bool = Field(..., description="Czy NIP został znaleziony")
    nip: Optional[str] = Field(None, description="NIP (10 cyfr)")
    nip_formatted: Optional[str] = Field(None, description="NIP sformatowany (XXX-XXX-XX-XX)")

    # Alternatywni kandydaci (maybe - max 5)
    alternatives: list[NIPCandidate] = Field(
        default_factory=list, 
        description="Alternatywni kandydaci (max 5) - inne możliwe NIPy"
    )

    # Metadane
    confidence: float = Field(0.0, description="Poziom pewności (0.0-1.0)")
    strategy_used: Optional[SearchStrategy] = Field(None, description="Strategia która znalazła NIP")
    validation: Optional[ValidationResult] = Field(None, description="Wynik walidacji")

    # Dodatkowe informacje
    warnings: list[str] = Field(default_factory=list, description="Ostrzeżenia")
    processing_time_ms: int = Field(0, description="Czas przetwarzania w ms")
    cost_usd: float = Field(0.0, description="Koszt zapytania w USD")
    metadata: dict = Field(default_factory=dict, description="Dodatkowe metadane (strategy-specific)")

    # Dane zebrane podczas crawlowania
    scraped_data: Optional[ScrapedCompanyData] = Field(
        None, description="Dane kontaktowe zebrane podczas scrapingu (email, tel, adres, social)"
    )

    # Cache metadata
    from_cache: bool = Field(False, description="Czy wynik z cache")
    cache_age_days: Optional[int] = Field(None, description="Wiek cache w dniach")


class CacheEntry(BaseModel):
    """Wpis w cache."""

    company_name: str
    city: Optional[str]
    nip: Optional[str]
    confidence: float
    strategy: str
    validation_json: str
    created_at: datetime
    last_updated_at: datetime

    def is_expired(self, ttl_days: int = 30) -> bool:
        """Sprawdza czy wpis wygasł."""
        age_days = (datetime.utcnow() - self.created_at).days
        return age_days > ttl_days

    def age_days(self) -> int:
        """Zwraca wiek wpisu w dniach."""
        return (datetime.utcnow() - self.created_at).days

    def needs_freshness_warning(self, warning_days: int = 14) -> bool:
        """Sprawdza czy potrzebne ostrzeżenie o świeżości."""
        return self.age_days() > warning_days


class BatchNIPRequest(BaseModel):
    """Request do batch processing."""

    companies: list[NIPRequest]
    max_concurrent: int = Field(5, description="Max równoczesnych requestów")
    skip_cache: bool = Field(False, description="Pomiń cache")


class BatchNIPResult(BaseModel):
    """Wynik batch processing."""

    results: list[NIPResult]
    total: int
    found: int
    not_found: int
    success_rate: float
    total_cost_usd: float
    avg_cost_usd: float
    total_time_ms: int
    avg_time_ms: int

    # Strategy breakdown
    strategy_stats: dict[str, int] = Field(
        default_factory=dict,
        description="Statystyki użycia strategii"
    )
