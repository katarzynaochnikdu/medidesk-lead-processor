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
from .scrapers.zoho_lookup import ZohoLookupScraper
from .analyzers import ActivityScorer, AICategorizer, ReviewsAnalyzer
from .nip_lookup import NIPLookup, NIPLookupResult
from .chaotic_router import ChaoticDataRouter
from .models import DecisionTrace, CandidateDecision

# Import ekstraktora NIP i PEŁNY NIPFinderV3 (zamiast uproszczonego GoogleSearchStrategy)
try:
    from nip_finder_v3.utils.extractors import extract_nip_from_text
    from nip_finder_v3 import NIPFinderV3
    NIP_EXTRACTOR_AVAILABLE = True
    NIP_FINDER_V3_AVAILABLE = True
except ImportError:
    NIP_EXTRACTOR_AVAILABLE = False
    NIP_FINDER_V3_AVAILABLE = False
    extract_nip_from_text = None
    NIPFinderV3 = None


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
        
        # PEŁNY NIPFinderV3 - 8-poziomowa kaskada wyszukiwania NIP
        # (Privacy Policy, Google Search, Homepage, Domain Discovery, Brave)
        # UWAGA: Używam API key zamiast Vertex AI SDK (problem z gcloud auth)
        if NIP_FINDER_V3_AVAILABLE:
            from nip_finder_v3.config import NIPFinderV3Settings
            import os
            nip_settings = NIPFinderV3Settings(
                # Wymuś użycie API key zamiast Vertex AI SDK (który wymaga gcloud auth)
                vertex_ai_project_id="",  # Wyłącz Vertex AI SDK - użyje API key fallback
                enable_ai_semantic_validation=True,  # Włącz AI (przez API key)
                enable_ai_enrichment=False,  # Wyłącz enrichment (niepotrzebne)
                enable_ai_domain_discovery=False,  # Wyłącz domain discovery
            )
            self.nip_finder_v3 = NIPFinderV3(settings=nip_settings)
            self.logger.info("NIPFinderV3 initialized (8-level cascade, using API key for AI)")
        else:
            self.nip_finder_v3 = None
            self.logger.warning("NIPFinderV3 NOT available - NIP search will be limited")
        
        # Zoho lookup
        self.zoho_lookup = ZohoLookupScraper(self.settings)
        
        # Vertex AI service (do parsowania chaotycznych danych)
        self.vertex_ai = None
        try:
            from src.services.vertex_ai import get_vertex_ai_service
            self.vertex_ai = get_vertex_ai_service()
            self.logger.info("Vertex AI service initialized")
        except Exception as e:
            self.logger.warning("Vertex AI not available: %s", e)
        
        # Chaotic Data Router (nowa ścieżka dla chaotycznych danych)
        self.chaotic_router = ChaoticDataRouter(
            settings=self.settings,
            nip_lookup=self.nip_lookup,
            zoho_lookup=self.zoho_lookup,
            nip_finder_v3=self.nip_finder_v3,
            vertex_ai_service=self.vertex_ai,
        )
        self.logger.info("ChaoticDataRouter initialized")
        
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
            
            # === KROK 1.5a: TANIE szukanie NIP w Zoho po danych ze strony ===
            # ZAKOMENTOWANE NA CZAS TESTÓW ZEWNĘTRZNYCH SERWISÓW (NIPFinderV3)
            # TODO: Odkomentować po testach!
            # if not result.nip and website:
            #     self.logger.info("Step 1.5a: Searching NIP in Zoho by website data (CHEAP!)...")
            #     from urllib.parse import urlparse
            #     parsed_url = urlparse(website)
            #     search_domain = parsed_url.netloc.replace("www.", "") if parsed_url.netloc else None
            #     phones_from_website = []
            #     email_domains_from_website = []
            #     if result.placowki and result.placowki[0].kontakty:
            #         for kontakt in result.placowki[0].kontakty:
            #             if kontakt.typ == "telefon" and kontakt.wartosc:
            #                 phones_from_website.append(kontakt.wartosc)
            #             elif kontakt.typ == "email" and kontakt.wartosc:
            #                 if "@" in kontakt.wartosc:
            #                     email_domain = kontakt.wartosc.split("@")[1].lower()
            #                     if email_domain not in email_domains_from_website:
            #                         email_domains_from_website.append(email_domain)
            #     self.logger.info("  Domain: %s, Phones: %s, Email domains: %s", 
            #                    search_domain, phones_from_website[:3], email_domains_from_website[:3])
            #     try:
            #         zoho_nip = await self.zoho_lookup.find_nip_by_website_data(
            #             domain=search_domain, phones=phones_from_website, email_domains=email_domains_from_website)
            #         if zoho_nip:
            #             self.logger.info("ZOHO HIT! Found NIP %s in CRM (FREE!)", zoho_nip)
            #             lookup_result = await self.nip_lookup.lookup(zoho_nip)
            #             if lookup_result.found:
            #                 result.nip = zoho_nip
            #                 gus = lookup_result.gus_data
            #                 if gus and gus.found:
            #                     result.regon = gus.regon
            #                     if gus.full_name: result.nazwa_pelna = gus.full_name
            #                     if gus.city or gus.street:
            #                         from .models import Adres
            #                         result.adres_siedziby = Adres(ulica=gus.street, kod=gus.zip_code, miasto=gus.city, wojewodztwo=gus.voivodeship)
            #                     result.metadata.sources_used.append("gus")
            #                 result.metadata.sources_used.append("zoho_nip_lookup")
            #     except Exception as e:
            #         self.logger.warning("Zoho NIP lookup failed: %s", e)
            
            # === KROK 1.5b: Szukaj NIP przez PEŁNY NIPFinderV3 (8-poziomowa kaskada) ===
            # KASKADA: Privacy Policy (90%) -> Google+AI -> Homepage -> AI Discovery -> Brave
            # UWAGA: Ten krok MUSI być POZA blokiem if page_text żeby działał zawsze
            if not result.nip and self.nip_finder_v3 and (page_title or company_name):
                search_name = page_title or company_name
                # Wyciągnij domenę z website (dla privacy policy scraping)
                search_domain = None
                if website:
                    from urllib.parse import urlparse
                    parsed = urlparse(website)
                    search_domain = parsed.netloc.replace("www.", "") if parsed.netloc else None
                
                self.logger.info("Step 1.5b: NIPFinderV3 cascade for '%s' (domain=%s)...", 
                               search_name[:50], search_domain or "none")
                try:
                    # PEŁNA KASKADA V3: privacy -> google+AI -> homepage -> brave
                    # UWAGA: NIPFinderV3 ekstrauje domenę z emaila - tworzymy fake email z domeny
                    fake_email = f"info@{search_domain}" if search_domain else None
                    nip_result = await self.nip_finder_v3.find_nip(
                        company_name=search_name,
                        city=city,
                        email=fake_email,  # Fake email żeby NIPFinderV3 wyciągnął domenę
                        skip_cache=True,  # Pomiń cache - chcemy świeże wyniki
                    )
                    
                    if nip_result and nip_result.found and nip_result.nip:
                        strategy_name = nip_result.strategy_used.value if nip_result.strategy_used else "unknown"
                        self.logger.info(
                            "NIPFinderV3 SUCCESS: NIP=%s (confidence: %.2f, strategy: %s)", 
                            nip_result.nip, nip_result.confidence, strategy_name
                        )
                        
                        # Walidacja w GUS (może już być z kaskady, ale dla pewności)
                        lookup_result = await self.nip_lookup.lookup(nip_result.nip)
                        if lookup_result.found:
                            result.nip = nip_result.nip
                            self.logger.info("NIP validated via GUS: %s", nip_result.nip)
                            
                            # Dane z GUS
                            gus = lookup_result.gus_data
                            if gus and gus.found:
                                result.regon = gus.regon
                                if gus.full_name and (not result.nazwa_pelna or len(gus.full_name) > len(result.nazwa_pelna)):
                                    result.nazwa_pelna = gus.full_name
                                if gus.city or gus.street:
                                    from .models import Adres
                                    result.adres_siedziby = Adres(
                                        ulica=gus.street,
                                        kod=gus.zip_code,
                                        miasto=gus.city,
                                        wojewodztwo=gus.voivodeship,
                                    )
                                result.metadata.sources_used.append("gus")
                            result.metadata.sources_used.append(f"nip_finder_v3_{strategy_name}")
                        else:
                            self.logger.warning("NIPFinderV3 NIP %s not confirmed by GUS", nip_result.nip)
                    else:
                        self.logger.debug("NIPFinderV3: No NIP found in cascade")
                except Exception as e:
                    self.logger.warning("NIPFinderV3 cascade failed: %s", e)
            
            # === KROK 1.6: Wyciagnij krotka nazwe ze strony (przed Google Maps) ===
            short_name = None
            if page_title:
                short_name = self._extract_short_name(page_title, company_name)
                if short_name and short_name != company_name:
                    self.logger.info("Step 1.6: Short name from website: '%s'", short_name)
            
            # === KROK 2: Google Maps ===
            # Szukaj po obu nazwach: pelnej (GUS) i krotkiej (strona WWW)
            search_names = []
            if company_name:
                search_names.append(company_name)
            if short_name and short_name not in search_names:
                search_names.append(short_name)
            
            all_placowki = []
            all_reviews = {}
            
            for search_name in search_names:
                self.logger.info("Step 2: Searching Google Maps for '%s'...", search_name[:50])
                maps_result = await self.google_maps_scraper.execute(
                    company_name=search_name,
                    city=city,
                    max_places=5,
                    website=website,  # Filtruj wyniki po stronie WWW
                )
                
                if maps_result.success:
                    placowki = maps_result.data.get("placowki", [])
                    reviews_by_place = maps_result.data.get("reviews", {})
                    
                    # Zbieraj placowki z roznych wyszukiwan
                    for p in placowki:
                        # Deduplikacja po place_id
                        if p.google_maps_place_id and p.google_maps_place_id not in [
                            x.google_maps_place_id for x in all_placowki
                        ]:
                            all_placowki.append(p)
                            self.logger.info("  Found place: %s (%s)", p.adres.ulica, p.google_maps_place_id)
                    
                    # Zbieraj recenzje
                    all_reviews.update(reviews_by_place)
                    total_cost += maps_result.cost_usd
                else:
                    self.logger.warning("Google Maps search failed for '%s': %s", search_name[:30], maps_result.error)
            
            # === KROK 2.1: Przetwarzanie znalezionych placowek ===
            if all_placowki:
                self.logger.info("Step 2.1: Processing %d unique places from Google Maps", len(all_placowki))
                
                # Zachowaj kontakty z WWW - sa bardziej wiarygodne
                www_kontakty = result.placowki[0].kontakty if result.placowki else []
                
                # === CROSS-VALIDATION KONTAKTOW ===
                all_google_kontakty = []
                for p in all_placowki:
                    all_google_kontakty.extend(p.kontakty)
                
                if www_kontakty or all_google_kontakty:
                    validation = self._cross_validate_contacts(www_kontakty, all_google_kontakty)
                    result.metadata.data_validation = validation
                
                result.placowki = all_placowki
                
                # Kontakty ogolne z WWW trafiaja do WSZYSTKICH placowek
                if www_kontakty:
                    for placowka in result.placowki:
                        google_kontakty = placowka.kontakty
                        merged = www_kontakty + google_kontakty
                        seen = set()
                        unique_kontakty = []
                        for k in merged:
                            if k.wartosc not in seen:
                                seen.add(k.wartosc)
                                unique_kontakty.append(k)
                        placowka.kontakty = unique_kontakty
                
                # === ANALIZA RECENZJI Z GOOGLE MAPS ===
                if all_reviews and not skip_reviews:
                    self.logger.info("Step 2.5: Analyzing Google Maps reviews for %d places...", len(all_reviews))
                    for placowka in result.placowki:
                        if placowka.google_maps_place_id in all_reviews:
                            reviews_data = all_reviews[placowka.google_maps_place_id]
                            insights = await self.reviews_analyzer.analyze(
                                reviews_data=reviews_data,
                                place_name=f"{company_name} - {placowka.adres.miasto}",
                            )
                            if insights:
                                placowka.reviews_insights = insights
                elif all_reviews and skip_reviews:
                    self.logger.info("Step 2.5: SKIPPED - reviews analysis disabled (skip_reviews=True)")
                
                result.metadata.sources_used.append("google_maps")
                if all_reviews and not skip_reviews:
                    result.metadata.sources_used.append("google_reviews_analysis")
            elif search_names:
                result.metadata.warnings.append("Google Maps: no places found for any search name")
            
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
        
        # === KROK 5.4: NORMALIZACJA DANYCH I NAZWY PLACÓWEK ===
        # 1. Maile małymi literami
        # 2. Nazwy WIELKIMI LITERAMI
        # 3. Generuj nazwa_placowki: [BRAND] [MIASTO] [ULICA]
        # 4. Wyciągnij brand name przez AI (słowo klucz marketingowe)
        await self._normalize_and_name_placowki_async(result, page_title, page_text)
        
        # === KROK 5.5: ZOHO CRM LOOKUP ===
        # Sprawdź czy placówki istnieją w Zoho CRM
        # WYMAGANY NIP - bez NIP nie ma sensu szukać w Zoho (zbyt ryzykowne dopasowania)
        if self.settings.has_zoho_credentials and result.nip and result.placowki:
            self.logger.info("Step 5.5: Checking Zoho CRM for NIP %s...", result.nip)
            try:
                # Pobierz wszystkie lokalizacje firmy z Zoho PO NIP
                zoho_locations = await self.zoho_lookup.lookup_by_nip(result.nip)
                
                if zoho_locations:
                    self.logger.info("Zoho: Found %d existing locations in CRM for NIP %s", len(zoho_locations), result.nip)
                    result.metadata.sources_used.append("zoho_crm")
                    
                    # Dla każdej znalezionej placówki, spróbuj dopasować do lokalizacji w Zoho
                    for placowka in result.placowki:
                        best_match = self._match_placowka_to_zoho(placowka, zoho_locations)
                        
                        if best_match:
                            placowka.zoho_match = best_match
                            self.logger.info(
                                "Zoho match: %s -> %s (status: %s, typ: %s)",
                                placowka.adres.miasto or "?",
                                best_match.zoho_name,
                                best_match.status_klienta or "-",
                                best_match.adres_w_rekordzie or "-",
                            )
                        else:
                            self.logger.info(
                                "Zoho: No match for placowka %s - new location?",
                                placowka.adres.miasto or placowka.adres.ulica or "?",
                            )
                else:
                    self.logger.info("Zoho: NIP %s not found in CRM - new company", result.nip)
            except Exception as e:
                self.logger.warning("Zoho lookup failed: %s", e)
        elif not result.nip and self.settings.has_zoho_credentials:
            self.logger.info("Step 5.5: SKIPPED - no NIP available for Zoho lookup")
        
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
    
    def _match_placowka_to_zoho(
        self,
        placowka: Placowka,
        zoho_locations: list,
    ):
        """
        Dopasowuje placówkę do rekordu Zoho po adresie.
        
        Algorytm:
        1. Jeśli tylko 1 rekord w Zoho -> użyj go
        2. Porównaj ulicę i miasto (znormalizowane)
        3. Jeśli brak dopasowania -> weź siedzibę (is_siedziba=True)
        """
        from .models import ZohoMatch
        
        if not zoho_locations:
            return None
        
        # Tylko 1 rekord w Zoho - użyj go
        if len(zoho_locations) == 1:
            return zoho_locations[0]
        
        # Normalizuj adres placówki
        placowka_ulica = (placowka.adres.ulica or "").lower().strip()
        placowka_miasto = (placowka.adres.miasto or "").lower().strip()
        
        # Usuń "ul." z nazwy ulicy
        for prefix in ["ul.", "ul ", "ulica "]:
            if placowka_ulica.startswith(prefix):
                placowka_ulica = placowka_ulica[len(prefix):].strip()
                break
        
        # Szukaj dopasowania po adresie
        best_match = None
        best_score = 0
        
        for zoho_loc in zoho_locations:
            score = 0
            
            # Sprawdź nazwę - czy zawiera ulicę lub miasto
            zoho_name = (zoho_loc.zoho_name or "").lower()
            
            if placowka_miasto and placowka_miasto in zoho_name:
                score += 10
            
            if placowka_ulica:
                # Sprawdź czy ulica jest w nazwie (np. "Klinika OT.CO Bartycka")
                ulica_core = placowka_ulica.split()[0] if placowka_ulica else ""
                if ulica_core and len(ulica_core) > 3 and ulica_core in zoho_name:
                    score += 20
            
            # Priorytet: siedziba
            if zoho_loc.is_siedziba and not zoho_loc.is_filia:
                score += 5  # Mały bonus dla siedziby
            
            if score > best_score:
                best_score = score
                best_match = zoho_loc
        
        # Jeśli brak dopasowania - weź siedzibę
        if not best_match:
            siedziby = [z for z in zoho_locations if z.is_siedziba and not z.is_filia]
            if siedziby:
                return siedziby[0]
            # Fallback - pierwszy rekord
            return zoho_locations[0]
        
        return best_match
    
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
    
    async def _normalize_and_name_placowki_async(
        self, 
        result, 
        page_title: str = "",
        page_text: str = "",
    ) -> None:
        """
        Normalizuje dane i generuje nazwy placówek z użyciem AI.
        
        1. Maile -> małe litery
        2. Nazwy -> WIELKIE LITERY
        3. Wyciąga BRAND NAME przez AI (słowo klucz marketingowe)
        4. Generuje nazwa_placowki: [BRAND] [MIASTO] [ULICA]
        """
        import re
        
        # Normalizuj nazwy firmy na WIELKIE LITERY
        if result.nazwa_pelna:
            result.nazwa_pelna = result.nazwa_pelna.upper()
        
        # === WYCIĄGNIJ BRAND NAME PRZEZ AI ===
        # To jest słowo klucz którym placówka się reklamuje (np. ALDENT, OTCO, MEDICOVER)
        brand_name = await self.ai_categorizer.extract_brand_name(
            full_name=result.nazwa_pelna or "",
            page_title=page_title,
            page_text=page_text[:500] if page_text else None,
        )
        
        if brand_name:
            result.nazwa_zwyczajowa = brand_name.upper()
            self.logger.info("Brand name extracted: '%s'", brand_name)
        elif result.nazwa_zwyczajowa:
            result.nazwa_zwyczajowa = result.nazwa_zwyczajowa.upper()
        
        # Użyj brand name lub fallback
        short_company = brand_name or self._get_short_company_name(result.nazwa_pelna or "")
        
        # Normalizuj adres siedziby do porównania
        siedziba_key = self._normalize_address_key(result.adres_siedziby) if result.adres_siedziby else None
        
        # Flaga czy znaleźliśmy siedzibę
        siedziba_found = False
        
        for placowka in result.placowki:
            # === 1. Normalizuj maile na małe litery ===
            for kontakt in placowka.kontakty:
                if kontakt.typ == "email" and kontakt.wartosc:
                    kontakt.wartosc = kontakt.wartosc.lower()
            
            # === 2. Określ czy to siedziba ===
            placowka_key = self._normalize_address_key(placowka.adres)
            
            if siedziba_key and placowka_key and not siedziba_found:
                # Porównaj ulicę i miasto
                if self._addresses_match(siedziba_key, placowka_key):
                    placowka.is_siedziba = True
                    siedziba_found = True
                    self.logger.info("Siedziba found: %s", placowka.adres.ulica or placowka.adres.miasto)
            
            # === 3. Generuj nazwa_placowki: [BRAND] [MIASTO] [ULICA] ===
            miasto = (placowka.adres.miasto or "").upper()
            
            # Wyciągnij tylko nazwę ulicy (bez numeru)
            ulica_raw = placowka.adres.ulica or ""
            # Usuń numer z ulicy: "Bartycka 24B/U1" -> "Bartycka"
            ulica_match = re.match(r"^(?:ul\.?\s*)?([A-Za-zżźćńółęąśŻŹĆĄŚĘÓŁŃ\s\-\"]+)", ulica_raw, re.IGNORECASE)
            ulica = ulica_match.group(1).strip().upper() if ulica_match else ulica_raw.upper()
            
            # Składaj nazwę: ALDENT WROCŁAW ARBUZOWA
            parts = [short_company, miasto, ulica]
            placowka.nazwa_placowki = " ".join(p for p in parts if p).strip()
        
        # Jeśli nie znaleźliśmy siedziby, pierwsza placówka to siedziba
        if not siedziba_found and result.placowki:
            result.placowki[0].is_siedziba = True
            self.logger.info("Siedziba assigned to first placowka: %s", result.placowki[0].nazwa_placowki)
    
    def _get_short_company_name(self, full_name: str) -> str:
        """Wyciąga krótką nazwę firmy bez 'SP. Z O.O.' itp."""
        if not full_name:
            return ""
        
        # Usuń typowe sufiksy
        import re
        name = full_name.upper()
        
        # Usuń sufiksy prawne
        patterns = [
            r"\s*SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ\s*$",
            r"\s*SP\.?\s*Z\s*O\.?O\.?\s*$",
            r"\s*S\.?A\.?\s*$",
            r"\s*SP\.?\s*J\.?\s*$",
            r"\s*SP\.?\s*K\.?\s*$",
        ]
        for pattern in patterns:
            name = re.sub(pattern, "", name, flags=re.IGNORECASE)
        
        # Weź pierwsze słowo/słowa (max 20 znaków)
        name = name.strip()
        if len(name) > 25:
            # Spróbuj wyciągnąć główną nazwę
            # np. "KLINIKA OSIPOWICZ & TURKOWSKI" -> "OTCO" (jeśli mamy)
            # Na razie bierzemy pierwsze słowo
            words = name.split()
            if words:
                name = words[0]
        
        return name.strip()
    
    def _normalize_address_key(self, adres) -> dict:
        """Normalizuje adres do porównania."""
        if not adres:
            return {}
        
        ulica = (adres.ulica or "").lower().strip()
        miasto = (adres.miasto or "").lower().strip()
        
        # Usuń "ul." z ulicy
        for prefix in ["ul.", "ul ", "ulica "]:
            if ulica.startswith(prefix):
                ulica = ulica[len(prefix):].strip()
                break
        
        return {"ulica": ulica, "miasto": miasto}
    
    def _addresses_match(self, addr1: dict, addr2: dict) -> bool:
        """Sprawdza czy dwa adresy pasują do siebie."""
        if not addr1 or not addr2:
            return False
        
        miasto1 = addr1.get("miasto", "")
        miasto2 = addr2.get("miasto", "")
        ulica1 = addr1.get("ulica", "")
        ulica2 = addr2.get("ulica", "")
        
        # Miasto musi się zgadzać
        if miasto1 and miasto2 and miasto1 != miasto2:
            return False
        
        # Ulica - sprawdź czy jedna zawiera drugą (bo numery mogą się różnić)
        if ulica1 and ulica2:
            # Wyciągnij tylko nazwę ulicy (bez numeru)
            import re
            name1 = re.match(r"^([a-ząćęłńóśźż\s\-\"]+)", ulica1, re.IGNORECASE)
            name2 = re.match(r"^([a-ząćęłńóśźż\s\-\"]+)", ulica2, re.IGNORECASE)
            
            if name1 and name2:
                n1 = name1.group(1).strip().lower()
                n2 = name2.group(1).strip().lower()
                return n1 == n2 or n1 in n2 or n2 in n1
        
        return False
    
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
    
    async def analyze_chaotic(
        self,
        raw_text: str,
        skip_zoho: bool = False,
        skip_search: bool = False,
        full_analysis: bool = True,
    ) -> tuple[Optional[CompanyIntel], DecisionTrace]:
        """
        Analizuje firmę na podstawie chaotycznego tekstu wejściowego.
        
        NOWA ŚCIEŻKA dla danych typu:
        - "Aldent Wrocław 8941864949"
        - "klinikaambroziak.pl"
        - "Medyczna Gdynia stomatolog"
        
        Workflow:
        1. AI parsuje tekst → wydobywa NIP/WWW/nazwa/miasto
        2. Router wybiera najtańszą metodę (Zoho → GUS → scrape → search)
        3. Scoring i decyzja (ACCEPT/SUSPECT/REJECT)
        4. Opcjonalnie: pełna analiza (social, recenzje)
        
        Args:
            raw_text: Surowy tekst wejściowy
            skip_zoho: Pomiń Zoho lookup (do testów)
            skip_search: Pomiń search (do testów)
            full_analysis: Czy wykonać pełną analizę po znalezieniu NIP/WWW
        
        Returns:
            Tuple (CompanyIntel lub None, DecisionTrace z pełnym śladem)
        """
        self.logger.info("=" * 60)
        self.logger.info("ANALYZE CHAOTIC: '%s'", raw_text[:100])
        self.logger.info("=" * 60)
        
        # Krok 1: Router przetwarza chaotyczne dane
        trace = await self.chaotic_router.process(
            raw_text=raw_text,
            skip_zoho=skip_zoho,
            skip_search=skip_search,
        )
        
        self.logger.info(
            "[CHAOTIC] Router result: nip=%s (%s), website=%s, steps=%d, cost=$%.4f",
            trace.final_nip,
            trace.final_nip_decision.value if trace.final_nip_decision else "?",
            trace.final_website,
            len(trace.steps),
            trace.total_cost_usd,
        )
        
        # Krok 2: Jeśli nie znaleziono NIP ani WWW - zwróć tylko trace
        if not trace.final_nip and not trace.final_website:
            self.logger.warning("[CHAOTIC] No NIP or website found")
            return None, trace
        
        # Krok 3: Jeśli full_analysis=False - zwróć minimalny wynik
        if not full_analysis:
            # Stwórz minimalny CompanyIntel
            result = CompanyIntel(
                nip=trace.final_nip,
                social_media=SocialMediaLinks(website=trace.final_website),
                metadata=Metadata(
                    sources_used=["chaotic_router"],
                    processing_time_ms=trace.total_duration_ms,
                    cost_usd=trace.total_cost_usd,
                ),
            )
            
            # Dodaj dane z GUS jeśli dostępne
            accepted = trace.get_accepted_nip()
            if accepted:
                result.nazwa_pelna = accepted.gus_name
                if accepted.gus_city or accepted.gus_street:
                    from .models import Adres
                    result.adres_siedziby = Adres(
                        ulica=accepted.gus_street,
                        miasto=accepted.gus_city,
                    )
            
            return result, trace
        
        # Krok 4: Pełna analiza (używając istniejących metod)
        # Wyciągnij dane z trace
        nip = trace.final_nip
        website = trace.final_website
        
        # Wyciągnij nazwę i miasto z parsed input lub GUS
        company_name = None
        city = None
        
        if trace.input_parsed:
            company_name = trace.input_parsed.name
            city = trace.input_parsed.city
        
        accepted = trace.get_accepted_nip()
        if accepted:
            if accepted.gus_name and not company_name:
                company_name = accepted.gus_name
            if accepted.gus_city and not city:
                city = accepted.gus_city
        
        self.logger.info(
            "[CHAOTIC] Starting full analysis: nip=%s, website=%s, name=%s, city=%s",
            nip,
            website,
            company_name[:40] if company_name else "?",
            city,
        )
        
        # Użyj istniejącej metody analyze
        if nip:
            result = await self.analyze_by_nip(
                nip=nip,
                skip_social=False,
                skip_ai=False,
                skip_reviews=False,
            )
        else:
            result = await self.analyze(
                company_name=company_name,
                city=city,
                website=website,
                skip_social=False,
                skip_ai=False,
                skip_reviews=False,
            )
        
        # Dodaj info o chaotic router do metadata
        result.metadata.sources_used.insert(0, "chaotic_router")
        result.metadata.cost_usd += trace.total_cost_usd
        
        return result, trace
    
    async def close(self) -> None:
        """Zamyka wszystkie zasoby."""
        await self.website_scraper.close()
        await self.google_maps_scraper.close()
        await self.facebook_scraper.close()
        await self.instagram_scraper.close()
        await self.tiktok_scraper.close()
        await self.ai_categorizer.close()
        await self.nip_lookup.close()
        if self.nip_finder_v3:
            await self.nip_finder_v3.close()
