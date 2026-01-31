"""
Google Maps Scraper - pobieranie danych z Google Maps przez Apify.

Zbiera:
- Lokalizacje/placówki firmy
- Recenzje i rating
- Godziny otwarcia
- Kontakty
"""

import asyncio
from typing import Optional

from .base import BaseScraper, ScraperResult
from ..models import Placowka, Adres, Kontakt, TypAdresu


class GoogleMapsScraper(BaseScraper):
    """
    Google Maps Scraper używający Apify Actor.
    
    Actor: compass/crawler-google-places
    Docs: https://apify.com/compass/crawler-google-places
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apify_client = None
        self._initialized = False
    
    def _init_apify(self) -> bool:
        """Lazy initialization Apify client."""
        if self._initialized:
            return self._apify_client is not None
        
        try:
            from apify_client import ApifyClient
            
            if not self.settings.has_apify_credentials:
                self.logger.warning("Brak Apify credentials - tryb offline")
                self._initialized = True
                return False
            
            self._apify_client = ApifyClient(self.settings.apify_api_token)
            self._initialized = True
            self.logger.info("Apify client initialized for Google Maps")
            return True
            
        except ImportError:
            self.logger.error("Brak apify-client - zainstaluj: pip install apify-client")
            self._initialized = True
            return False
        except Exception as e:
            self.logger.error("Apify init error: %s", e)
            self._initialized = True
            return False
    
    async def _execute(
        self,
        company_name: str,
        city: Optional[str] = None,
        max_places: int = 5,
        website: Optional[str] = None,
    ) -> ScraperResult:
        """
        Wyszukuje firmę w Google Maps.
        
        Args:
            company_name: Nazwa firmy
            city: Miasto (opcjonalne, zwiększa precyzję)
            max_places: Max miejsc do pobrania
            website: URL strony WWW firmy (do filtrowania wyników)
        
        Returns:
            ScraperResult z listą Placowka
        """
        self.logger.info("Searching Google Maps: '%s' in '%s'", company_name, city or "Poland")
        
        if not self._init_apify():
            return ScraperResult(
                success=False,
                error="Apify client not available",
                data={"placowki": []},
            )
        
        # Przygotuj query
        search_query = company_name
        if city:
            search_query = f"{company_name} {city}"
        
        # Input dla Actora
        run_input = {
            "searchStringsArray": [search_query],
            "locationQuery": city or "Polska",
            "maxCrawledPlacesPerSearch": max_places,
            "language": "pl",
            "deeperCityScrape": False,
            "onePerGooglePlacesRequest": True,
            # Opcje danych
            "includeReviews": True,  # Pobieraj recenzje dla insights
            "maxReviews": 50,  # Max 50 najnowszych recenzji
            "includeImages": False,
            "includePeopleAlsoSearch": False,
            "includeWebResults": False,
        }
        
        self.logger.debug("Apify input: %s", run_input)
        
        try:
            # Uruchom Actor (sync call w thread pool)
            run = await asyncio.to_thread(
                lambda: self._apify_client.actor(
                    self.settings.apify_google_maps_actor_id
                ).call(
                    run_input=run_input,
                    timeout_secs=self.settings.apify_actor_timeout_sec,
                )
            )
            
            if run.get("status") != "SUCCEEDED":
                self.logger.error("Actor failed: %s", run.get("status"))
                return ScraperResult(
                    success=False,
                    error=f"Actor failed: {run.get('status')}",
                    data={"placowki": []},
                    raw_response=run,
                )
            
            # Pobierz wyniki
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                return ScraperResult(
                    success=False,
                    error="No dataset ID in response",
                    data={"placowki": []},
                )
            
            items = await asyncio.to_thread(
                lambda: list(self._apify_client.dataset(dataset_id).iterate_items())
            )
            
            self.logger.info("Google Maps returned %d places", len(items))
            
            # Filtruj po website URL jeśli podane (PRZED parsowaniem - na raw items)
            if website:
                website_domain = self._extract_domain(website)
                filtered_items = []
                for item in items:
                    item_website = item.get("website", "")
                    if item_website:
                        item_domain = self._extract_domain(item_website)
                        if website_domain and item_domain and website_domain == item_domain:
                            filtered_items.append(item)
                            self.logger.debug(
                                "Place matches website: %s", item.get("title")
                            )
                
                if filtered_items:
                    self.logger.info(
                        "Filtered %d/%d places matching website '%s'",
                        len(filtered_items), len(items), website_domain
                    )
                    items = filtered_items
                else:
                    self.logger.warning(
                        "No places match website '%s' - keeping all %d",
                        website_domain, len(items)
                    )
            
            # Konwertuj do Placowka
            placowki = []
            # Słownik: place_id -> reviews_data
            all_reviews = {}
            
            for item in items:
                result = self._parse_place(item)
                if result:
                    placowka, reviews_data = result
                    placowki.append(placowka)
                    if reviews_data and placowka.google_maps_place_id:
                        all_reviews[placowka.google_maps_place_id] = reviews_data
            
            # Filtruj po mieście jeśli podane
            if city and placowki:
                city_lower = city.lower()
                filtered = []
                for p in placowki:
                    if p.adres and p.adres.miasto:
                        place_city = p.adres.miasto.lower()
                        # Sprawdź czy miasto pasuje (fuzzy)
                        if city_lower in place_city or place_city in city_lower:
                            filtered.append(p)
                
                if filtered:
                    self.logger.info(
                        "Filtered %d/%d places matching city '%s'",
                        len(filtered), len(placowki), city
                    )
                    placowki = filtered
                else:
                    self.logger.warning(
                        "No places match city '%s' - keeping all %d",
                        city, len(placowki)
                    )
            
            # Oszacuj koszt (pay per event + reviews)
            cost = len(items) * 0.003  # ~$0.003 per place
            if all_reviews:
                cost += len(all_reviews) * 0.001  # +$0.001 per place with reviews
            
            return ScraperResult(
                success=True,
                data={
                    "placowki": placowki,
                    "reviews": all_reviews,  # place_id -> reviews_data
                    "raw_items": items,
                    "count": len(placowki),
                },
                cost_usd=cost,
                raw_response=run,
            )
            
        except Exception as e:
            self.logger.exception("Google Maps scraping failed: %s", e)
            return ScraperResult(
                success=False,
                error=str(e),
                data={"placowki": []},
            )
    
    def _parse_place(self, item: dict) -> Optional[Placowka]:
        """Parsuje pojedyncze miejsce z Google Maps do Placowka."""
        try:
            # Adres
            adres = Adres(
                ulica=item.get("street"),
                kod=item.get("postalCode"),
                miasto=item.get("city"),
                wojewodztwo=item.get("state"),
            )
            
            # Kontakty
            kontakty = []
            
            phone = item.get("phone") or item.get("phoneUnformatted")
            if phone and self._is_valid_phone(phone):
                formatted_phone = self._format_phone(phone)
                kontakty.append(Kontakt(
                    typ="telefon",
                    wartosc=formatted_phone,
                    opis="Google Maps"
                ))
            
            # Godziny otwarcia - wszystkie dni tygodnia
            godziny = None
            opening_hours = item.get("openingHours")
            if opening_hours and isinstance(opening_hours, list):
                # Format: [{"day": "piątek", "hours": "9:00 to 17:00"}, ...]
                godziny_parts = []
                for oh in opening_hours:  # Wszystkie dni
                    day = oh.get("day", "")
                    hours = oh.get("hours", "")
                    if day and hours:
                        # Skróć nazwę dnia do 3 liter
                        day_short = day[:3] if len(day) > 3 else day
                        godziny_parts.append(f"{day_short}: {hours}")
                if godziny_parts:
                    godziny = "; ".join(godziny_parts)
            
            # Współrzędne GPS
            coordinates = None
            location = item.get("location")
            if location and isinstance(location, dict):
                lat = location.get("lat")
                lng = location.get("lng")
                if lat is not None and lng is not None:
                    from ..models import Coordinates
                    coordinates = Coordinates(lat=float(lat), lng=float(lng))
            
            # Wyciągnij recenzje (jeśli są)
            reviews_data = item.get("reviews", [])
            
            placowka = Placowka(
                typ_adresu=TypAdresu.NONE,  # Określimy później
                adres=adres,
                kontakty=kontakty,
                godziny_otwarcia=godziny,
                coordinates=coordinates,
                google_maps_place_id=item.get("placeId"),
                google_rating=item.get("totalScore"),
                google_reviews_count=item.get("reviewsCount"),
            )
            
            self.logger.debug(
                "Parsed place: %s, rating=%.1f, reviews=%d, reviews_data=%d",
                item.get("title"),
                placowka.google_rating or 0,
                placowka.google_reviews_count or 0,
                len(reviews_data),
            )
            
            return placowka, reviews_data
            
        except Exception as e:
            self.logger.warning("Failed to parse place: %s", e)
            return None
    
    def _format_phone(self, phone: str) -> str:
        """Formatuje numer telefonu do standardowego formatu: +48 XXX XXX XXX"""
        import re
        
        # Wyciągnij tylko cyfry
        digits = re.sub(r'\D', '', phone)
        
        # Usuń kierunkowy kraju jeśli jest
        if digits.startswith('48') and len(digits) > 9:
            digits = digits[2:]
        elif digits.startswith('0'):
            digits = digits[1:]
        
        # Weź ostatnie 9 cyfr
        if len(digits) > 9:
            digits = digits[-9:]
        
        # Formatuj jako +48 XXX XXX XXX
        if len(digits) == 9:
            return f"+48 {digits[:3]} {digits[3:6]} {digits[6:9]}"
        else:
            return f"+48 {digits}"
    
    def _extract_domain(self, url: str) -> Optional[str]:
        """Wyciąga domenę z URL (bez www.)."""
        if not url:
            return None
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url if url.startswith("http") else f"http://{url}")
            domain = parsed.netloc.lower()
            # Usuń www.
            if domain.startswith("www."):
                domain = domain[4:]
            return domain or None
        except Exception:
            return None
    
    def _is_valid_phone(self, phone: str) -> bool:
        """
        Sprawdza czy numer telefonu jest prawdziwy, nie placeholder.
        """
        import re
        
        # Wyciągnij tylko cyfry
        digits = re.sub(r'\D', '', phone)
        
        # Za krótki
        if len(digits) < 9:
            return False
        
        # Weź ostatnie 9 cyfr
        local_digits = digits[-9:] if len(digits) > 9 else digits
        
        # Fake patterns
        fake_patterns = [
            "123456789", "987654321", "123456", "654321",
            "111111", "222222", "333333", "444444", "555555",
            "666666", "777777", "888888", "999999", "000000",
            "123123", "456456", "789789",
        ]
        
        for pattern in fake_patterns:
            if pattern in local_digits:
                self.logger.debug("Odrzucam fake numer z Google Maps: %s", phone)
                return False
        
        # Sprawdź czy wszystkie cyfry są takie same
        if len(set(local_digits)) <= 2:
            return False
        
        return True
    
    async def search_by_url(self, google_maps_url: str) -> ScraperResult:
        """
        Pobiera dane z konkretnego URL Google Maps.
        
        Args:
            google_maps_url: URL miejsca w Google Maps
        
        Returns:
            ScraperResult z pojedynczą Placowka
        """
        self.logger.info("Fetching Google Maps URL: %s", google_maps_url)
        
        if not self._init_apify():
            return ScraperResult(
                success=False,
                error="Apify client not available",
            )
        
        run_input = {
            "startUrls": [{"url": google_maps_url}],
            "maxCrawledPlacesPerSearch": 1,
            "language": "pl",
        }
        
        try:
            run = await asyncio.to_thread(
                lambda: self._apify_client.actor(
                    self.settings.apify_google_maps_actor_id
                ).call(
                    run_input=run_input,
                    timeout_secs=self.settings.apify_actor_timeout_sec,
                )
            )
            
            if run.get("status") != "SUCCEEDED":
                return ScraperResult(
                    success=False,
                    error=f"Actor failed: {run.get('status')}",
                )
            
            dataset_id = run.get("defaultDatasetId")
            items = await asyncio.to_thread(
                lambda: list(self._apify_client.dataset(dataset_id).iterate_items())
            )
            
            if not items:
                return ScraperResult(
                    success=False,
                    error="No results for URL",
                )
            
            placowka = self._parse_place(items[0])
            
            return ScraperResult(
                success=True,
                data={"placowka": placowka, "raw": items[0]},
                cost_usd=0.003,
            )
            
        except Exception as e:
            self.logger.exception("Google Maps URL fetch failed: %s", e)
            return ScraperResult(
                success=False,
                error=str(e),
            )
