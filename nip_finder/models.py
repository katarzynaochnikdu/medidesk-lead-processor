"""
Modele danych dla NIP Finder.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class NIPRequest(BaseModel):
    """Request do wyszukania NIP."""
    
    company_name: str = Field(..., description="Nazwa firmy (może być chaotyczna)")
    city: Optional[str] = Field(None, description="Miasto (opcjonalne)")
    email: Optional[str] = Field(None, description="Email (opcjonalne, dla domeny)")
    phone: Optional[str] = Field(None, description="Telefon (opcjonalne)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_name": "VITA MEDICA SIEDLCE",
                "city": "Siedlce",
                "email": "kontakt@vitamedica.pl"
            }
        }


class ValidationResult(BaseModel):
    """Wynik walidacji NIP."""
    
    valid_checksum: bool = Field(..., description="Czy checksum NIP poprawny")
    vat_active: Optional[bool] = Field(None, description="Czy NIP aktywny w VAT (Biała Lista)")
    gus_found: bool = Field(False, description="Czy znaleziono w GUS")
    gus_name: Optional[str] = Field(None, description="Nazwa z GUS")
    name_match_score: Optional[float] = Field(None, description="Score dopasowania nazw (0-1)")
    validated: bool = Field(..., description="Czy NIP w pełni zwalidowany")
    validation_errors: List[str] = Field(default_factory=list, description="Lista błędów walidacji")


class SearchSource(BaseModel):
    """Źródło znalezionego NIP."""
    
    url: str = Field(..., description="URL źródła")
    strategy: str = Field(..., description="Strategia znalezienia (google/scraping/cache)")
    text_snippet: Optional[str] = Field(None, description="Fragment tekstu z NIP")


class NIPResult(BaseModel):
    """Wynik wyszukania NIP."""
    
    # Input
    company_name: str
    city: Optional[str] = None
    
    # Wynik
    nip: Optional[str] = Field(None, description="Znaleziony NIP (10 cyfr)")
    nip_formatted: Optional[str] = Field(None, description="NIP sformatowany (XXX-XXX-XX-XX)")
    found: bool = Field(False, description="Czy NIP znaleziony")
    
    # Confidence & source
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Pewność wyniku (0-1)")
    source: Optional[SearchSource] = Field(None, description="Źródło znalezienia")
    strategy_used: Optional[str] = Field(None, description="Strategia która zadziałała")
    
    # Walidacja
    validation: Optional[ValidationResult] = Field(None, description="Wynik walidacji NIP")
    
    # AI reasoning
    ai_reasoning: Optional[str] = Field(None, description="Wyjaśnienie AI dlaczego wybrał ten NIP")
    
    # Metadata
    search_queries_used: List[str] = Field(default_factory=list, description="Użyte zapytania")
    urls_searched: List[str] = Field(default_factory=list, description="Przeszukane URL")
    processing_time_ms: int = Field(0, description="Czas przetwarzania (ms)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp wyszukiwania")
    
    # Errors
    errors: List[str] = Field(default_factory=list, description="Lista błędów")
    warnings: List[str] = Field(default_factory=list, description="Ostrzeżenia")
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_name": "VITA MEDICA SIEDLCE",
                "city": "Siedlce",
                "nip": "1234567890",
                "nip_formatted": "123-456-78-90",
                "found": True,
                "confidence": 0.95,
                "strategy_used": "google_search_ai",
                "validation": {
                    "valid_checksum": True,
                    "vat_active": True,
                    "validated": True
                }
            }
        }


class BatchNIPRequest(BaseModel):
    """Request do batch processing."""
    
    companies: List[NIPRequest] = Field(..., description="Lista firm do przetworzenia")
    max_concurrent: int = Field(5, ge=1, le=20, description="Maksymalna liczba równoległych zapytań")


class BatchNIPResult(BaseModel):
    """Wynik batch processing."""
    
    total: int = Field(..., description="Całkowita liczba firm")
    successful: int = Field(0, description="Liczba znalezionych NIP")
    failed: int = Field(0, description="Liczba nieudanych")
    results: List[NIPResult] = Field(default_factory=list, description="Lista wyników")
    
    # Statistics
    avg_confidence: float = Field(0.0, description="Średnia confidence")
    avg_processing_time_ms: int = Field(0, description="Średni czas przetwarzania")
    
    # Strategy breakdown
    strategy_stats: dict = Field(
        default_factory=dict,
        description="Statystyki strategii {strategy: count}"
    )


class CacheEntry(BaseModel):
    """Wpis w cache."""
    
    company_name: str
    city: Optional[str]
    nip: Optional[str]
    confidence: float
    found: bool
    created_at: datetime
    last_validated_at: Optional[datetime] = None
    validation_result: Optional[ValidationResult] = None
