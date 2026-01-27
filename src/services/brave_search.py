"""
Serwis Brave Search API - wyszukiwanie NIP i informacji o firmach.
"""

import logging
import re
from typing import Optional

import httpx

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)


class BraveSearchService:
    """
    Klient Brave Search API do wyszukiwania informacji o firmach.
    - Szuka NIP po nazwie firmy
    - Zbiera informacje o placówce
    """
    
    BASE_URL = "https://api.search.brave.com/res/v1/web/search"
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None
    
    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    def _get_headers(self) -> dict:
        """Nagłówki do Brave API."""
        return {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.settings.brave_search_api_key,
        }
    
    async def search(self, query: str, count: int = 10) -> list[dict]:
        """
        Wykonuje wyszukiwanie w Brave.
        
        Args:
            query: Zapytanie wyszukiwania
            count: Liczba wyników (max 20)
        
        Returns:
            Lista wyników wyszukiwania
        """
        if not self.settings.brave_search_api_key:
            logger.warning("Brak BRAVE_SEARCH_API_KEY - wyszukiwanie niedostępne")
            return []
        
        try:
            params = {
                "q": query,
                "count": min(count, 20),
                "country": "pl",
                "search_lang": "pl",
                "safesearch": "off",
            }
            
            response = await self.http_client.get(
                self.BASE_URL,
                params=params,
                headers=self._get_headers(),
            )
            
            if response.status_code == 429:
                logger.warning("Brave Search: limit zapytań przekroczony")
                return []
            
            response.raise_for_status()
            data = response.json()
            
            # Wyciągnij wyniki
            web_results = data.get("web", {}).get("results", [])
            return web_results
            
        except httpx.HTTPStatusError as e:
            logger.error("Brave Search HTTP error: %s", e)
            return []
        except Exception as e:
            logger.error("Brave Search error: %s", e)
            return []
    
    async def find_nip(self, company_name: str) -> Optional[str]:
        """
        Szuka NIP firmy po nazwie.
        
        Args:
            company_name: Nazwa firmy
        
        Returns:
            NIP (10 cyfr) lub None
        """
        if not company_name:
            return None
        
        # Zapytanie zoptymalizowane pod szukanie NIP
        query = f'"{company_name}" NIP'
        
        results = await self.search(query, count=10)
        
        # Szukaj NIP w wynikach
        nip_pattern = re.compile(r'\b(\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2})\b')
        nip_pattern_plain = re.compile(r'\b(\d{10})\b')
        
        found_nips = []
        
        for result in results:
            # Szukaj w title i description
            text = f"{result.get('title', '')} {result.get('description', '')}"
            
            # Szukaj formatu XXX-XXX-XX-XX lub XXX XXX XX XX
            matches = nip_pattern.findall(text)
            for match in matches:
                # Usuń separatory
                nip = re.sub(r'[-\s]', '', match)
                if self._validate_nip(nip):
                    found_nips.append(nip)
            
            # Szukaj formatu 10 cyfr bez separatorów
            matches_plain = nip_pattern_plain.findall(text)
            for nip in matches_plain:
                if self._validate_nip(nip):
                    found_nips.append(nip)
        
        if found_nips:
            # Zwróć najczęściej występujący NIP
            from collections import Counter
            nip_counts = Counter(found_nips)
            best_nip = nip_counts.most_common(1)[0][0]
            logger.info("Znaleziono NIP dla '%s': %s", company_name, best_nip)
            return best_nip
        
        logger.info("Nie znaleziono NIP dla '%s'", company_name)
        return None
    
    def _validate_nip(self, nip: str) -> bool:
        """Waliduje NIP checksum."""
        if not nip or len(nip) != 10 or not nip.isdigit():
            return False
        
        # Wagi dla checksum
        weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]
        
        checksum = sum(int(nip[i]) * weights[i] for i in range(9)) % 11
        
        # Checksum nie może być 10
        if checksum == 10:
            return False
        
        return checksum == int(nip[9])
    
    async def get_company_info(self, company_name: str) -> dict:
        """
        Zbiera informacje o firmie z internetu.
        
        Args:
            company_name: Nazwa firmy
        
        Returns:
            Słownik z informacjami o firmie
        """
        if not company_name:
            return {}
        
        # Różne zapytania żeby zebrać różne informacje
        queries = [
            f'"{company_name}" placówka medyczna',
            f'"{company_name}" przychodnia kontakt adres',
        ]
        
        info = {
            "sources": [],
            "snippets": [],
            "urls": [],
        }
        
        for query in queries:
            results = await self.search(query, count=5)
            
            for result in results:
                url = result.get("url", "")
                title = result.get("title", "")
                description = result.get("description", "")
                
                if url and url not in info["urls"]:
                    info["urls"].append(url)
                    info["sources"].append({
                        "url": url,
                        "title": title,
                        "snippet": description,
                    })
                    info["snippets"].append(description)
        
        return info
    
    async def enrich_company(self, company_name: str, address: Optional[str] = None) -> dict:
        """
        Wzbogaca dane o firmie - szuka w internecie i klasyfikuje.
        
        Args:
            company_name: Nazwa firmy
            address: Opcjonalny adres do weryfikacji
        
        Returns:
            Dict z danymi do Zoho CRM (Industry, Specjalizacja, Platnik_uslug, Adres_w_rekordzie)
        """
        if not company_name:
            return {}
        
        # Zbierz informacje z internetu
        info = await self.get_company_info(company_name)
        nip = await self.find_nip(company_name)
        
        # Połącz snippety w tekst do analizy (krótsze, bez polskich znaków problematycznych)
        snippets = info.get("snippets", [])[:5]  # Max 5 snippetów
        snippets_text = "\n".join(s[:300] for s in snippets)[:1500]  # Max 1500 znaków
        
        return {
            "company_name": company_name,
            "nip": nip,
            "web_snippets": snippets_text,
            "sources": info.get("sources", [])[:5],
            "address": address,
        }
    
    async def close(self):
        """Zamyka klienta HTTP."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# Singleton
_brave_search_service: Optional[BraveSearchService] = None


def get_brave_search_service(settings: Optional[Settings] = None) -> BraveSearchService:
    """Zwraca singleton serwisu Brave Search."""
    global _brave_search_service
    if _brave_search_service is None:
        _brave_search_service = BraveSearchService(settings)
    return _brave_search_service
