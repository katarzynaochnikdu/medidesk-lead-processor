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


class NIPResult(BaseModel):
    """Wynik wyszukiwania NIP."""

    # Dane wejściowe
    company_name: str = Field(..., description="Nazwa firmy (input)")
    city: Optional[str] = Field(None, description="Miasto (input)")

    # Wynik
    found: bool = Field(..., description="Czy NIP został znaleziony")
    nip: Optional[str] = Field(None, description="NIP (10 cyfr)")
    nip_formatted: Optional[str] = Field(None, description="NIP sformatowany (XXX-XXX-XX-XX)")

    # Metadane
    confidence: float = Field(0.0, description="Poziom pewności (0.0-1.0)")
    strategy_used: Optional[SearchStrategy] = Field(None, description="Strategia która znalazła NIP")
    validation: Optional[ValidationResult] = Field(None, description="Wynik walidacji")

    # Dodatkowe informacje
    warnings: list[str] = Field(default_factory=list, description="Ostrzeżenia")
    processing_time_ms: int = Field(0, description="Czas przetwarzania w ms")
    cost_usd: float = Field(0.0, description="Koszt zapytania w USD")
    metadata: dict = Field(default_factory=dict, description="Dodatkowe metadane (strategy-specific)")

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
