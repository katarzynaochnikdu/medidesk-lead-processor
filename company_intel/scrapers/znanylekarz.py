"""
ZnanyLekarz Scraper - pobiera opinie o placówkach medycznych.

Zbiera:
- Opinie pacjentów (tekst, ocena, data)
- Odpowiedzi placówki
- Średnią ocenę
- Liczbę opinii
"""

import re
from typing import Optional
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ScraperResult


class ZnanyLekarzScraper(BaseScraper):
    """
    Scraper profilu placówki na ZnanyLekarz.pl.
    
    Wyszukuje placówkę po nazwie i mieście, następnie pobiera opinie.
    """
    
    async def _execute(
        self,
        company_name: str,
        city: Optional[str] = None,
        max_reviews: int = 50,
    ) -> ScraperResult:
        """
        Wyszukuje placówkę i pobiera opinie.
        
        Args:
            company_name: Nazwa placówki
            city: Miasto (opcjonalne, pomaga w wyszukiwaniu)
            max_reviews: Max liczba opinii do pobrania
        
        Returns:
            ScraperResult z opiniami
        """
        self.logger.info(
            "Searching ZnanyLekarz: '%s' in '%s'",
            company_name,
            city or "Poland",
        )
        
        try:
            # KROK 1: Wyszukaj placówkę
            profile_url = await self._find_profile(company_name, city)
            
            if not profile_url:
                self.logger.warning("Profile not found on ZnanyLekarz")
                return ScraperResult(
                    success=False,
                    error="Profile not found",
                    data={"reviews": [], "profile_url": None},
                )
            
            self.logger.info("Found profile: %s", profile_url)
            
            # KROK 2: Pobierz opinie
            reviews_data = await self._scrape_reviews(profile_url, max_reviews)
            
            self.logger.info(
                "Scraped %d reviews from ZnanyLekarz",
                len(reviews_data.get("reviews", [])),
            )
            
            return ScraperResult(
                success=True,
                data={
                    "reviews": reviews_data.get("reviews", []),
                    "avg_rating": reviews_data.get("avg_rating"),
                    "total_reviews": reviews_data.get("total_reviews"),
                    "profile_url": profile_url,
                    "facility_responds": reviews_data.get("facility_responds", False),
                },
                cost_usd=0.0,  # Darmowy scraping
            )
            
        except Exception as e:
            self.logger.exception("ZnanyLekarz scraping failed: %s", e)
            return ScraperResult(
                success=False,
                error=str(e),
                data={"reviews": []},
            )
    
    async def _find_profile(
        self,
        company_name: str,
        city: Optional[str],
    ) -> Optional[str]:
        """Wyszukuje profil placówki na ZnanyLekarz."""
        try:
            # Przygotuj query
            query = company_name.lower().strip()
            
            # Usuń typowe słowa
            query = re.sub(r'\b(klinika|centrum|gabinet|przychodnia|nzoz)\b', '', query, flags=re.IGNORECASE)
            query = query.strip()
            
            # Wyszukaj przez Google (site:znanylekarz.pl)
            search_query = f'site:znanylekarz.pl/placowki {query}'
            if city:
                search_query += f' {city}'
            
            # Użyj httpx do prostego wyszukania
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                # Spróbuj bezpośredniego URL (zgadnij slug)
                slug = self._make_slug(company_name)
                direct_url = f"https://www.znanylekarz.pl/placowki/{slug}"
                
                response = await client.get(direct_url)
                if response.status_code == 200:
                    self.logger.info("Found via direct URL: %s", direct_url)
                    return direct_url
                
                # Fallback: wyszukaj przez Google
                self.logger.info("Direct URL failed, searching via Google...")
                google_url = f"https://www.google.com/search?q={search_query}"
                
                response = await client.get(
                    google_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                
                if response.status_code != 200:
                    return None
                
                # Parsuj wyniki Google
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Szukaj linków do znanylekarz.pl/placowki
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    if "znanylekarz.pl/placowki/" in href and "/placowki/stomatologia/" not in href:
                        # Wyciągnij prawdziwy URL z Google redirect
                        match = re.search(r'https://www\.znanylekarz\.pl/placowki/[^&"]+', href)
                        if match:
                            return match.group(0)
                
                return None
                
        except Exception as e:
            self.logger.error("Profile search failed: %s", e)
            return None
    
    def _make_slug(self, company_name: str) -> str:
        """Tworzy slug z nazwy firmy."""
        slug = company_name.lower()
        
        # Usuń typowe słowa
        slug = re.sub(r'\b(klinika|centrum|gabinet|przychodnia|nzoz|sp\.|z\.?o\.?o\.?)\b', '', slug, flags=re.IGNORECASE)
        
        # Zamień polskie znaki
        replacements = {
            'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l',
            'ń': 'n', 'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        }
        for pl, en in replacements.items():
            slug = slug.replace(pl, en)
        
        # Usuń znaki specjalne
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug.strip())
        slug = re.sub(r'-+', '-', slug)
        
        return slug
    
    async def _scrape_reviews(
        self,
        profile_url: str,
        max_reviews: int,
    ) -> dict:
        """Pobiera opinie z profilu placówki."""
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                verify=False,  # SSL issues
            ) as client:
                response = await client.get(
                    profile_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept-Language": "pl-PL,pl;q=0.9",
                    },
                )
                
                if response.status_code != 200:
                    self.logger.error("Failed to fetch profile: %d", response.status_code)
                    return {"reviews": []}
                
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Wyciągnij średnią ocenę i liczbę opinii
                avg_rating = None
                total_reviews = 0
                
                # Szukaj "304 opinie" lub podobnych
                rating_text = soup.find(text=re.compile(r'\d+\s+opini'))
                if rating_text:
                    match = re.search(r'(\d+)\s+opini', rating_text)
                    if match:
                        total_reviews = int(match.group(1))
                
                # Szukaj średniej oceny (gwiazdki)
                rating_elem = soup.find("span", class_=re.compile(r"rating|stars"))
                if rating_elem:
                    rating_text = rating_elem.get_text()
                    match = re.search(r'(\d+(?:\.\d+)?)', rating_text)
                    if match:
                        avg_rating = float(match.group(1))
                
                # Pobierz opinie
                reviews = []
                
                # Szukaj sekcji z opiniami
                # ZnanyLekarz używa różnych struktur - szukamy elastycznie
                review_containers = soup.find_all(["article", "div"], class_=re.compile(r"opinion|review|comment"))
                
                if not review_containers:
                    # Fallback: szukaj po strukturze tekstu
                    # Opinie mają format: inicjał, tekst, data, lekarz
                    self.logger.warning("No review containers found, trying text parsing")
                
                for container in review_containers[:max_reviews]:
                    review = self._parse_review(container)
                    if review:
                        reviews.append(review)
                
                # Sprawdź czy placówka odpowiada na opinie
                facility_responds = any(r.get("facility_response") for r in reviews)
                
                self.logger.info(
                    "Parsed: %d reviews, avg=%.1f, total=%d, responds=%s",
                    len(reviews),
                    avg_rating or 0,
                    total_reviews,
                    facility_responds,
                )
                
                return {
                    "reviews": reviews,
                    "avg_rating": avg_rating,
                    "total_reviews": total_reviews,
                    "facility_responds": facility_responds,
                }
                
        except Exception as e:
            self.logger.exception("Reviews scraping failed: %s", e)
            return {"reviews": []}
    
    def _parse_review(self, container) -> Optional[dict]:
        """Parsuje pojedynczą opinię."""
        try:
            # Wyciągnij tekst opinii
            text = ""
            text_elem = container.find(["p", "div"], class_=re.compile(r"text|content|body"))
            if text_elem:
                text = text_elem.get_text(strip=True)
            
            if not text:
                # Fallback: cały tekst z kontenera
                text = container.get_text(strip=True)
            
            # Wyciągnij ocenę (gwiazdki)
            rating = None
            rating_elem = container.find(["span", "div"], class_=re.compile(r"star|rating"))
            if rating_elem:
                # Szukaj liczby gwiazdek
                rating_text = rating_elem.get("aria-label", "") or rating_elem.get_text()
                match = re.search(r'(\d+)', rating_text)
                if match:
                    rating = int(match.group(1))
            
            # Wyciągnij datę
            date = None
            date_elem = container.find(["time", "span"], class_=re.compile(r"date|time"))
            if date_elem:
                date = date_elem.get_text(strip=True)
            
            # Wyciągnij nazwę lekarza/usługi
            doctor = None
            doctor_elem = container.find(["span", "a"], class_=re.compile(r"doctor|specialist"))
            if doctor_elem:
                doctor = doctor_elem.get_text(strip=True)
            
            # Wyciągnij odpowiedź placówki
            facility_response = None
            response_elem = container.find_next_sibling(["div", "article"], class_=re.compile(r"response|reply"))
            if response_elem:
                facility_response = response_elem.get_text(strip=True)
            
            if not text or len(text) < 10:
                return None
            
            return {
                "text": text,
                "rating": rating,
                "date": date,
                "doctor": doctor,
                "facility_response": facility_response,
            }
            
        except Exception as e:
            self.logger.debug("Failed to parse review: %s", e)
            return None
