"""
Apify Client - wrapper do Apify SDK.
Obsługuje Google Search i Web Scraping przez Apify Actors.
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class ApifyClient:
    """
    Wrapper dla Apify SDK.
    
    Używa:
    - Apify Google Search Actor (gotowy z Store)
    - Custom Web Scraper Actor (utworzony przez nas)
    """
    
    def __init__(self, settings: Optional[object] = None):
        """
        Args:
            settings: NIPFinderSettings (opcjonalne)
        """
        self.settings = settings
        self._client = None
        self._initialized = False
    
    def _ensure_initialized(self) -> bool:
        """Lazy initialization Apify client."""
        if self._initialized:
            return True
        
        try:
            from apify_client import ApifyClient as ApifySDKClient
            
            if not self.settings or not self.settings.has_apify_credentials:
                logger.warning("[WARN] Brak credentials Apify - uzywam mock mode")
                return False
            
            self._client = ApifySDKClient(self.settings.apify_api_token)
            self._initialized = True
            
            logger.info("[OK] Apify client zainicjalizowany, type=%s", type(self._client).__name__)
            return True
            
        except ImportError:
            logger.error("[ERROR] Brak biblioteki apify-client - zainstaluj: pip install apify-client")
            return False
        except Exception as e:
            logger.error("[ERROR] Blad inicjalizacji Apify: %s", e)
            return False
    
    async def google_search(
        self,
        queries: List[str],
        max_results_per_query: int = 20,
    ) -> List[str]:
        """
        Wykonuje Google Search przez Apify Actor.
        
        Args:
            queries: Lista zapytań do Google
            max_results_per_query: Max wyników per query (domyślnie 20)
        
        Returns:
            Lista URL znalezionych stron
        """
        if not self._ensure_initialized():
            logger.warning("[WARN] Apify niedostepne - zwracam puste wyniki")
            return []
        
        try:
            logger.info("[GOOGLE] Google Search przez Apify: %d queries, client_type=%s", 
                       len(queries), type(self._client).__name__)
            
            # Przygotuj input dla Actora
            # Dokumentacja: https://apify.com/apify/google-search-scraper
            run_input = {
                "queries": "\n".join(queries),  # Jedna linia per query
                "maxPagesPerQuery": 1,  # Tylko pierwsza strona wyników
                "resultsPerPage": max_results_per_query,
                "countryCode": "pl",
                "languageCode": "pl",
                "mobileResults": False,
                "includeUnfilteredResults": False,
            }
            
            # Uruchom Actor
            logger.info("[RUN] Uruchamiam Google Search Actor: %s", self.settings.apify_google_actor_id)
            run = self._client.actor(self.settings.apify_google_actor_id).call(
                run_input=run_input,
                timeout_secs=self.settings.apify_actor_timeout_sec if self.settings else 300,
            )
            
            if run.get("status") != "SUCCEEDED":
                logger.error("[ERROR] Actor failed: %s", run.get("status"))
                return []
            
            # Pobierz wyniki
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                logger.error("[ERROR] Brak dataset ID")
                return []
            
            items = list(self._client.dataset(dataset_id).iterate_items())
            
            # Wyciagnij URL z wynikow
            urls = []
            for item in items:
                # Organic results
                organic_results = item.get("organicResults", [])
                for result in organic_results:
                    url = result.get("url")
                    if url and url.startswith("http"):
                        urls.append(url)
            
            logger.info("[OK] Google Search zwrocil %d URL", len(urls))
            return urls
            
        except Exception as e:
            logger.error("[ERROR] Blad Google Search przez Apify: %s (client_type=%s)", 
                        e, type(self._client).__name__ if self._client else "None")
            return []
    
    async def scrape_urls(
        self,
        urls: List[str],
    ) -> List[dict]:
        """
        Scrapuje URL używając custom Web Scraper Actor.
        
        Args:
            urls: Lista URL do scrapowania
        
        Returns:
            Lista dict z {'url': ..., 'text': ..., 'success': bool}
        """
        if not self._ensure_initialized():
            logger.warning("[WARN] Apify niedostępne - używam fallback scraping")
            return await self._scrape_urls_fallback(urls)
        
        # Sprawdź czy mamy Custom Actor
        if not self.settings or not self.settings.apify_scraper_actor_id:
            logger.warning("[WARN] Brak Custom Scraper Actor - używam fallback")
            return await self._scrape_urls_fallback(urls)
        
        try:
            logger.info("[SCRAPE] Scraping przez Apify: %d URL", len(urls))
            
            # Przygotuj input dla Actora
            run_input = {
                "urls": urls,
                "maxTextLength": 10000,  # Max 10k znaków per strona
            }
            
            # Uruchom Actor
            logger.info("[RUN] Uruchamiam Web Scraper Actor...")
            run = self._client.actor(self.settings.apify_scraper_actor_id).call(
                run_input=run_input,
                timeout_secs=self.settings.apify_actor_timeout_sec if self.settings else 300,
            )
            
            if run.get("status") != "SUCCEEDED":
                logger.error("[ERROR] Actor failed: %s", run.get("status"))
                return await self._scrape_urls_fallback(urls)
            
            # Pobierz wyniki
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                logger.error("[ERROR] Brak dataset ID")
                return await self._scrape_urls_fallback(urls)
            
            items = list(self._client.dataset(dataset_id).iterate_items())
            
            logger.info("[OK] Scraping zwrócił %d stron", len(items))
            return items
            
        except Exception as e:
            logger.error("[ERROR] Błąd scrapingu przez Apify: %s", e)
            return await self._scrape_urls_fallback(urls)
    
    async def _scrape_urls_fallback(self, urls: List[str]) -> List[dict]:
        """
        Fallback scraping bez Apify - używa httpx + BeautifulSoup.
        Mniej niezawodne (brak proxy, łatwiej zablokować), ale działa bez Apify.
        """
        try:
            import httpx
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("[ERROR] Brak httpx lub beautifulsoup4 - scraping niemożliwy")
            return []
        
        logger.info("[FIX] Fallback scraping (bez Apify): %d URL", len(urls))
        
        results = []
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for url in urls:
                try:
                    logger.debug("Scraping: %s", url)
                    
                    response = await client.get(
                        url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Accept": "text/html,application/xhtml+xml",
                            "Accept-Language": "pl,en;q=0.9",
                        }
                    )
                    
                    if response.status_code != 200:
                        logger.warning("[WARN] HTTP %d: %s", response.status_code, url)
                        results.append({
                            "url": url,
                            "text": "",
                            "success": False,
                            "error": f"HTTP {response.status_code}"
                        })
                        continue
                    
                    # Parsuj HTML
                    soup = BeautifulSoup(response.text, "lxml")
                    
                    # Usuń niepotrzebne elementy
                    for tag in soup(["script", "style", "nav", "header", "aside"]):
                        tag.decompose()
                    
                    # Priorytet: footer (często NIP w stopce)
                    footer = soup.find("footer")
                    if footer:
                        text = footer.get_text(separator=" ", strip=True)
                    else:
                        # Cała strona
                        text = soup.get_text(separator=" ", strip=True)
                    
                    # Truncate do 10k znaków
                    text = text[:10000]
                    
                    results.append({
                        "url": url,
                        "text": text,
                        "success": True,
                    })
                    
                    logger.debug("[OK] Scraped %d chars from %s", len(text), url)
                    
                except Exception as e:
                    logger.warning("[WARN] Błąd scraping %s: %s", url, str(e)[:50])
                    results.append({
                        "url": url,
                        "text": "",
                        "success": False,
                        "error": str(e)[:100]
                    })
        
        successful = sum(1 for r in results if r.get("success"))
        logger.info("[OK] Fallback scraping: %d/%d udanych", successful, len(urls))
        
        return results
    
    async def close(self):
        """Zamknij klienta (placeholder - Apify SDK nie wymaga zamykania)."""
        pass
