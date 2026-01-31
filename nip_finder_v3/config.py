"""
Konfiguracja NIP Finder V3.
"""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NIPFinderV3Settings(BaseSettings):
    """Konfiguracja NIP Finder V3."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra env vars
    )

    # ============================================
    # API Keys
    # ============================================

    brave_search_api_key: str = Field(
        default="",
        description="Brave Search API key (required for Brave strategies)"
    )

    gus_api_key: str = Field(
        default="",
        description="GUS API key (production key required)",
        validation_alias=AliasChoices("gus_api_key", "regon_api_key_token"),
    )

    # Google AI Platform API Key (alternative to Vertex AI)
    ai_google_platform_models_api_key: str = Field(
        default="",
        description="Google AI Platform API key for Gemini models (alternative to Vertex AI)",
        validation_alias="ai_google_platfrom_models_api_key",  # Accept typo version from env
    )

    # Vertex AI (required for AI features)
    vertex_ai_project_id: str = Field(
        default="",
        description="Google Cloud project ID (also accepts GCP_PROJECT_ID)",
        validation_alias="gcp_project_id",  # Accept both VERTEX_AI_PROJECT_ID and GCP_PROJECT_ID
    )
    vertex_ai_location: str = Field(
        default="europe-central2",
        description="Vertex AI location",
        validation_alias="gcp_region",  # Accept both VERTEX_AI_LOCATION and GCP_REGION
    )

    # Apify (for Google Search Actor)
    apify_api_token: str = Field(
        default="",
        description="Apify API token (for Google Search)"
    )
    apify_google_actor_id: str = Field(
        default="apify/google-search-scraper",
        description="Apify Google Search Actor ID"
    )
    apify_actor_timeout_sec: int = Field(
        default=300,
        description="Apify Actor timeout in seconds"
    )

    # Google Custom Search JSON API (alternative to Apify)
    google_api_key: str = Field(
        default="",
        description="Google API key for Custom Search JSON API"
    )
    google_search_engine_id: str = Field(
        default="",
        description="Google Custom Search Engine ID (cx parameter)"
    )

    # ScraperAPI / Bright Data (proxy scraping)
    scraper_api_key: str = Field(
        default="",
        description="ScraperAPI key (optional, for proxy-based scraping)"
    )

    # ============================================
    # Strategy Toggles
    # ============================================

    enable_cache: bool = Field(
        default=True,
        description="Enable SQLite caching"
    )
    enable_privacy_scraping: bool = Field(
        default=True,
        description="Enable privacy policy scraping (90% success)"
    )
    enable_gus_search: bool = Field(
        default=True,
        description="Enable GUS API search by name (60-70% success)"
    )
    enable_homepage_scraping: bool = Field(
        default=True,
        description="Enable homepage footer scraping (70% success)"
    )
    enable_brave_search: bool = Field(
        default=True,
        description="Enable Brave Search strategies (60% domain, 30% name)"
    )
    enable_deep_ai_search: bool = Field(
        default=False,
        description="Enable Deep AI search (expensive, $0.10/lead)"
    )

    # ============================================
    # Ultimate Solution Strategy Toggles
    # ============================================

    enable_ai_enrichment: bool = Field(
        default=True,
        description="Enable AI-powered input enrichment (Level 0)"
    )
    enable_fuzzy_cache: bool = Field(
        default=True,
        description="Enable smart cache with fuzzy matching (Level 1)"
    )
    enable_google_search: bool = Field(
        default=True,
        description="Enable Google Search via Apify/JSON API (Level 3)"
    )
    enable_ai_domain_discovery: bool = Field(
        default=True,
        description="Enable AI-powered domain discovery (Level 4)"
    )
    enable_deep_scraping: bool = Field(
        default=True,
        description="Enable deep multi-page scraping with AI (Level 5)"
    )
    enable_ai_web_analysis: bool = Field(
        default=True,
        description="Enable AI web search + deep analysis (Level 6)"
    )
    enable_multi_source_validation: bool = Field(
        default=True,
        description="Enable multi-source cross-validation (Level 7)"
    )
    enable_ai_semantic_validation: bool = Field(
        default=True,
        description="Enable AI semantic validation for Google Search results (uses Gemini Flash - fast & high limits)"
    )

    # ============================================
    # Cache Settings
    # ============================================

    cache_db_path: str = Field(
        default="nip_finder_v3/cache.db",
        description="Path to SQLite cache database"
    )
    cache_ttl_days: int = Field(
        default=30,
        description="Cache TTL in days"
    )
    cache_freshness_warning_days: int = Field(
        default=14,
        description="Show freshness warning after this many days"
    )

    # ============================================
    # Validation Settings
    # ============================================

    require_checksum_validation: bool = Field(
        default=True,
        description="Require NIP checksum validation (always recommended)"
    )
    require_domain_validation: bool = Field(
        default=True,
        description="Require domain validation when domain available"
    )
    require_gus_validation: bool = Field(
        default=False,
        description="Require GUS validation (optional, slower)"
    )
    fuzzy_match_threshold: float = Field(
        default=0.70,
        description="Fuzzy matching threshold for company names (0.0-1.0)"
    )

    # ============================================
    # Performance Settings
    # ============================================

    max_concurrent_requests: int = Field(
        default=5,
        description="Max concurrent requests in batch processing"
    )
    request_timeout_sec: int = Field(
        default=30,
        description="HTTP request timeout in seconds"
    )
    brave_rate_limit_per_sec: float = Field(
        default=1.0,
        description="Brave API rate limit (requests per second)"
    )

    # ============================================
    # Cost Settings
    # ============================================

    max_cost_per_lead: float = Field(
        default=0.15,
        description="Maximum cost per lead in USD (budget cap)"
    )

    # ============================================
    # Retry Settings
    # ============================================

    max_retries: int = Field(
        default=2,
        description="Max retry attempts for failed requests"
    )
    retry_delay_sec: float = Field(
        default=1.0,
        description="Delay between retries in seconds"
    )

    # ============================================
    # Scraping Settings
    # ============================================

    scraping_timeout_sec: int = Field(
        default=10,
        description="Timeout for web scraping in seconds"
    )
    max_scraping_attempts: int = Field(
        default=3,
        description="Max attempts for scraping a URL"
    )
    user_agent: str = Field(
        default="NIPFinderV3/1.0 (compatible; +https://medidesk.pl)",
        description="User-Agent header for scraping"
    )

    # ============================================
    # Privacy Policy URLs
    # ============================================

    privacy_url_variants: list[str] = Field(
        default_factory=lambda: [
            "/polityka-prywatnosci",
            "/polityka-prywatności",  # Polish ó
            "/privacy-policy",
            "/rodo",
            "/polityka_prywatnosci",
            "/pl/polityka-prywatnosci",
            "/privacy",
            "/en/privacy-policy",
        ],
        description="Privacy policy URL variants to try"
    )

    # ============================================
    # Public Email Domains (to ignore)
    # ============================================

    public_email_domains: list[str] = Field(
        default_factory=lambda: [
            "gmail.com",
            "outlook.com",
            "hotmail.com",
            "yahoo.com",
            "interia.pl",
            "onet.pl",
            "wp.pl",
            "o2.pl",
            "poczta.pl",
            "buziaczek.pl",
        ],
        description="Public email domains to ignore (no company domain)"
    )

    # ============================================
    # GUS API Settings
    # ============================================

    gus_api_url: str = Field(
        default="https://wyszukiwarkaregon.stat.gov.pl/wsBIR/wsdl/UslugaBIRzewnPubl-ver11-prod.wsdl",
        description="GUS API URL (production WSDL v11)"
    )
    gus_use_test: bool = Field(
        default=False,
        description="Use GUS test environment (not recommended)"
    )

    # ============================================
    # AI Settings (Vertex AI Gemini)
    # ============================================

    vertex_ai_model: str = Field(
        default="gemini-2.0-flash-exp",
        description="Vertex AI model (Flash = faster + higher rate limits, Pro = more accurate)"
    )
    ai_temperature: float = Field(
        default=0.1,
        description="AI temperature (0.0-1.0, lower = more deterministic)"
    )
    ai_max_tokens: int = Field(
        default=1000,
        description="Max tokens for AI responses"
    )

    # ============================================
    # Google Search Settings
    # ============================================

    max_google_results: int = Field(
        default=10,
        description="Max Google search results per query"
    )
    google_search_country: str = Field(
        default="pl",
        description="Google search country code"
    )
    google_search_language: str = Field(
        default="pl",
        description="Google search language code"
    )

    # ============================================
    # Deep Scraping Settings
    # ============================================

    max_pages_to_scrape: int = Field(
        default=10,
        description="Max pages to scrape per company (Level 5-6)"
    )
    scrape_pages_list: list[str] = Field(
        default_factory=lambda: [
            "/polityka-prywatnosci",
            "/rodo",
            "/kontakt",
            "/o-nas",
            "/",  # homepage
            "/regulamin",
            "/about",
            "/contact",
        ],
        description="Page paths to scrape for deep analysis"
    )

    # ============================================
    # Confidence & Quality Settings
    # ============================================

    min_confidence_threshold: float = Field(
        default=0.60,
        description="Minimum confidence to accept NIP (reject below this)"
    )
    min_sources_agreement: int = Field(
        default=2,
        description="Minimum number of sources that must agree (multi-source validation)"
    )
    reject_low_confidence_without_domain: bool = Field(
        default=True,
        description="Reject low-confidence results if no domain available"
    )

    # Strict mode: reject results without domain validation
    require_domain_for_acceptance: bool = Field(
        default=True,
        description="STRICT: Reject any NIP that wasn't validated with domain (prevents wrong company NIP)"
    )


# Singleton instance
_settings: NIPFinderV3Settings = None


def get_settings() -> NIPFinderV3Settings:
    """Get singleton settings instance."""
    global _settings
    if _settings is None:
        _settings = NIPFinderV3Settings()
    return _settings
