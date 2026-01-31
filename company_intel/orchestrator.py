"""
Company Intel Orchestrator - główny flow łączący wszystkie scrapery i analyzery.

Koordynuje:
1. Scraping strony WWW (discovery social links)
2. Scraping Google Maps (lokalizacje, recenzje)
3. Scraping social media (FB, IG, TikTok)
4. Kategoryzacja AI
5. Scoring aktywności
6. Generowanie finalnego JSON
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

from .config import CompanyIntelSettings, get_settings
from .models import (
    CompanyIntel,
    CompanyIntelRequest,
    SocialMediaLinks,
    Placowka,
    SocialProfile,
    Metadata,
    KategoryzacjaAI,
    ActivityScore,
    SocialPlatform,
    DataValidation,
    Kontakt,
)
from .scrapers import (
    WebsiteScraper,
    GoogleMapsScraper,
)
from .scrapers.facebook import FacebookScraper
from .scrapers.instagram import InstagramScraper
from .scrapers.tiktok import TikTokScraper
from .scrapers.znanylekarz import ZnanyLekarzScraper
from .analyzers import ActivityScorer, AICategorizer, ReviewsAnalyzer
from .nip_lookup import NIPLookup, NIPLookupResult

# Import ekstraktora NIP
try:
    from nip_finder_v3.utils.extractors import extract_nip_from_text
    NIP_EXTRACTOR_AVAILABLE = True
except ImportError:
    NIP_EXTRACTOR_AVAILABLE = False
    extract_nip_from_text = None


logger = logging.getLogger(__name__)


class CompanyIntelOrchestrator:
    """
    Główny orchestrator Company Intelligence.
    
    Łączy wszystkie komponenty i generuje pełny raport.
    """
    
    def __init__(self, settings: Optional[CompanyIntelSettings] = None):
        self.settings = settings or get_settings()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Inicjalizuj scrapery
        self.website_scraper = WebsiteScraper(self.settings)
        self.google_maps_scraper = GoogleMapsScraper(self.settings)
        self.facebook_scraper = FacebookScraper(self.settings)
        self.instagram_scraper = InstagramScraper(self.settings)
        self.tiktok_scraper = TikTokScraper(self.settings)
        self.znanylekarz_scraper = ZnanyLekarzScraper(self.settings)
        
        # NIP lookup
        self.nip_lookup = NIPLookup(self.settings)
        
        # Inicjalizuj analyzery
        self.scorer = ActivityScorer(self.settings)
        self.ai_categorizer = AICategorizer(self.settings)
        self.reviews_analyzer = ReviewsAnalyzer(self.settings)
    
    async def analyze_by_nip(
        self,
        nip: str,
        skip_social: bool = False,
        skip_ai: bool = False,
        skip_reviews: bool = False,
        core_only: bool = False,
    ) -> CompanyIntel:
        """
        Analizuje firmę po NIP.
        
        Workflow:
        1. NIP -> GUS API -> nazwa firmy, adres
        2. Nazwa firmy -> Google Search -> strona WWW
        3. Strona WWW -> pełna analiza
        
        Args:
            nip: NIP firmy (10 cyfr)
            skip_social: Pomiń scraping social media (FB, IG, TikTok)
            skip_ai: Pomiń kategoryzację AI
            skip_reviews: Pomiń analizę recenzji (Google Maps reviews, ZnanyLekarz)
            core_only: Tryb CORE - tylko WWW + placówki + kontakty (bez social, reviews, scoring)
        
        Returns:
            CompanyIntel z pełnymi danymi
        """
        self.logger.info("=" * 60)
        self.logger.info("ANALYZE BY NIP: %s", nip)
        self.logger.info("=" * 60)
        
        # Krok 1: Wyszukaj dane w GUS i stronę WWW
        lookup_result = await self.nip_lookup.lookup(nip)
        
        if not lookup_result.found and not lookup_result.website:
            self.logger.warning("NIP %s: nie znaleziono w GUS ani strony WWW", nip)
            # Zwróć pusty wynik z błędem
            return CompanyIntel(
                nip=lookup_result.nip,
                metadata=Metadata(
                    sources_used=["nip_lookup"],
                    errors=[lookup_result.error or "Nie znaleziono firmy"],
                ),
            )
        
        # Krok 2: Uruchom normalną analizę z danymi z lookup
        company_name = lookup_result.company_name
        city = lookup_result.city
        website = lookup_result.website
        
        self.logger.info(
            "NIP %s -> nazwa='%s', miasto='%s', www='%s'",
            nip,
            company_name[:50] if company_name else None,
            city,
            website,
        )
        
        # W trybie core_only automatycznie pomijamy social, reviews i scoring
        effective_skip_social = skip_social or core_only
        effective_skip_reviews = skip_reviews or core_only
        
        result = await self.analyze(
            company_name=company_name,
            nip=lookup_result.nip,
            city=city,
            website=website,
            skip_social=effective_skip_social,
            skip_ai=skip_ai,
            skip_reviews=effective_skip_reviews,
            core_only=core_only,
        )
        
        # Dodaj dane rejestrowe z GUS do wyniku
        if lookup_result.gus_data and lookup_result.gus_data.found:
            result.metadata.sources_used.insert(0, "gus")
            gus = lookup_result.gus_data
            
            # Dane rejestrowe
            result.regon = gus.regon
            
            # Jeśli nie mamy nazwy pełnej, użyj z GUS
            if not result.nazwa_pelna:
                result.nazwa_pelna = gus.full_name
            
            # Adres siedziby z GUS
            if gus.city or gus.street:
                from .models import Adres
                ulica = gus.street or ""
                if gus.building_number:
                    ulica += f" {gus.building_number}"
                if gus.apartment_number:
                    ulica += f"/{gus.apartment_number}"
                
                result.adres_siedziby = Adres(
                    ulica=ulica.strip() if ulica.strip() else None,
                    kod=gus.zip_code,
                    miasto=gus.city,
                    wojewodztwo=gus.voivodeship,
                )
        
        result.metadata.sources_used.insert(0, "nip_lookup")
        
        return result
    
    async def analyze(
        self,
        company_name: Optional[str] = None,
        nip: Optional[str] = None,
        city: Optional[str] = None,
        website: Optional[str] = None,
        social_links: Optional[SocialMediaLinks] = None,
        skip_social: bool = False,
        skip_ai: bool = False,
        skip_reviews: bool = False,
        core_only: bool = False,
    ) -> CompanyIntel:
        """
        Analizuje firmę i generuje pełny raport.
        
        Segmentacja na CORE / SOCIAL / REVIEWS:
        
        CORE (zawsze wykonywane):
        - Scraping strony WWW (kontakty, social links discovery)
        - Wyszukiwanie placówek w Google Maps (bez recenzji jeśli skip_reviews)
        - Podstawowe dane: kontakty, adresy, social links
        
        SOCIAL (pomijane jeśli skip_social lub core_only):
        - Scraping Facebook, Instagram, TikTok
        - Activity Score
        
        REVIEWS (pomijane jeśli skip_reviews lub core_only):
        - Analiza recenzji Google Maps
        - Scraping ZnanyLekarz
        - Analiza sentymentu
        
        Args:
            company_name: Nazwa firmy
            nip: NIP (opcjonalny)
            city: Miasto (opcjonalne)
            website: URL strony WWW (jeśli znany)
            social_links: Znane linki social (opcjonalne)
            skip_social: Pomiń scraping social media (FB, IG, TikTok)
            skip_ai: Pomiń kategoryzację AI
            skip_reviews: Pomiń analizę recenzji (Google Maps reviews, ZnanyLekarz)
            core_only: Tryb CORE - tylko WWW + placówki + kontakty (bez social, reviews, scoring)
        
        Returns:
            CompanyIntel z pełnymi danymi
        """
        start_time = time.time()
        
        self.logger.info(
            "=== Starting analysis: %s (NIP: %s, city: %s) ===",
            company_name,
            nip,
            city,
        )
        
        # Input logging
        input_data = {
            "company_name": company_name,
            "nip": nip,
            "city": city,
            "website": website,
            "social_links": social_links.to_dict() if social_links else None,
            "skip_social": skip_social,
            "skip_ai": skip_ai,
            "skip_reviews": skip_reviews,
            "core_only": core_only,
        }
        self.logger.info("[INPUT] Orchestrator.analyze | %s", input_data)
        
        # W trybie core_only automatycznie pomijamy social i reviews
        if core_only:
            skip_social = True
            skip_reviews = True
        
        # Inicjalizuj wynik
        result = CompanyIntel(
            nip=nip,
            nazwa_pelna=company_name,
            social_media=social_links or SocialMediaLinks(),
            metadata=Metadata(sources_used=[]),
        )
        
        total_cost = 0.0
        
        try:
            # === KROK 1: Scraping strony WWW ===
            if website:
                self.logger.info("Step 1: Scraping website...")
                website_result = await self.website_scraper.execute(url=website)
                
                if website_result.success:
                    data = website_result.data
                    
                    # Aktualizuj social links
                    if data.get("social_links"):
                        result.social_media = data["social_links"]
                    
                    # Kontakty -> pierwsza placówka
                    if data.get("kontakty"):
                        if not result.placowki:
                            result.placowki.append(Placowka())
                        result.placowki[0].kontakty = data["kontakty"]
                    
                    # Adresy ze strony WWW (tylko logowanie na razie)
                    www_adresy = data.get("adresy", [])
                    if www_adresy:
                        self.logger.info("Found %d addresses on website: %s", len(www_adresy), www_adresy[:3])
                    
                    # Zapisz tekst do AI
                    page_text = data.get("page_text", "")
                    page_title = data.get("page_title", "")
                    
                    result.metadata.sources_used.append("website")
                    total_cost += website_result.cost_usd
                    
                    # === KROK 1.5: Ekstrakcja NIP ze strony WWW i walidacja w GUS ===
                    if not nip and NIP_EXTRACTOR_AVAILABLE and page_text:
                        self.logger.info("Step 1.5: Extracting NIP from website...")
                        extracted_nip = extract_nip_from_text(page_text)
                        
                        if extracted_nip:
                            self.logger.info("Found NIP on website: %s - validating...", extracted_nip)
                            
                            # Walidacja i lookup w GUS
                            lookup_result = await self.nip_lookup.lookup(extracted_nip)
                            
                            if lookup_result.found:
                                # NIP jest poprawny (potwierdzony przez GUS lub Google)
                                result.nip = extracted_nip
                                self.logger.info("NIP validated: %s", extracted_nip)
                                
                                # Jeśli GUS zwrócił pełne dane - użyj ich
                                gus = lookup_result.gus_data
                                if gus and gus.found:
                                    self.logger.info("GUS data available: %s", gus.full_name[:50] if gus.full_name else "")
                                    
                                    result.regon = gus.regon
                                    
                                    # Nazwa pełna z GUS (jeśli lepsza niż z WWW)
                                    if gus.full_name and (not result.nazwa_pelna or len(gus.full_name) > len(result.nazwa_pelna)):
                                        result.nazwa_pelna = gus.full_name
                                    
                                    # Adres siedziby z GUS
                                    if gus.city or gus.street:
                                        from .models import Adres
                                        ulica = gus.street or ""
                                        if gus.building_number:
                                            ulica = f"{ulica} {gus.building_number}"
                                            if gus.apartment_number:
                                                ulica = f"{ulica}/{gus.apartment_number}"
                                        
                                        result.adres_siedziby = Adres(
                                            ulica=ulica.strip() or None,
                                            kod=gus.zip_code,
                                            miasto=gus.city,
                                            wojewodztwo=gus.voivodeship,
                                        )
                                    
                                    result.metadata.sources_used.append("gus")
                                else:
                                    # GUS niedostępny ale NIP potwierdzony przez Google
                                    self.logger.info("GUS unavailable, NIP confirmed via Google search")
                            else:
                                self.logger.warning("NIP %s not found/invalid", extracted_nip)
                        else:
                            self.logger.debug("No NIP found on website")
                else:
                    result.metadata.warnings.append(f"Website scraping failed: {website_result.error}")
                    page_text = ""
                    page_title = ""
            else:
                page_text = ""
                page_title = ""
            
            # === KROK 2: Google Maps ===
            if company_name:
                self.logger.info("Step 2: Searching Google Maps...")
                maps_result = await self.google_maps_scraper.execute(
                    company_name=company_name,
                    city=city,
                    max_places=5,
                    website=website,  # Filtruj wyniki po stronie WWW
                )
                
                if maps_result.success:
                    placowki = maps_result.data.get("placowki", [])
                    reviews_by_place = maps_result.data.get("reviews", {})  # place_id -> reviews
                    
                    # Merge z istniejącymi (kontakty z WWW mają priorytet)
                    if placowki:
                        # Zachowaj kontakty z WWW - są bardziej wiarygodne
                        www_kontakty = result.placowki[0].kontakty if result.placowki else []
                        
                        # === CROSS-VALIDATION KONTAKTÓW ===
                        # Zbierz wszystkie kontakty z Google Maps
                        all_google_kontakty = []
                        for p in placowki:
                            all_google_kontakty.extend(p.kontakty)
                        
                        # Porównaj kontakty WWW vs Google Maps
                        if www_kontakty or all_google_kontakty:
                            validation = self._cross_validate_contacts(www_kontakty, all_google_kontakty)
                            result.metadata.data_validation = validation
                        
                        result.placowki = placowki
                        
                        # Kontakty ogólne z WWW trafiają do WSZYSTKICH placówek
                        if www_kontakty:
                            for placowka in result.placowki:
                                # WWW kontakty + Google Maps kontakty dla tej placówki
                                google_kontakty = placowka.kontakty
                                merged = www_kontakty + google_kontakty
                                # Deduplikacja po wartości kontaktu
                                seen = set()
                                unique_kontakty = []
                                for k in merged:
                                    if k.wartosc not in seen:
                                        seen.add(k.wartosc)
                                        unique_kontakty.append(k)
                                placowka.kontakty = unique_kontakty
                        
                        # === ANALIZA RECENZJI Z GOOGLE MAPS ===
                        # BRAMKA: skip_reviews - pomija analizę recenzji (kosztowną operację AI)
                        if reviews_by_place and not skip_reviews:
                            self.logger.info("Step 2.5: Analyzing Google Maps reviews for %d places...", len(reviews_by_place))
                            for placowka in result.placowki:
                                if placowka.google_maps_place_id in reviews_by_place:
                                    reviews_data = reviews_by_place[placowka.google_maps_place_id]
                                    insights = await self.reviews_analyzer.analyze(
                                        reviews_data=reviews_data,
                                        place_name=f"{company_name} - {placowka.adres.miasto}",
                                    )
                                    if insights:
                                        placowka.reviews_insights = insights
                        elif reviews_by_place and skip_reviews:
                            self.logger.info("Step 2.5: SKIPPED - reviews analysis disabled (skip_reviews=True)")
                    
                    result.metadata.sources_used.append("google_maps")
                    if reviews_by_place and not skip_reviews:
                        result.metadata.sources_used.append("google_reviews_analysis")
                    total_cost += maps_result.cost_usd
                else:
                    result.metadata.warnings.append(f"Google Maps failed: {maps_result.error}")
            
            # === KROK 2B: ZnanyLekarz (opinie o komunikacji) ===
            # BRAMKA: skip_reviews - pomija scraping i analizę recenzji ZnanyLekarz
            if company_name and city and not skip_reviews:
                self.logger.info("Step 2B: Scraping ZnanyLekarz...")
                zl_result = await self.znanylekarz_scraper.execute(
                    company_name=company_name,
                    city=city,
                    max_reviews=50,
                )
                
                if zl_result.success and zl_result.data.get("reviews"):
                    zl_reviews = zl_result.data.get("reviews", [])
                    
                    self.logger.info("Step 2B.1: Analyzing ZnanyLekarz reviews...")
                    # Analiza recenzji ZnanyLekarz (fokus na komunikacji)
                    zl_insights = await self.reviews_analyzer.analyze(
                        reviews_data=zl_reviews,
                        place_name=f"{company_name} (ZnanyLekarz)",
                    )
                    
                    # Dodaj insights do pierwszej placówki (lub stwórz nową sekcję)
                    if zl_insights and result.placowki:
                        # Merge z istniejącymi insights z Google Maps
                        if result.placowki[0].reviews_insights:
                            # Połącz insights z obu źródeł
                            existing = result.placowki[0].reviews_insights
                            existing.total_reviews_analyzed += zl_insights.total_reviews_analyzed
                            existing.top_complaints.extend(zl_insights.top_complaints)
                            existing.top_praises.extend(zl_insights.top_praises)
                            existing.common_themes.extend(zl_insights.common_themes)
                            # Deduplikuj
                            existing.top_complaints = list(dict.fromkeys(existing.top_complaints))[:5]
                            existing.top_praises = list(dict.fromkeys(existing.top_praises))[:5]
                            existing.common_themes = list(dict.fromkeys(existing.common_themes))[:5]
                        else:
                            result.placowki[0].reviews_insights = zl_insights
                    
                    result.metadata.sources_used.append("znanylekarz")
                    result.metadata.sources_used.append("znanylekarz_reviews_analysis")
                    
                    # Dodaj info o responsywności placówki
                    if zl_result.data.get("facility_responds"):
                        result.metadata.warnings.append("Placówka aktywnie odpowiada na opinie (ZnanyLekarz)")
                else:
                    if zl_result.error != "Profile not found":
                        result.metadata.warnings.append(f"ZnanyLekarz failed: {zl_result.error}")
            elif skip_reviews:
                self.logger.info("Step 2B: SKIPPED - ZnanyLekarz disabled (skip_reviews=True)")
            
            # === KROK 3: Social Media (równolegle) ===
            if not skip_social:
                self.logger.info("Step 3: Scraping social media...")
                social_profiles = await self._scrape_social_media(
                    result.social_media,
                    result.metadata,
                )
                result.social_profiles = social_profiles
                
                # Oblicz koszt social
                # (koszty są w ScraperResult, ale tu upraszczamy)
            
            # === KROK 4: Kategoryzacja AI ===
            if not skip_ai and page_text:
                self.logger.info("Step 4: AI categorization...")
                result.kategoryzacja_ai = await self.ai_categorizer.categorize(
                    page_text=page_text,
                    company_name=company_name or page_title,
                )
                result.metadata.sources_used.append("ai_categorization")
            
            # === KROK 5: Nazwa zwyczajowa ===
            if page_title and not result.nazwa_zwyczajowa:
                result.nazwa_zwyczajowa = self._extract_short_name(
                    page_title,
                    company_name,
                )
            
        except Exception as e:
            self.logger.exception("Analysis failed: %s", e)
            result.metadata.errors.append(f"Analysis error: {str(e)}")
        
        # === DEDUPLIKACJA PLACÓWEK PO ADRESIE ===
        # Grupuj placówki po adresie i wybierz najlepszą (z najwyższym ratingiem)
        # WAŻNE: Musi być PRZED scoring żeby liczba placówek była prawidłowa
        result.placowki = self._deduplicate_placowki(result.placowki)
        
        # === LOKALNA DEDUPLIKACJA KONTAKTÓW ===
        # Usuń duplikaty WEWNĄTRZ każdej placówki (ale nie między placówkami)
        # Kontakty ogólne firmy powinny być przy WSZYSTKICH placówkach
        for placowka in result.placowki:
            seen = set()
            unique_kontakty = []
            for k in placowka.kontakty:
                if k.wartosc not in seen:
                    seen.add(k.wartosc)
                    unique_kontakty.append(k)
            placowka.kontakty = unique_kontakty
        
        # === KROK 6: Activity Score ===
        # BRAMKA: W trybie core_only pomijamy scoring (wymaga danych social)
        # WAŻNE: Musi być PO deduplikacji placówek żeby liczba była prawidłowa
        if not core_only:
            self.logger.info("Step 6: Calculating activity score...")
            result.activity_score = self.scorer.calculate(
                social_profiles=result.social_profiles,
                placowki=result.placowki,
                website_url=result.social_media.website,
            )
        else:
            self.logger.info("Step 6: SKIPPED - activity score disabled (core_only=True)")
        
        # === FINALIZACJA ===
        result.metadata.processing_time_ms = int((time.time() - start_time) * 1000)
        result.metadata.cost_usd = total_cost
        result.metadata.scraped_at = datetime.utcnow()
        
        # Output logging
        score_total = result.activity_score.total if result.activity_score else 0
        score_recommendation = result.activity_score.recommendation.value if result.activity_score else "N/A"
        
        self.logger.info(
            "[OUTPUT] Orchestrator.analyze | success | %dms | cost=$%.4f | score=%d (%s)",
            result.metadata.processing_time_ms,
            result.metadata.cost_usd,
            score_total,
            score_recommendation,
        )
        
        self.logger.info(
            "=== Analysis complete: %s | Score: %d | Sources: %s ===",
            company_name,
            score_total,
            ", ".join(result.metadata.sources_used),
        )
        
        return result
    
    async def analyze_core_only(
        self,
        company_name: Optional[str] = None,
        nip: Optional[str] = None,
        city: Optional[str] = None,
        website: Optional[str] = None,
    ) -> CompanyIntel:
        """
        Analizuje firmę w trybie CORE - tylko podstawowe dane.
        
        Wykonuje:
        - Scraping strony WWW (kontakty, social links discovery)
        - Wyszukiwanie placówek w Google Maps (bez recenzji)
        - Podstawowe dane: kontakty, adresy, social links
        
        NIE wykonuje:
        - Scraping social media (FB, IG, TikTok)
        - Analiza recenzji (Google Maps, ZnanyLekarz)
        - Activity Score
        
        Użyj tej metody dla endpointu /org/enrich-core.
        """
        return await self.analyze(
            company_name=company_name,
            nip=nip,
            city=city,
            website=website,
            core_only=True,
        )
    
    async def analyze_social_only(
        self,
        social_links: SocialMediaLinks,
        placowki: Optional[list[Placowka]] = None,
        website_url: Optional[str] = None,
        include_reviews: bool = False,
    ) -> dict:
        """
        Analizuje tylko social media i scoring.
        
        Wymaga przekazania social_links (np. z poprzedniego etapu CORE).
        
        Wykonuje:
        - Scraping social media (FB, IG, TikTok)
        - Activity Score
        
        Opcjonalnie (jeśli include_reviews=True):
        - Analiza recenzji z placówek (wymaga przekazania placowki)
        
        Użyj tej metody dla endpointu /org/enrich-social.
        
        Returns:
            dict z social_profiles, activity_score, reviews_insights (opcjonalnie)
        """
        start_time = time.time()
        
        # Scraping social media
        metadata = Metadata(sources_used=[])
        social_profiles = await self._scrape_social_media(social_links, metadata)
        
        # Activity Score
        activity_score = self.scorer.calculate(
            social_profiles=social_profiles,
            placowki=placowki or [],
            website_url=website_url or social_links.website,
        )
        
        result = {
            "social_profiles": [p.model_dump() if hasattr(p, 'model_dump') else p for p in social_profiles],
            "activity_score": activity_score.total if hasattr(activity_score, 'total') else 0,
            "activity_recommendation": activity_score.recommendation.value if hasattr(activity_score, 'recommendation') else None,
            "sources_used": metadata.sources_used,
            "processing_time_ms": int((time.time() - start_time) * 1000),
        }
        
        # Opcjonalnie: analiza recenzji
        if include_reviews and placowki:
            reviews_insights = []
            for placowka in placowki:
                if hasattr(placowka, 'reviews_insights') and placowka.reviews_insights:
                    reviews_insights.append(placowka.reviews_insights.model_dump())
            if reviews_insights:
                result["reviews_insights"] = reviews_insights
        
        return result
    
    async def _scrape_social_media(
        self,
        social_links: SocialMediaLinks,
        metadata: Metadata,
    ) -> list[SocialProfile]:
        """Scrapuje wszystkie dostępne social media równolegle."""
        profiles = []
        tasks = []
        
        # Facebook
        if social_links.facebook:
            tasks.append(("facebook", self.facebook_scraper.execute(
                facebook_url=social_links.facebook
            )))
        
        # Instagram
        if social_links.instagram:
            tasks.append(("instagram", self.instagram_scraper.execute(
                instagram_url=social_links.instagram
            )))
        
        # TikTok
        if social_links.tiktok:
            tasks.append(("tiktok", self.tiktok_scraper.execute(
                tiktok_url=social_links.tiktok
            )))
        
        if not tasks:
            self.logger.info("No social media links to scrape")
            return profiles
        
        # Wykonaj równolegle
        self.logger.info("Scraping %d social profiles...", len(tasks))
        
        results = await asyncio.gather(
            *[task for _, task in tasks],
            return_exceptions=True,
        )
        
        for i, (platform, _) in enumerate(tasks):
            result = results[i]
            
            if isinstance(result, Exception):
                self.logger.warning("%s scraping exception: %s", platform, result)
                metadata.warnings.append(f"{platform} failed: {str(result)}")
                continue
            
            if result.success:
                profile = result.data.get("profile")
                if profile:
                    profiles.append(profile)
                    metadata.sources_used.append(platform)
                    self.logger.info("%s scraped: %s", platform, profile.followers)
            else:
                self.logger.warning("%s scraping failed: %s", platform, result.error)
                metadata.warnings.append(f"{platform} failed: {result.error}")
        
        return profiles
    
    def _deduplicate_placowki(self, placowki: list[Placowka]) -> list[Placowka]:
        """
        Deduplikuje placówki po adresie.
        
        Jeśli kilka placówek ma ten sam adres (ulica + miasto),
        wybiera tę z najlepszym ratingiem/liczbą recenzji.
        """
        if not placowki:
            return []
        
        # Grupuj po adresie
        from collections import defaultdict
        address_groups = defaultdict(list)
        
        for p in placowki:
            if not p.adres:
                address_groups[None].append(p)
                continue
            
            # Klucz: ulica + miasto (normalizowane)
            ulica = (p.adres.ulica or "").strip().lower()
            miasto = (p.adres.miasto or "").strip().lower()
            key = (ulica, miasto)
            address_groups[key].append(p)
        
        # Wybierz najlepszą placówkę z każdej grupy
        result = []
        for key, group in address_groups.items():
            if len(group) == 1:
                result.append(group[0])
            else:
                # Wybierz placówkę z najlepszym ratingiem
                best = max(
                    group,
                    key=lambda p: (
                        p.google_reviews_count or 0,  # Najpierw liczba recenzji
                        p.google_rating or 0,  # Potem rating
                        len(p.kontakty),  # Potem liczba kontaktów
                    )
                )
                
                # Merge kontaktów z wszystkich duplikatów
                all_contacts = []
                seen = set()
                for p in group:
                    for k in p.kontakty:
                        if k.wartosc not in seen:
                            seen.add(k.wartosc)
                            all_contacts.append(k)
                
                best.kontakty = all_contacts
                result.append(best)
                
                self.logger.info(
                    "Deduplicated %d placówki at '%s, %s' -> kept best (rating=%.1f, reviews=%d)",
                    len(group),
                    key[0][:30] if key[0] else "?",
                    key[1][:20] if key[1] else "?",
                    best.google_rating or 0,
                    best.google_reviews_count or 0,
                )
        
        return result
    
    def _cross_validate_contacts(
        self,
        www_kontakty: list[Kontakt],
        google_kontakty: list[Kontakt],
    ) -> DataValidation:
        """
        Porównuje kontakty z WWW i Google Maps.
        Zwraca DataValidation z informacją o niespójnościach.
        """
        import re
        
        validation = DataValidation()
        discrepancies = []
        
        # Normalizuj telefony (tylko cyfry)
        def normalize_phone(phone: str) -> str:
            digits = re.sub(r'\D', '', phone)
            return digits[-9:] if len(digits) >= 9 else digits
        
        # Wyciągnij telefony
        www_phones = {normalize_phone(k.wartosc) for k in www_kontakty if k.typ == "telefon"}
        google_phones = {normalize_phone(k.wartosc) for k in google_kontakty if k.typ == "telefon"}
        
        # Wyciągnij emaile
        www_emails = {k.wartosc.lower() for k in www_kontakty if k.typ == "email"}
        google_emails = {k.wartosc.lower() for k in google_kontakty if k.typ == "email"}
        
        # Sprawdź rozbieżności telefonów
        if www_phones and google_phones:
            # Sprawdź czy jest wspólny telefon
            common_phones = www_phones & google_phones
            if not common_phones:
                discrepancies.append(
                    f"Brak wspólnego telefonu: WWW ma {len(www_phones)}, Google Maps ma {len(google_phones)}"
                )
        
        # Tylko Google Maps ma telefon (WWW nie ma)
        if google_phones and not www_phones:
            discrepancies.append(
                f"Telefon tylko w Google Maps: {', '.join(google_phones)}"
            )
        
        # Sprawdź rozbieżności emaili
        if www_emails and google_emails:
            common_emails = www_emails & google_emails
            if not common_emails:
                discrepancies.append(
                    f"Brak wspólnego emaila między WWW i Google Maps"
                )
        
        # Ustaw wyniki
        if discrepancies:
            validation.contacts_match = False
            validation.contacts_discrepancies = discrepancies
            self.logger.warning("Cross-validation: %d contact discrepancies found", len(discrepancies))
        
        return validation
    
    def _extract_short_name(
        self,
        page_title: str,
        company_name: Optional[str],
    ) -> Optional[str]:
        """Wyciąga krótką nazwę z tytułu strony."""
        if not page_title:
            return company_name
        
        # Usuń typowe sufiksy
        suffixes = [
            " - Strona główna",
            " - Home",
            " | Oficjalna strona",
            " - Oficjalna strona",
            " | ",
            " - ",
        ]
        
        result = page_title
        for suffix in suffixes:
            if suffix in result:
                result = result.split(suffix)[0]
        
        return result.strip()[:100] if result else company_name
    
    async def analyze_from_request(self, request: CompanyIntelRequest) -> CompanyIntel:
        """Analizuje firmę na podstawie CompanyIntelRequest."""
        return await self.analyze(
            company_name=request.company_name,
            nip=request.nip,
            city=request.city,
            website=request.website,
            social_links=request.social_links,
        )
    
    async def close(self) -> None:
        """Zamyka wszystkie zasoby."""
        await self.website_scraper.close()
        await self.google_maps_scraper.close()
        await self.facebook_scraper.close()
        await self.instagram_scraper.close()
        await self.tiktok_scraper.close()
        await self.ai_categorizer.close()
        await self.nip_lookup.close()
