"""
Konfiguracja NIP Finder.
"""

import os
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NIPFinderSettings(BaseSettings):
    """Konfiguracja NIP Finder - rozszerza Settings z głównego projektu."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Apify
    apify_api_token: str = Field(default="", description="Apify API token")
    apify_google_actor_id: str = Field(
        default="apify/google-search-scraper",
        description="ID Actora do Google Search"
    )
    apify_scraper_actor_id: str = Field(
        default="",
        description="ID Custom Actora do web scraping"
    )
    
    # Biała Lista VAT
    vat_whitelist_api_url: str = Field(
        default="https://wl-api.mf.gov.pl/api/search/nip/{nip}",
        description="URL API Białej Listy VAT"
    )
    
    # Cache
    nip_cache_db: str = Field(
        default="nip_finder/cache.db",
        description="Ścieżka do bazy SQLite cache"
    )
    nip_cache_ttl_days: int = Field(
        default=30,
        description="Czas życia cache w dniach"
    )
    
    # Thresholds
    nip_confidence_threshold: float = Field(
        default=0.7,
        description="Minimalny próg confidence dla zaakceptowania NIP"
    )
    fuzzy_match_threshold: float = Field(
        default=0.8,
        description="Próg fuzzy match dla nazw firm (0-1)"
    )
    
    # Apify Limits
    max_google_results: int = Field(
        default=20,
        description="Maksymalna liczba wyników Google per query"
    )
    max_urls_to_scrape: int = Field(
        default=10,
        description="Maksymalna liczba URL do scrapowania per firma"
    )
    max_scrape_text_length: int = Field(
        default=50000,
        description="Maksymalna długość tekstu do analizy AI (znaków)"
    )
    
    # Timeouts
    apify_actor_timeout_sec: int = Field(
        default=300,
        description="Timeout dla Apify Actor (sekundy)"
    )
    
    # Google Cloud (dziedziczymy z głównego config)
    gcp_project_id: str = ""
    gcp_region: str = "europe-central2"
    vertex_ai_model: str = "gemini-2.5-pro"
    
    # GUS API (dziedziczymy)
    gus_api_key: str = ""
    gus_api_url: str = "https://wfirma-api.onrender.com"
    
    @property
    def has_apify_credentials(self) -> bool:
        """Czy mamy pełne dane do Apify."""
        return bool(
            self.apify_api_token 
            and not self.apify_api_token.startswith("your-")
        )
    
    @property
    def has_vertex_ai(self) -> bool:
        """Czy mamy dostęp do Vertex AI."""
        return bool(self.gcp_project_id)


@lru_cache
def get_nip_finder_settings() -> NIPFinderSettings:
    """Singleton dla ustawień NIP Finder."""
    return NIPFinderSettings()
