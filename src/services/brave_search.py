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
        
        import asyncio
        
        # Jedno zapytanie żeby nie przekroczyć rate limit (1 req/s)
        query = f'"{company_name}" placówka medyczna przychodnia'
        
        info = {
            "sources": [],
            "snippets": [],
            "urls": [],
        }
        
        results = await self.search(query, count=10)
        
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
        
        import asyncio
        
        # Zbierz informacje z internetu (z opóźnieniem między zapytaniami - rate limit 1/s)
        info = await self.get_company_info(company_name)
        await asyncio.sleep(1.5)  # Opóźnienie przed następnym zapytaniem
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
    
    async def find_organization_locations(self, nip: str) -> dict:
        """
        Szuka wszystkich placówek/filii należących do organizacji o podanym NIP.
        
        Mechanizm:
        1. Szuka informacji o firmie po NIP (nazwa, siedziba)
        2. Szuka "nazwa firmy" + "placówki/filie/oddziały"
        3. Szuka strony z listą placówek
        4. Zwraca surowe dane do przetworzenia przez AI
        
        Args:
            nip: NIP organizacji (10 cyfr)
        
        Returns:
            Dict z zebranymi danymi o placówkach
        """
        import asyncio
        
        if not nip or len(nip) != 10:
            return {"error": "Nieprawidłowy NIP"}
        
        result = {
            "nip": nip,
            "company_name": None,
            "headquarters": None,
            "locations_data": [],
            "sources": [],
            "raw_snippets": [],
        }
        
        # Krok 1: Znajdź nazwę firmy po NIP
        query1 = f"NIP {nip}"
        search1 = await self.search(query1, count=5)
        
        company_name = None
        for r in search1:
            title = r.get("title", "")
            desc = r.get("description", "")
            # Szukaj nazwy firmy w tytule (często format "NAZWA FIRMY - dane...")
            if "sp. z o.o" in title.lower() or "spółka" in title.lower():
                # Wytnij nazwę przed przecinkiem lub myślnikiem
                name_match = re.match(r'^([^,\-–|]+)', title)
                if name_match:
                    company_name = name_match.group(1).strip()
                    break
            # Szukaj w description
            if not company_name and nip in desc:
                # Szukaj wzorca "NAZWA ... NIP"
                name_match = re.search(r'([A-ZŻŹĆĄŚĘŁÓŃ][A-ZŻŹĆĄŚĘŁÓŃa-ząćęłńóśźż\s\.\-]+(?:sp\.?\s*z\s*o\.?o\.?|S\.A\.|spółka))', desc, re.IGNORECASE)
                if name_match:
                    company_name = name_match.group(1).strip()
                    break
        
        if not company_name and search1:
            # Fallback: weź pierwszy tytuł
            company_name = search1[0].get("title", "").split(" - ")[0].split(" | ")[0].strip()
        
        result["company_name"] = company_name
        result["sources"].extend([r.get("url") for r in search1 if r.get("url")])
        
        if not company_name:
            return result
        
        await asyncio.sleep(1.5)  # Rate limit
        
        # Krok 2: Szukaj placówek po nazwie firmy
        query2 = f'"{company_name}" placówki filie oddziały adresy'
        search2 = await self.search(query2, count=10)
        
        for r in search2:
            result["raw_snippets"].append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
            })
            if r.get("url") and r.get("url") not in result["sources"]:
                result["sources"].append(r.get("url"))
        
        await asyncio.sleep(1.5)  # Rate limit
        
        # Krok 3: Szukaj strony grupy/sieci z listą placówek
        # Wyciągnij krótką nazwę (bez "sp. z o.o." itp.)
        short_name = re.sub(r'\s*(sp\.?\s*z\.?\s*o\.?o\.?|spółka.*|s\.a\.).*', '', company_name, flags=re.IGNORECASE).strip()
        query3 = f'"{short_name}" placówki lista wszystkie adresy'
        search3 = await self.search(query3, count=10)
        
        for r in search3:
            url = r.get("url", "")
            # Priorytetyzuj strony z /placowki, /kontakt, /lokalizacje w URL
            if any(kw in url.lower() for kw in ["/placowki", "/lokalizacje", "/oddzialy", "/kontakt", "/gdzie-nas-znajdziesz"]):
                result["locations_data"].append({
                    "url": url,
                    "title": r.get("title", ""),
                    "snippet": r.get("description", ""),
                    "priority": "high",
                })
            else:
                result["raw_snippets"].append({
                    "title": r.get("title", ""),
                    "url": url,
                    "snippet": r.get("description", ""),
                })
            
            if url and url not in result["sources"]:
                result["sources"].append(url)
        
        await asyncio.sleep(1.5)  # Rate limit
        
        # Krok 4: Szukaj pod domeną grupy (jeśli znaleziono URL grupy)
        group_domains = []
        for url in result["sources"]:
            if "grupa" in url.lower() or "group" in url.lower():
                # Wyciągnij domenę
                domain_match = re.search(r'https?://([^/]+)', url)
                if domain_match:
                    group_domains.append(domain_match.group(1))
        
        if group_domains:
            query4 = f'site:{group_domains[0]} placówki'
            search4 = await self.search(query4, count=10)
            
            for r in search4:
                url = r.get("url", "")
                if any(kw in url.lower() for kw in ["/placowki", "/lokalizacje", "/oddzialy", "/kontakt"]):
                    result["locations_data"].append({
                        "url": url,
                        "title": r.get("title", ""),
                        "snippet": r.get("description", ""),
                        "priority": "high",
                    })
                else:
                    result["raw_snippets"].append({
                        "title": r.get("title", ""),
                        "url": url,
                        "snippet": r.get("description", ""),
                    })
                
                if url and url not in result["sources"]:
                    result["sources"].append(url)
        
        return result
    
    async def scrape_locations_page(self, url: str) -> dict:
        """
        Scrapuje stronę z listą placówek i wyciąga tekst z adresami.
        
        Args:
            url: URL strony do scrapowania
        
        Returns:
            Dict z wyciągniętym tekstem i strukturą strony
        """
        from bs4 import BeautifulSoup
        
        result = {
            "url": url,
            "success": False,
            "text_content": "",
            "addresses_found": [],
            "error": None,
        }
        
        try:
            # Pobierz HTML
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pl,en;q=0.5",
            }
            
            response = await self.http_client.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()
            
            html = response.text
            soup = BeautifulSoup(html, "lxml")
            
            # Usuń niepotrzebne elementy
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            
            # Szukaj sekcji z placówkami/adresami
            location_keywords = ["placówk", "oddział", "fili", "lokalizacj", "adres", "kontakt", "klinik", "przychodn"]
            
            relevant_sections = []
            
            # Szukaj divów/sekcji z keywords w klasie lub id
            for element in soup.find_all(["div", "section", "article", "ul", "li"]):
                element_str = str(element.get("class", [])) + str(element.get("id", ""))
                if any(kw in element_str.lower() for kw in location_keywords):
                    text = element.get_text(separator=" ", strip=True)
                    if len(text) > 50:  # Pomiń puste
                        relevant_sections.append(text[:2000])  # Max 2000 znaków per sekcja
            
            # Szukaj adresów w całym tekście (wzorzec: ul./al. + nazwa + numer)
            full_text = soup.get_text(separator="\n", strip=True)
            
            # Wzorce adresów polskich
            address_patterns = [
                r'(?:ul\.|ulica|al\.|aleja)\s+[A-ZŻŹĆĄŚĘŁÓŃ][a-ząćęłńóśźż\w\s\-]+\s+\d+[a-zA-Z]?(?:\s*/\s*\d+)?',
                r'\d{2}-\d{3}\s+[A-ZŻŹĆĄŚĘŁÓŃ][a-ząćęłńóśźż]+',  # Kod pocztowy + miasto
            ]
            
            addresses = []
            for pattern in address_patterns:
                matches = re.findall(pattern, full_text, re.IGNORECASE)
                addresses.extend(matches)
            
            result["success"] = True
            result["text_content"] = "\n\n".join(relevant_sections[:10])[:8000]  # Max 8000 znaków
            result["addresses_found"] = list(set(addresses))[:50]  # Max 50 unikalnych
            result["full_text_sample"] = full_text[:20000]  # Sample pełnego tekstu - zwiększony do 20k
            
        except httpx.HTTPStatusError as e:
            result["error"] = f"HTTP {e.response.status_code}"
            logger.warning("Scrape HTTP error for %s: %s", url, e)
        except Exception as e:
            result["error"] = str(e)
            logger.warning("Scrape error for %s: %s", url, e)
        
        return result
    
    async def find_organization_locations_with_scraping(self, nip: str) -> dict:
        """
        Rozszerzona wersja find_organization_locations z scrapowaniem stron.
        
        1. Wyszukuje placówki przez Brave Search
        2. Scrapuje znalezione strony z priority_urls
        3. Zwraca połączone dane do analizy AI
        """
        import asyncio
        
        # Krok 1: Standardowe wyszukiwanie
        search_result = await self.find_organization_locations(nip)
        
        if search_result.get("error"):
            return search_result
        
        # Krok 2: Scrapuj priority URLs (strony z /placowki itp.)
        priority_urls = [loc["url"] for loc in search_result.get("locations_data", [])]
        
        scraped_data = []
        for url in priority_urls[:3]:  # Max 3 strony żeby nie przekroczyć limitów
            await asyncio.sleep(1)  # Rate limit
            scrape_result = await self.scrape_locations_page(url)
            if scrape_result["success"]:
                scraped_data.append(scrape_result)
        
        search_result["scraped_pages"] = scraped_data
        search_result["total_addresses_scraped"] = sum(
            len(s.get("addresses_found", [])) for s in scraped_data
        )
        
        return search_result
    
    async def find_location_details(self, postal_code: str, city: str) -> dict:
        """
        Szuka szczegółów lokalizacji (gmina, powiat, województwo) po kodzie pocztowym i mieście.
        
        Args:
            postal_code: Kod pocztowy (XX-XXX)
            city: Nazwa miasta
        
        Returns:
            Dict z gmina, powiat, województwo
        """
        if not postal_code or not city:
            return {"gmina": None, "powiat": None, "wojewodztwo": None}
        
        import re
        
        # Wyszukaj w Brave - query optymalizowane pod strukturę administracyjną
        query = f'"{postal_code}" "{city}" gmina powiat województwo polska'
        results = await self.search(query, count=5)
        
        details = {
            "gmina": None,
            "powiat": None,
            "wojewodztwo": None,
        }
        
        # Zbierz tekst z wyników
        text = ""
        for r in results:
            text += f"{r.get('title', '')} {r.get('description', '')} "
        
        # Debug: log surowego tekstu
        logger.debug("Brave search results for %s %s: %s", postal_code, city, text[:200])
        
        # Wzorce do wyciągania danych
        # GMINA: pomiń typ (miejska/wiejska/miejsko-wiejska), wyciągnij nazwę
        # WAŻNE: Nazwy gmin mogą mieć spacje (Nowy Sącz, Zielona Góra)
        gmina_patterns = [
            # "gmina miejska Warszawa" -> "Warszawa"
            r'gmin[aąe]\s+miejsk[aoąę]\s+([A-ZŻŹĆĄŚĘŁÓŃ][a-ząćęłńóśźż\-\s]+?)(?:\s*[,\.]|\s+w\s+|\s+\(|\s+powiat)',
            # "gmina wiejska Kędzierzyn-Koźle" -> "Kędzierzyn-Koźle"
            r'gmin[aąe]\s+wiejsk[aoąę]\s+([A-ZŻŹĆĄŚĘŁÓŃ][a-ząćęłńóśźż\-\s]+?)(?:\s*[,\.]|\s+w\s+|\s+\(|\s+powiat)',
            # "gmina miejsko-wiejska Lębork" -> "Lębork"
            r'gmin[aąe]\s+miejsko[\-\s]?wiejsk[aoąę]\s+([A-ZŻŹĆĄŚĘŁÓŃ][a-ząćęłńóśźż\-\s]+?)(?:\s*[,\.]|\s+w\s+|\s+\(|\s+powiat)',
            # "Gmina Nowy Sącz" (bez typu, z spacjami w nazwie)
            r'gmin[aąe]\s+([A-ZŻŹĆĄŚĘŁÓŃ][a-ząćęłńóśźż\-\s]+?)(?:\s*[,\.]|\s+powiat|\s+woj)',
        ]
        
        for pattern in gmina_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                # Filtruj słowa kluczowe które nie są nazwą gminy
                if value.lower() not in ['wiejska', 'miejska', 'miejsko', 'wiejska']:
                    details["gmina"] = " ".join(word.capitalize() for word in value.split())
                    break
        
        # POWIAT: wyciągnij nazwę powiatu (często z końcówką -ski/-cki)
        powiat_patterns = [
            # "powiat kędzierzyńsko-kozielski" -> "Kędzierzyńsko-kozielski"
            r'powiat\s+([a-ząćęłńóśźż]+(?:[\-\s][a-ząćęłńóśźż]+)?[sc]ki)(?:\s*[,\.]|\s+w\s+|\s|$)',
            # "powiat nowosądecki"
            r'powiat\s+([a-ząćęłńóśźż\-]+)',
        ]
        
        for pattern in powiat_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                details["powiat"] = " ".join(word.capitalize() for word in value.split())
                break
        
        # WOJEWÓDZTWO: pełna nazwa województwa (małymi literami)
        wojewodztwo_patterns = [
            # "województwo małopolskie" - dopasuj 1-2 słowa, zatrzymaj się na przecinku/kropce/spacji przed kolejnym słowem kluczowym
            r'wojew[oó]dztw[oae]\s+([a-ząćęłńóśźż]+(?:[\-][a-ząćęłńóśźż]+)?)(?:\s*[,\.\s]|$)',
        ]
        
        for pattern in wojewodztwo_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                # Filtruj niepoprawne wartości (zbyt długie, zawierające słowa kluczowe)
                if len(value) <= 30 and not any(kw in value.lower() for kw in ['gmina', 'powiat', 'mapie']):
                    # Województwa MAŁYMI literami
                    details["wojewodztwo"] = value.lower()
                    break
        
        logger.info(
            "Location details for %s %s: gmina=%s, powiat=%s, woj=%s",
            postal_code,
            city,
            details["gmina"],
            details["powiat"],
            details["wojewodztwo"],
        )
        
        return details
    
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
