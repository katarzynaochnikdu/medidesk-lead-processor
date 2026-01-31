"""
Konfiguracja Company Intelligence Tool.

Wszystkie ustawienia ładowane z .env lub wartości domyślne.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class CompanyIntelSettings(BaseSettings):
    """Ustawienia dla Company Intelligence Tool."""
    
    # === APIFY ===
    apify_api_token: Optional[str] = Field(None, alias="APIFY_API_TOKEN")
    apify_google_maps_actor_id: str = Field(
        "compass/crawler-google-places",
        alias="APIFY_GOOGLE_MAPS_ACTOR_ID"
    )
    apify_facebook_actor_id: str = Field(
        "apify/facebook-pages-scraper",
        alias="APIFY_FACEBOOK_ACTOR_ID"
    )
    apify_instagram_actor_id: str = Field(
        "apify/instagram-profile-scraper",
        alias="APIFY_INSTAGRAM_ACTOR_ID"
    )
    apify_tiktok_actor_id: str = Field(
        "clockworks/tiktok-scraper",
        alias="APIFY_TIKTOK_ACTOR_ID"
    )
    apify_actor_timeout_sec: int = Field(300, alias="APIFY_ACTOR_TIMEOUT_SEC")
    
    # === VERTEX AI ===
    vertex_ai_model: str = Field("gemini-2.5-pro", alias="VERTEX_AI_MODEL")
    gcp_project_id: Optional[str] = Field(None, alias="GCP_PROJECT_ID")
    gcp_region: str = Field("europe-central2", alias="GCP_REGION")
    
    # === GUS API ===
    gus_api_key: Optional[str] = Field(None, alias="REGON_API_KEY_TOKEN")
    
    # === TIMEOUTS ===
    request_timeout_sec: int = Field(30, alias="REQUEST_TIMEOUT_SEC")
    scraper_timeout_sec: int = Field(60, alias="SCRAPER_TIMEOUT_SEC")
    
    # === LOGGING ===
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_inputs_outputs: bool = Field(True, alias="LOG_INPUTS_OUTPUTS")
    
    # === CACHE ===
    cache_enabled: bool = Field(True, alias="CACHE_ENABLED")
    cache_ttl_days_social: int = Field(7, alias="CACHE_TTL_DAYS_SOCIAL")
    cache_ttl_days_categorization: int = Field(30, alias="CACHE_TTL_DAYS_CATEGORIZATION")
    cache_db_path: str = Field("company_intel/cache.db", alias="CACHE_DB_PATH")
    
    # === SCORING ===
    score_google_maps_rating_threshold: float = Field(4.5)
    score_google_maps_reviews_threshold: int = Field(50)
    score_facebook_followers_threshold: int = Field(1000)
    score_instagram_followers_threshold: int = Field(500)
    
    @property
    def has_apify_credentials(self) -> bool:
        """Sprawdza czy mamy credentials do Apify."""
        return bool(self.apify_api_token)
    
    @property
    def has_vertex_ai_credentials(self) -> bool:
        """Sprawdza czy mamy credentials do Vertex AI."""
        return bool(self.gcp_project_id)
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Singleton dla ustawień
_settings: Optional[CompanyIntelSettings] = None


def get_settings() -> CompanyIntelSettings:
    """Zwraca singleton ustawień."""
    global _settings
    if _settings is None:
        _settings = CompanyIntelSettings()
    return _settings


def reload_settings() -> CompanyIntelSettings:
    """Przeładowuje ustawienia (przydatne w testach)."""
    global _settings
    _settings = CompanyIntelSettings()
    return _settings
