"""
NIP Finder v2 - Zero-Click & Official Source Strategy

Priorytetowe zrodla:
1. GUS API (wyszukiwanie po nazwie)
2. Google Snippets (NIP z wynikow wyszukiwania, bez wchodzenia na strony)
3. Homepage scraper (ostatecznosc - tylko strona glowna firmy)
"""

from .orchestrator import NIPFinderV2
from .models import NIPResultV2, SearchStrategy

__all__ = ["NIPFinderV2", "NIPResultV2", "SearchStrategy"]
__version__ = "2.0.0"
