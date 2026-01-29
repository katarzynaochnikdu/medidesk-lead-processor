"""
Modele danych dla NIP Finder v2.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class SearchStrategy(Enum):
    """Strategia ktora znalazla NIP."""
    GUS = "gus"
    GOOGLE_SNIPPET = "google_snippet"
    HOMEPAGE = "homepage"
    CACHE = "cache"


@dataclass
class NIPResultV2:
    """Wynik wyszukiwania NIP."""
    company_name: str
    city: Optional[str] = None
    
    # Wynik
    found: bool = False
    nip: Optional[str] = None
    nip_formatted: Optional[str] = None
    confidence: float = 0.0
    
    # Zrodlo
    strategy: Optional[SearchStrategy] = None
    source_url: Optional[str] = None
    source_snippet: Optional[str] = None
    
    # Dodatkowe dane z GUS
    gus_name: Optional[str] = None
    gus_regon: Optional[str] = None
    gus_city: Optional[str] = None
    
    # Statystyki
    processing_time_ms: int = 0
    errors: List[str] = field(default_factory=list)
    
    def format_nip(self, nip: str) -> str:
        """Formatuje NIP do XXX-XXX-XX-XX."""
        if len(nip) != 10:
            return nip
        return f"{nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:10]}"
