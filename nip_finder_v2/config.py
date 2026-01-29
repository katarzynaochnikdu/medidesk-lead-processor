"""
Konfiguracja NIP Finder v2.
"""

import os
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NIPFinderV2Settings(BaseSettings):
    """Konfiguracja NIP Finder v2."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # GUS API (BIR1)
    bir1_gus_api_key: str = Field(default="", description="Klucz do GUS BIR1 API")
    gus_test_mode: bool = Field(default=False, description="Czy uzywac srodowiska testowego GUS")
    
    # Apify (dla Google Search)
    apify_api_token: str = Field(default="", description="Apify API token")
    apify_google_actor_id: str = Field(
        default="apify/google-search-scraper",
        description="ID Actora do Google Search"
    )
    
    # Timeouts
    gus_timeout_sec: int = Field(default=30, description="Timeout dla GUS API")
    google_timeout_sec: int = Field(default=60, description="Timeout dla Google Search")
    scrape_timeout_sec: int = Field(default=30, description="Timeout dla scrapera")
    
    # Thresholds
    name_match_threshold: float = Field(
        default=0.7,
        description="Minimalny prog podobienstwa nazw (0-1)"
    )
    
    @property
    def has_gus_credentials(self) -> bool:
        """Czy mamy klucz do GUS."""
        return bool(self.bir1_gus_api_key and not self.bir1_gus_api_key.startswith("your-"))
    
    @property
    def has_apify_credentials(self) -> bool:
        """Czy mamy klucz do Apify."""
        return bool(self.apify_api_token and not self.apify_api_token.startswith("your-"))


@lru_cache
def get_settings() -> NIPFinderV2Settings:
    """Singleton dla ustawien."""
    return NIPFinderV2Settings()
