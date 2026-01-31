"""
Website Scraper - ekstrakcja danych ze strony WWW firmy.

Zbiera:
- Linki do social media
- Kontakty (telefony, email)
- Adresy
- Tekst do analizy AI
"""

import re
from typing import Optional
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ScraperResult
from ..models import SocialMediaLinks, Kontakt, Adres

# Import ekstrakcji adresów
try:
    from nip_finder_v3.utils.extractors import extract_addresses_from_text
    ADDR_EXTRACTOR_AVAILABLE = True
except ImportError:
    ADDR_EXTRACTOR_AVAILABLE = False
    extract_addresses_from_text = None


class WebsiteScraper(BaseScraper):
    """
    Scraper strony WWW.
    
    Ekstrakcja:
    - Linków social media (FB, IG, LinkedIn, TikTok, X)
    - Telefonów i emaili
    - Adresów
    - Tekstu strony (do kategoryzacji AI)
    """
    
    # Wzorce URL dla social media
    SOCIAL_PATTERNS = {
        "facebook": [
            r"(?:https?://)?(?:www\.)?facebook\.com/[\w\.\-]+/?",
            r"(?:https?://)?(?:www\.)?fb\.com/[\w\.\-]+/?",
        ],
        "instagram": [
            r"(?:https?://)?(?:www\.)?instagram\.com/[\w\.\-]+/?",
        ],
        "linkedin": [
            r"(?:https?://)?(?:www\.)?linkedin\.com/company/[\w\.\-]+/?",
            r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\.\-]+/?",
        ],
        "tiktok": [
            r"(?:https?://)?(?:www\.)?tiktok\.com/@[\w\.\-]+/?",
        ],
        "x": [
            r"(?:https?://)?(?:www\.)?twitter\.com/[\w\.\-]+/?",
            r"(?:https?://)?(?:www\.)?x\.com/[\w\.\-]+/?",
        ],
    }
    
    # Wzorce dla kontaktów - polskie numery telefonów
    # Format: +48 XXX XXX XXX lub XXX XXX XXX lub XX XXX XX XX (stacjonarne)
    PHONE_PATTERNS = [
        # +48 z 9 cyframi (komórkowe i stacjonarne)
        re.compile(r"\+48[\s\-]?\d{2,3}[\s\-]?\d{3}[\s\-]?\d{2,3}[\s\-]?\d{2,3}\b"),
        # 9 cyfr bez +48 - komórkowe (5,6,7,8)
        re.compile(r"\b[5-8]\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b"),
        # Stacjonarne z kierunkowym (np. 22 758 59 03)
        re.compile(r"\b(?:12|22|32|42|52|58|61|71|81|91)[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b"),
    ]
    # Stary pattern jako fallback
    PHONE_PATTERN = re.compile(
        r"(?:\+48[\s\-]?)?\d{2,3}[\s\-]?\d{3}[\s\-]?\d{2,3}[\s\-]?\d{2}\b",
        re.IGNORECASE
    )
    EMAIL_PATTERN = re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE
    )
    
    # Strony do przeszukania
    PAGES_TO_CHECK = [
        "",  # Strona główna
        "kontakt",
        "contact",
        "o-nas",
        "about",
        "lokalizacje",
        "placowki",
        "oddzialy",
        # Strony z danymi rejestracyjnymi (NIP, REGON)
        "polityka-prywatnosci",
        "privacy-policy",
        "regulamin",
        "terms",
        "rodo",
        "impressum",
        "dane-firmy",
        "o-firmie",
    ]
    
    async def _execute(
        self,
        url: str,
        max_pages: int = 5,
        extract_text: bool = True,
    ) -> ScraperResult:
        """
        Scrapuje stronę WWW.
        
        Args:
            url: URL strony głównej
            max_pages: Max stron do sprawdzenia
            extract_text: Czy wyciągać tekst (do AI)
        
        Returns:
            ScraperResult z danymi
        """
        self.logger.info("Scraping website: %s", url)
        
        # Normalizuj URL
        if not url.startswith("http"):
            url = f"https://{url}"
        
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        result_data = {
            "url": url,
            "social_links": SocialMediaLinks(website=url),
            "kontakty": [],
            "adresy": [],
            "page_text": "",
            "page_title": "",
            "pages_scraped": [],
        }
        
        all_text = []
        pages_scraped = 0
        ssl_failed = False
        
        # Konfiguracja klienta z obsługą problemów SSL
        client_kwargs = {
            "timeout": self.settings.request_timeout_sec,
            "follow_redirects": True,
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
            },
        }
        
        async with httpx.AsyncClient(**client_kwargs) as client:
            
            for page_path in self.PAGES_TO_CHECK[:max_pages]:
                page_url = urljoin(base_url, page_path)
                
                try:
                    self.logger.debug("Fetching: %s", page_url)
                    response = await self._fetch_with_fallback(client, page_url, ssl_failed)
                    
                    if response is None:
                        continue
                    
                    if response.status_code != 200:
                        self.logger.debug("Skip %s - HTTP %d", page_url, response.status_code)
                        continue
                    
                    pages_scraped += 1
                    result_data["pages_scraped"].append(page_url)
                    
                    # Parsuj HTML
                    soup = BeautifulSoup(response.text, "lxml")
                    
                    # Tytuł strony (tylko z głównej)
                    if not result_data["page_title"] and soup.title:
                        result_data["page_title"] = soup.title.get_text(strip=True)
                    
                    # Ekstrakcja social media
                    self._extract_social_links(soup, response.text, result_data["social_links"])
                    
                    # Ekstrakcja kontaktów
                    page_text = soup.get_text(separator=" ", strip=True)
                    self._extract_contacts(page_text, result_data["kontakty"])
                    
                    # Ekstrakcja adresów
                    if ADDR_EXTRACTOR_AVAILABLE:
                        found_addrs = extract_addresses_from_text(page_text)
                        for addr_str in found_addrs:
                            if addr_str not in result_data["adresy"]:
                                result_data["adresy"].append(addr_str)
                    
                    # Zbierz tekst do AI
                    if extract_text:
                        # Usuń skrypty i style
                        for tag in soup(["script", "style", "nav", "header", "footer"]):
                            tag.decompose()
                        
                        clean_text = soup.get_text(separator=" ", strip=True)
                        all_text.append(clean_text)
                    
                except Exception as e:
                    self.logger.debug("Error processing %s: %s", page_url, e)
                    continue
        
        # Połącz tekst (limit 15k znaków)
        if extract_text and all_text:
            combined_text = " ".join(all_text)
            result_data["page_text"] = combined_text[:15000]
        
        # Deduplikacja kontaktów
        result_data["kontakty"] = self._dedupe_contacts(result_data["kontakty"])
        
        self.logger.info(
            "Website scraped: %d pages, %d contacts, social: FB=%s IG=%s",
            pages_scraped,
            len(result_data["kontakty"]),
            bool(result_data["social_links"].facebook),
            bool(result_data["social_links"].instagram),
        )
        
        return ScraperResult(
            success=True,
            data=result_data,
            cost_usd=0.0,  # Własny scraping - bez kosztów
        )
    
    async def _fetch_with_fallback(
        self,
        client: httpx.AsyncClient,
        url: str,
        ssl_already_failed: bool = False,
    ) -> Optional[httpx.Response]:
        """
        Pobiera stronę z fallback dla problemów SSL.
        
        Strategia:
        1. Normalny request
        2. Jeśli SSL error - spróbuj z verify=False
        3. Jeśli nadal error - spróbuj HTTP zamiast HTTPS
        """
        import ssl
        
        # Strategia 1: Normalny request
        if not ssl_already_failed:
            try:
                return await client.get(url)
            except (httpx.ConnectError, ssl.SSLError, Exception) as e:
                error_str = str(e).lower()
                if "ssl" in error_str or "certificate" in error_str or "tls" in error_str:
                    self.logger.warning("SSL error for %s, trying with verify=False", url)
                else:
                    self.logger.warning("Request failed for %s: %s", url, e)
                    return None
        
        # Strategia 2: Ignoruj błędy SSL (verify=False)
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_sec,
                follow_redirects=True,
                verify=False,  # Ignoruj błędy certyfikatu
                headers=client.headers,
            ) as insecure_client:
                response = await insecure_client.get(url)
                self.logger.info("Fetched %s with verify=False", url)
                return response
        except Exception as e:
            self.logger.debug("verify=False failed for %s: %s", url, e)
        
        # Strategia 3: Spróbuj HTTP zamiast HTTPS
        if url.startswith("https://"):
            http_url = url.replace("https://", "http://", 1)
            try:
                response = await client.get(http_url)
                self.logger.info("Fetched via HTTP fallback: %s", http_url)
                return response
            except Exception as e:
                self.logger.debug("HTTP fallback failed for %s: %s", http_url, e)
        
        return None
    
    def _extract_social_links(
        self, 
        soup: BeautifulSoup, 
        html_text: str,
        social_links: SocialMediaLinks
    ) -> None:
        """Wyciąga linki social media z HTML."""
        
        # Szukaj w href wszystkich linków
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            self._match_social_url(href, social_links)
        
        # Szukaj też w surowym HTML (czasem linki są w JS)
        for platform, patterns in self.SOCIAL_PATTERNS.items():
            if getattr(social_links, platform):
                continue  # Już mamy
            
            for pattern in patterns:
                match = re.search(pattern, html_text, re.IGNORECASE)
                if match:
                    url = match.group(0)
                    if not url.startswith("http"):
                        url = "https://" + url.lstrip("/")
                    setattr(social_links, platform, url)
                    break
    
    def _extract_real_url(self, url: str) -> str:
        """Wyciąga prawdziwy URL z przekierowań Google."""
        if "google.com/url" in url.lower():
            # Wyciągnij url= z przekierowania
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if "url" in params:
                return params["url"][0]
        return url
    
    def _match_social_url(self, url: str, social_links: SocialMediaLinks) -> None:
        """Dopasowuje URL do platformy social media."""
        # Najpierw wyciągnij prawdziwy URL z przekierowań Google
        url = self._extract_real_url(url)
        url_lower = url.lower()
        
        if "facebook.com" in url_lower or "fb.com" in url_lower:
            if not social_links.facebook:
                social_links.facebook = url
        elif "instagram.com" in url_lower:
            if not social_links.instagram:
                social_links.instagram = url
        elif "linkedin.com" in url_lower:
            if not social_links.linkedin:
                social_links.linkedin = url
        elif "tiktok.com" in url_lower:
            if not social_links.tiktok:
                social_links.tiktok = url
        elif "twitter.com" in url_lower or "x.com" in url_lower:
            if not social_links.x:
                social_links.x = url
    
    def _extract_contacts(self, text: str, kontakty: list[Kontakt]) -> None:
        """Wyciąga telefony i emaile z tekstu."""
        
        # Telefony - użyj wszystkich patternów
        found_phones = set()
        
        for pattern in self.PHONE_PATTERNS:
            for match in pattern.finditer(text):
                phone = match.group(0)
                # Normalizuj - usuń spacje i myślniki
                phone_clean = re.sub(r"[\s\-]", "", phone)
                
                # Sprawdź długość (9-12 cyfr dla polskich numerów)
                digits_only = re.sub(r"\D", "", phone_clean)
                if len(digits_only) < 9 or len(digits_only) > 12:
                    continue
                
                # Dodaj +48 jeśli brak
                if not phone_clean.startswith("+"):
                    phone_clean = "+48" + phone_clean.lstrip("0")
                
                # Walidacja - odrzuć fake/placeholder numery
                if not self._is_valid_phone(phone_clean):
                    continue
                
                found_phones.add(phone_clean)
        
        # Dodaj unikalne numery (sformatowane)
        for phone_clean in found_phones:
            formatted = self._format_phone(phone_clean)
            if not any(k.wartosc == formatted for k in kontakty):
                kontakty.append(Kontakt(
                    typ="telefon",
                    wartosc=formatted,
                    opis=None
                ))
        
        # Emaile
        for match in self.EMAIL_PATTERN.finditer(text):
            email = match.group(0).lower()
            
            # Filtruj typowe fałszywe
            if any(x in email for x in ["example.com", "test.", "sample."]):
                continue
            
            # Sprawdź czy już mamy
            if not any(k.wartosc == email for k in kontakty):
                kontakty.append(Kontakt(
                    typ="email",
                    wartosc=email,
                    opis=None
                ))
    
    def _format_phone(self, phone: str) -> str:
        """
        Formatuje numer telefonu do standardowego formatu: +48 XXX XXX XXX
        """
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
            # Fallback - po prostu dodaj +48
            return f"+48 {digits}"
    
    def _is_valid_phone(self, phone: str) -> bool:
        """
        Sprawdza czy numer telefonu jest prawdziwy, nie placeholder.
        
        Odrzuca:
        - Sekwencje jak 123456, 111111, 000000
        - Zbyt krótkie numery
        - Znane placeholder patterns
        """
        # Wyciągnij tylko cyfry
        digits = re.sub(r'\D', '', phone)
        
        # Za krótki
        if len(digits) < 9:
            return False
        
        # Weź ostatnie 9 cyfr (bez kierunkowego kraju)
        local_digits = digits[-9:] if len(digits) > 9 else digits
        
        # Fake patterns - sekwencje
        fake_patterns = [
            "123456789", "987654321",  # Sekwencje rosnące/malejące
            "123456", "654321",
            "111111", "222222", "333333", "444444", "555555",
            "666666", "777777", "888888", "999999", "000000",
            "121212", "343434", "565656", "787878", "909090",
            "112233", "223344", "334455", "445566", "556677",
            "123123", "456456", "789789",
        ]
        
        for pattern in fake_patterns:
            if pattern in local_digits:
                self.logger.debug("Odrzucam fake numer: %s (pattern: %s)", phone, pattern)
                return False
        
        # Sprawdź czy wszystkie cyfry są takie same
        if len(set(local_digits)) <= 2:
            self.logger.debug("Odrzucam numer z powtarzającymi się cyframi: %s", phone)
            return False
        
        # Znane fake numery
        known_fakes = [
            "+48221234567", "+48123456789", "+48111111111",
            "+48000000000", "+48999999999", "+48712345678",
        ]
        if phone in known_fakes:
            return False
        
        return True
    
    def _dedupe_contacts(self, kontakty: list[Kontakt]) -> list[Kontakt]:
        """Usuwa duplikaty kontaktów."""
        seen = set()
        result = []
        
        for k in kontakty:
            key = (k.typ, k.wartosc)
            if key not in seen:
                seen.add(key)
                result.append(k)
        
        return result
