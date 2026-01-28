"""
Konfiguracja aplikacji - centralne zarządzanie ustawieniami.
Używa pydantic-settings dla walidacji i typowania.
"""

import os
from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, model_validator
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
    vertex_ai_model: str = "gemini-2.5-pro"
    
    # GUS/REGON - różne nazwy zmiennych
    gus_api_key: str = ""
    regon_api_key_token: str = ""
    bir1_gus_api_key: str = ""
    gus_api_url: str = "https://wfirma-api.onrender.com"
    gus_use_test: bool = False
    
    # Zoho CRM - różne nazwy zmiennych
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_md_crm_leady_crud_client_id: str = ""
    zoho_md_crm_leady_crud_client_secret: str = ""
    zoho_md_crm_leady_crud_refresh_token: str = ""
    zoho_region: Literal["eu", "com", "in", "jp", "au", "ca"] = "eu"
    
    # API Security - różne nazwy zmiennych
    api_key: str = ""
    gcp_leads_api_key: str = ""
    gcp_api_key_id: str = ""
    
    # Brave Search API
    brave_search_api_key: str = ""
    
    @model_validator(mode="after")
    def resolve_aliases(self):
        """Rozwiązuje aliasy zmiennych po załadowaniu wszystkich wartości."""
        # GUS API Key: priorytet REGON > BIR1 > GUS (REGON jest aktualny)
        # Zawsze używaj specyficznych zmiennych jeśli są dostępne
        if self.regon_api_key_token and not self.regon_api_key_token.startswith("your-"):
            self.gus_api_key = self.regon_api_key_token
        elif self.bir1_gus_api_key and not self.bir1_gus_api_key.startswith("your-"):
            self.gus_api_key = self.bir1_gus_api_key
        elif not self.gus_api_key or self.gus_api_key.startswith("your-"):
            self.gus_api_key = ""
        
        # API Key: priorytet GCP_LEADS > GCP_API_KEY_ID > API_KEY
        if not self.api_key or self.api_key.startswith("your-"):
            self.api_key = self.gcp_leads_api_key or self.gcp_api_key_id or ""
        
        # Zoho: priorytet ZOHO_MD_CRM_* > ZOHO_*
        if not self.zoho_client_id or self.zoho_client_id.startswith("your-"):
            self.zoho_client_id = self.zoho_md_crm_leady_crud_client_id or ""
        if not self.zoho_client_secret or self.zoho_client_secret.startswith("your-"):
            self.zoho_client_secret = self.zoho_md_crm_leady_crud_client_secret or ""
        if not self.zoho_refresh_token or self.zoho_refresh_token.startswith("your-"):
            self.zoho_refresh_token = self.zoho_md_crm_leady_crud_refresh_token or ""
        
        return self
    
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
