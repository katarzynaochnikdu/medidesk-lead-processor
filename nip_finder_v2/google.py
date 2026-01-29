"""
Google Snippet Mining - wyciaganie NIP z wynikow wyszukiwania Google.

Kluczowa roznica od v1: NIE wchodzimy na strony!
Pobieramy tylko tytuly i opisy z wynikow Google.
To omija Cloudflare, CAPTCHe i inne zabezpieczenia.
"""

import logging
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from .config import get_settings, NIPFinderV2Settings
from .utils import extract_nips_from_text, is_valid_nip, normalize_company_name

logger = logging.getLogger(__name__)


@dataclass
class SnippetResult:
    """Wynik z Google Snippet."""
    nip: str
    source_url: str
    snippet: str
    confidence: float


class GoogleMining:
    """
    Wyciaga NIP z wynikow wyszukiwania Google (snippets).
    
    NIE wchodzi na strony docelowe - tylko analizuje to,
    co Google pokazuje w wynikach wyszukiwania.
    """
    
    # Domeny wysokiej jakosci - jesli NIP pochodzi z nich, mamy wysoka pewnosc
    HIGH_QUALITY_DOMAINS = [
        "krs-online.com",
        "krs-pobierz.pl",
        "bizraport.pl",
        "rejestr.io",
        "aleo.com",
        "infoveriti.pl",
        "okredo.com",
        "panoramafirm.pl",
        "regon.stat.gov.pl",
    ]
    
    def __init__(self, settings: Optional[NIPFinderV2Settings] = None):
        self.settings = settings or get_settings()
        self._apify_client = None
    
    def _get_apify_client(self):
        """Lazy init Apify client."""
        if self._apify_client is None:
            from apify_client import ApifyClient
            self._apify_client = ApifyClient(self.settings.apify_api_token)
        return self._apify_client
    
    def _generate_queries(self, company_name: str, city: Optional[str] = None) -> List[str]:
        """Generuje zapytania do Google."""
        clean_name = normalize_company_name(company_name)
        
        queries = []
        
        # Query 1: Nazwa + NIP
        if city:
            queries.append(f'"{clean_name}" "{city}" NIP')
        else:
            queries.append(f'"{clean_name}" NIP')
        
        # Query 2: Nazwa + KRS (KRS zawiera NIP)
        queries.append(f'"{clean_name}" KRS')
        
        # Query 3: Pelna nazwa z forma prawna
        queries.append(f'"{company_name}" NIP')
        
        return queries[:3]  # Max 3 queries
    
    def _is_high_quality_source(self, url: str) -> bool:
        """Sprawdza czy URL pochodzi z zaufanego zrodla."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.HIGH_QUALITY_DOMAINS)
    
    async def search_snippets(
        self,
        company_name: str,
        city: Optional[str] = None,
    ) -> Optional[SnippetResult]:
        """
        Szuka NIP w snippetach Google.
        
        Args:
            company_name: Nazwa firmy
            city: Miasto (opcjonalne)
        
        Returns:
            SnippetResult jesli znaleziono NIP, None w przeciwnym razie
        """
        if not self.settings.has_apify_credentials:
            logger.warning("[GOOGLE] Brak klucza Apify - pomijam")
            return None
        
        queries = self._generate_queries(company_name, city)
        logger.info("[GOOGLE] Szukam snippetow dla: %s (queries=%d)", company_name, len(queries))
        
        try:
            client = self._get_apify_client()
            
            # Przygotuj input dla Google Search Actor
            run_input = {
                "queries": "\n".join(queries),
                "maxPagesPerQuery": 1,
                "resultsPerPage": 10,
                "countryCode": "pl",
                "languageCode": "pl",
                "mobileResults": False,
            }
            
            # Uruchom Actor
            logger.info("[GOOGLE] Uruchamiam Google Search Actor...")
            run = client.actor(self.settings.apify_google_actor_id).call(
                run_input=run_input,
                timeout_secs=self.settings.google_timeout_sec,
            )
            
            if run.get("status") != "SUCCEEDED":
                logger.error("[GOOGLE] Actor failed: %s", run.get("status"))
                return None
            
            # Pobierz wyniki
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                logger.error("[GOOGLE] Brak dataset ID")
                return None
            
            items = list(client.dataset(dataset_id).iterate_items())
            logger.info("[GOOGLE] Otrzymano %d wynikow", len(items))
            
            # Analizuj snippety
            best_result = None
            best_confidence = 0.0
            
            for item in items:
                organic_results = item.get("organicResults", [])
                
                for result in organic_results:
                    url = result.get("url", "")
                    title = result.get("title", "")
                    description = result.get("description", "")
                    
                    # Polacz tytul i opis
                    snippet_text = f"{title} {description}"
                    
                    # Szukaj NIPow
                    nips = extract_nips_from_text(snippet_text)
                    
                    if nips:
                        # Okresl confidence
                        is_high_quality = self._is_high_quality_source(url)
                        confidence = 0.95 if is_high_quality else 0.7
                        
                        logger.info(
                            "[GOOGLE] Znaleziono NIP w snippet: %s (url=%s, confidence=%.2f)",
                            nips[0], url[:50], confidence
                        )
                        
                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_result = SnippetResult(
                                nip=nips[0],
                                source_url=url,
                                snippet=snippet_text[:200],
                                confidence=confidence,
                            )
            
            if best_result:
                logger.info(
                    "[GOOGLE] Najlepszy wynik: NIP=%s, confidence=%.2f",
                    best_result.nip, best_result.confidence
                )
                return best_result
            
            logger.info("[GOOGLE] Nie znaleziono NIP w snippetach")
            return None
            
        except Exception as e:
            logger.error("[GOOGLE] Blad wyszukiwania: %s", e)
            return None
    
    async def close(self):
        """Zamyka klienta."""
        self._apify_client = None
