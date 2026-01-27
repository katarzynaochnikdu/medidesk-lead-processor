"""
Konfiguracja aplikacji - centralne zarządzanie ustawieniami.
Używa pydantic-settings dla walidacji i typowania.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Główna konfiguracja aplikacji."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Google Cloud
    gcp_project_id: str = ""
    gcp_region: str = "europe-central2"
    
    # Vertex AI
    vertex_ai_model: str = "gemini-1.5-flash-001"
    
    # GUS/REGON - proxy przez wfirma-api na Render
    gus_api_key: str = ""  # Token do API na Render (REGON_API_KEY_TOKEN)
    gus_api_url: str = "https://wfirma-api.onrender.com"  # URL API na Render
    gus_use_test: bool = False
    
    @field_validator("gus_api_key", mode="before")
    @classmethod
    def resolve_gus_api_key(cls, v):
        """Sprawdź alternatywne nazwy zmiennej."""
        # Priorytet: BIR1_GUS_API_KEY > REGON_API_KEY_TOKEN > GUS_API_KEY
        alt = os.getenv("BIR1_GUS_API_KEY") or os.getenv("REGON_API_KEY_TOKEN")
        if alt:
            return alt
        if v and not v.startswith("your-"):
            return v
        return alt or v or ""
    
    # Zoho CRM (obsługuje też ZOHO_MD_CRM_LEADY_CRUD_* z env)
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_region: Literal["eu", "com", "in", "jp", "au", "ca"] = "eu"
    
    @field_validator("zoho_client_id", mode="before")
    @classmethod
    def resolve_zoho_client_id(cls, v):
        """Sprawdź alternatywną nazwę zmiennej (priorytet dla ZOHO_MD_CRM_*)."""
        alt = os.getenv("ZOHO_MD_CRM_LEADY_CRUD_CLIENT_ID")
        if alt:
            return alt
        if v and not v.startswith("your-"):
            return v
        return alt or v or ""
    
    @field_validator("zoho_client_secret", mode="before")
    @classmethod
    def resolve_zoho_client_secret(cls, v):
        """Sprawdź alternatywną nazwę zmiennej (priorytet dla ZOHO_MD_CRM_*)."""
        alt = os.getenv("ZOHO_MD_CRM_LEADY_CRUD_CLIENT_SECRET")
        if alt:
            return alt
        if v and not v.startswith("your-"):
            return v
        return alt or v or ""
    
    @field_validator("zoho_refresh_token", mode="before")
    @classmethod
    def resolve_zoho_refresh_token(cls, v):
        """Sprawdź alternatywną nazwę zmiennej (priorytet dla ZOHO_MD_CRM_*)."""
        alt = os.getenv("ZOHO_MD_CRM_LEADY_CRUD_REFRESH_TOKEN")
        if alt:
            return alt
        if v and not v.startswith("your-"):
            return v
        return alt or v or ""
    
    # API Security (obsługuje też GCP_API_KEY_ID z env)
    api_key: str = ""
    
    @field_validator("api_key", mode="before")
    @classmethod
    def resolve_api_key(cls, v):
        """Sprawdź alternatywną nazwę zmiennej."""
        alt = os.getenv("GCP_API_KEY_ID")
        if alt:
            return alt
        if v and not v.startswith("your-"):
            return v
        return alt or v or ""
    
    # Environment
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    
    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def zoho_api_base(self) -> str:
        """Zwraca bazowy URL API Zoho dla danego regionu."""
        region_map = {
            "eu": "https://www.zohoapis.eu",
            "com": "https://www.zohoapis.com",
            "in": "https://www.zohoapis.in",
            "jp": "https://www.zohoapis.jp",
            "au": "https://www.zohoapis.com.au",
            "ca": "https://www.zohoapis.ca",
        }
        return region_map.get(self.zoho_region, region_map["eu"])
    
    @property
    def zoho_oauth_base(self) -> str:
        """Zwraca bazowy URL OAuth Zoho dla danego regionu."""
        region_map = {
            "eu": "https://accounts.zoho.eu",
            "com": "https://accounts.zoho.com",
            "in": "https://accounts.zoho.in",
            "jp": "https://accounts.zoho.jp",
            "au": "https://accounts.zoho.com.au",
            "ca": "https://accounts.zoho.ca",
        }
        return region_map.get(self.zoho_region, region_map["eu"])
    


@lru_cache
def get_settings() -> Settings:
    """Singleton dla ustawień - cachowane przy pierwszym wywołaniu."""
    return Settings()
