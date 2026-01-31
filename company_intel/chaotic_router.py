"""
ChaoticDataRouter - główny router dla chaotycznych danych.

Łączy wszystkie komponenty:
- AI Parser (Vertex AI)
- Query Builder
- Candidate Scorer
- Metody wyszukiwania (Zoho, GUS, NIPFinderV3, Google Search)

Drabinka metod (tanie → drogie):
1. Parse chaotic text (AI)
2. If NIP detected → checksum → GUS
3. If phone/email/domain → Zoho lookup (FIRST!)
4. If website → scrape for NIP
5. If name+city → search (Google/Brave)
"""

import asyncio
import logging
import time
from typing import Optional, TYPE_CHECKING

from .models import (
    ChaoticLeadParsed,
    SignalStrength,
    NIPCandidate,
    DecisionTrace,
    StrategyStep,
    CandidateDecision,
)
from .query_builder import QueryBuilder
from .candidate_scorer import CandidateScorer, validate_nip_checksum

if TYPE_CHECKING:
    from .config import CompanyIntelSettings
    from .nip_lookup import NIPLookup
    from .scrapers.zoho_lookup import ZohoLookupScraper

logger = logging.getLogger(__name__)


class ChaoticDataRouter:
    """
    Router dla chaotycznych danych wejściowych.
    
    Wybiera optymalną ścieżkę wyszukiwania NIP i WWW
    na podstawie dostępnych sygnałów.
    """
    
    def __init__(
        self,
        settings: "CompanyIntelSettings",
        nip_lookup: Optional["NIPLookup"] = None,
        zoho_lookup: Optional["ZohoLookupScraper"] = None,
        nip_finder_v3=None,
        vertex_ai_service=None,
    ):
        """
        Args:
            settings: Ustawienia Company Intel
            nip_lookup: Serwis do lookup NIP w GUS
            zoho_lookup: Serwis do lookup w Zoho
            nip_finder_v3: Pełny NIPFinderV3 (8-poziomowa kaskada)
            vertex_ai_service: Serwis Vertex AI do parsowania
        """
        self.settings = settings
        self.nip_lookup = nip_lookup
        self.zoho_lookup = zoho_lookup
        self.nip_finder_v3 = nip_finder_v3
        self.vertex_ai = vertex_ai_service
        
        self.query_builder = QueryBuilder(max_queries=5)
        self.scorer = CandidateScorer()
        
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def process(
        self,
        raw_text: str,
        skip_zoho: bool = False,
        skip_search: bool = False,
    ) -> DecisionTrace:
        """
        Przetwarza chaotyczny tekst i znajduje NIP/WWW.
        
        Args:
            raw_text: Surowy tekst wejściowy (np. "Aldent Wrocław 8941864949")
            skip_zoho: Pomiń lookup Zoho (do testów)
            skip_search: Pomiń wyszukiwanie Google/Brave (do testów)
        
        Returns:
            DecisionTrace z pełnym śladem decyzji
        """
        start_time = time.time()
        
        trace = DecisionTrace(input_raw=raw_text)
        
        self.logger.info("=" * 60)
        self.logger.info("[CHAOTIC_ROUTER] Processing: '%s'", raw_text[:100])
        self.logger.info("=" * 60)
        
        # === KROK 0: AI Parsing ===
        parsed = await self._parse_input(raw_text, trace)
        if not parsed:
            self.logger.warning("[CHAOTIC_ROUTER] Failed to parse input")
            trace.total_duration_ms = int((time.time() - start_time) * 1000)
            return trace
        
        trace.input_parsed = parsed
        
        self.logger.info(
            "[CHAOTIC_ROUTER] Parsed signals: nip=%s, website=%s, phone=%s, email=%s, name=%s, city=%s, strongest=%s",
            parsed.nip,
            parsed.website,
            parsed.phone,
            parsed.email,
            parsed.name,
            parsed.city,
            parsed.strongest_signal.value if parsed.strongest_signal else None,
        )
        
        # === KROK 1: Jeśli NIP wykryty → checksum → GUS ===
        if parsed.nip:
            candidate = await self._process_nip(parsed, trace)
            if candidate and candidate.decision == CandidateDecision.ACCEPT:
                trace.final_nip = candidate.nip
                trace.final_nip_decision = candidate.decision
                # Szukaj WWW dla zaakceptowanego NIP
                if not parsed.website:
                    await self._find_website_for_nip(parsed, candidate, trace)
                else:
                    trace.final_website = parsed.website
                trace.total_duration_ms = int((time.time() - start_time) * 1000)
                return trace
        
        # === KROK 2: Jeśli phone/email/domain → Zoho (FIRST!) ===
        if not skip_zoho and (parsed.phone or parsed.email or parsed.website):
            zoho_result = await self._lookup_zoho(parsed, trace)
            if zoho_result:
                # Zoho znalazł NIP → waliduj przez GUS
                candidate = await self._validate_zoho_nip(zoho_result, parsed, trace)
                if candidate and candidate.decision == CandidateDecision.ACCEPT:
                    trace.final_nip = candidate.nip
                    trace.final_nip_decision = candidate.decision
                    if not trace.final_website:
                        trace.final_website = parsed.website
                    trace.total_duration_ms = int((time.time() - start_time) * 1000)
                    return trace
        
        # === KROK 3: Jeśli website → scrape NIP ===
        if parsed.website:
            scraped_nip = await self._scrape_website_for_nip(parsed, trace)
            if scraped_nip:
                candidate = await self._validate_scraped_nip(scraped_nip, parsed, trace)
                if candidate and candidate.decision == CandidateDecision.ACCEPT:
                    trace.final_nip = candidate.nip
                    trace.final_nip_decision = candidate.decision
                    trace.final_website = parsed.website
                    trace.total_duration_ms = int((time.time() - start_time) * 1000)
                    return trace
        
        # === KROK 4: Search (Google/Brave) - name+city ===
        if not skip_search and parsed.has_name():
            search_candidate = await self._search_for_nip(parsed, trace)
            if search_candidate and search_candidate.decision == CandidateDecision.ACCEPT:
                trace.final_nip = search_candidate.nip
                trace.final_nip_decision = search_candidate.decision
                trace.total_duration_ms = int((time.time() - start_time) * 1000)
                return trace
        
        # === Fallback: najlepszy SUSPECT ===
        best_suspect = self._get_best_suspect(trace)
        if best_suspect:
            trace.final_nip = best_suspect.nip
            trace.final_nip_decision = best_suspect.decision
            self.logger.info(
                "[CHAOTIC_ROUTER] No ACCEPT, using best SUSPECT: %s",
                best_suspect.nip,
            )
        else:
            self.logger.warning("[CHAOTIC_ROUTER] No NIP found")
        
        trace.total_duration_ms = int((time.time() - start_time) * 1000)
        
        self.logger.info(
            "[CHAOTIC_ROUTER] DONE: nip=%s (%s), website=%s, duration=%dms, cost=$%.4f",
            trace.final_nip,
            trace.final_nip_decision.value if trace.final_nip_decision else "?",
            trace.final_website,
            trace.total_duration_ms,
            trace.total_cost_usd,
        )
        
        return trace
    
    async def _parse_input(
        self,
        raw_text: str,
        trace: DecisionTrace,
    ) -> Optional[ChaoticLeadParsed]:
        """Parsuje surowy tekst przez AI."""
        step_start = time.time()
        
        step = StrategyStep(
            step_name="AI Parse",
            method="vertex_ai.parse_chaotic_lead",
        )
        
        parsed_dict = None
        
        try:
            if self.vertex_ai:
                try:
                    parsed_dict = await self.vertex_ai.parse_chaotic_lead(raw_text)
                except Exception as e:
                    self.logger.warning("[CHAOTIC_ROUTER] AI parse failed, using fallback: %s", str(e)[:50])
                    # Fallback do mocka przy błędzie AI
                    parsed_dict = None
            
            # Fallback - prosty regex parser (gdy AI nie działa lub zwrócił None)
            if not parsed_dict:
                from src.services.vertex_ai import VertexAIServiceMock
                mock = VertexAIServiceMock()
                parsed_dict = await mock.parse_chaotic_lead(raw_text)
                step.method = "regex_fallback"
            
            if not parsed_dict:
                step.skipped = True
                step.skip_reason = "AI returned None"
                trace.add_step(step)
                return None
            
            # Konwertuj na model
            strongest = parsed_dict.get("strongest_signal")
            if strongest:
                try:
                    strongest = SignalStrength(strongest)
                except ValueError:
                    strongest = None
            
            parsed = ChaoticLeadParsed(
                raw_text=raw_text,
                nip=parsed_dict.get("nip"),
                regon=parsed_dict.get("regon"),
                krs=parsed_dict.get("krs"),
                website=parsed_dict.get("website"),
                email=parsed_dict.get("email"),
                phone=parsed_dict.get("phone"),
                city=parsed_dict.get("city"),
                street=parsed_dict.get("street"),
                name=parsed_dict.get("name"),
                short_name=parsed_dict.get("short_name"),
                keywords=parsed_dict.get("keywords", []),
                confidence=parsed_dict.get("confidence", 0.5),
                strongest_signal=strongest,
            )
            
            step.results_count = 1
            step.duration_ms = int((time.time() - step_start) * 1000)
            # AI parsing koszt ~$0.001
            step.cost_usd = 0.001
            trace.add_step(step)
            
            return parsed
            
        except Exception as e:
            self.logger.error("[CHAOTIC_ROUTER] Parse error: %s", e)
            step.skipped = True
            step.skip_reason = str(e)
            step.duration_ms = int((time.time() - step_start) * 1000)
            trace.add_step(step)
            return None
    
    async def _process_nip(
        self,
        parsed: ChaoticLeadParsed,
        trace: DecisionTrace,
    ) -> Optional[NIPCandidate]:
        """Przetwarza wykryty NIP: checksum → GUS."""
        step_start = time.time()
        
        step = StrategyStep(
            step_name="NIP Validation",
            method="checksum + gus",
        )
        
        nip = parsed.nip
        
        # 1. Checksum
        if not validate_nip_checksum(nip):
            self.logger.warning("[CHAOTIC_ROUTER] NIP %s: checksum FAIL", nip)
            candidate = self.scorer.create_candidate(nip)
            candidate.decision = CandidateDecision.REJECT
            candidate.decision_reason = "Invalid checksum"
            trace.nip_candidates.append(candidate)
            
            step.candidates_found = 1
            step.duration_ms = int((time.time() - step_start) * 1000)
            trace.add_step(step)
            return candidate
        
        self.logger.info("[CHAOTIC_ROUTER] NIP %s: checksum OK", nip)
        
        # 2. GUS lookup
        gus_found = False
        gus_name = None
        gus_city = None
        gus_street = None
        
        if self.nip_lookup:
            try:
                lookup_result = await self.nip_lookup.lookup(nip)
                gus_found = lookup_result.found
                
                if gus_found and lookup_result.gus_data:
                    gus = lookup_result.gus_data
                    gus_name = gus.full_name
                    gus_city = gus.city
                    gus_street = gus.street
                    
                    self.logger.info(
                        "[CHAOTIC_ROUTER] NIP %s: GUS found '%s' (%s)",
                        nip,
                        gus_name[:40] if gus_name else "?",
                        gus_city,
                    )
            except Exception as e:
                self.logger.warning("[CHAOTIC_ROUTER] GUS lookup failed: %s", e)
        
        # 3. Scoring
        candidate = self.scorer.score_and_decide(
            nip=nip,
            gus_found=gus_found,
            gus_name=gus_name,
            gus_city=gus_city,
            gus_street=gus_street,
            input_name=parsed.name,
        )
        
        trace.nip_candidates.append(candidate)
        
        step.candidates_found = 1
        step.best_candidate = nip
        step.duration_ms = int((time.time() - step_start) * 1000)
        # GUS lookup ~$0.001
        step.cost_usd = 0.001 if gus_found else 0.0
        trace.add_step(step)
        
        return candidate
    
    async def _lookup_zoho(
        self,
        parsed: ChaoticLeadParsed,
        trace: DecisionTrace,
    ) -> Optional[str]:
        """Lookup NIP w Zoho po phone/email/domain."""
        step_start = time.time()
        
        step = StrategyStep(
            step_name="Zoho Lookup",
            method="zoho.find_nip_by_website_data",
        )
        
        if not self.zoho_lookup:
            step.skipped = True
            step.skip_reason = "Zoho not configured"
            trace.add_step(step)
            return None
        
        try:
            keys = self.query_builder.build_zoho_search_keys(parsed)
            
            zoho_nip = await self.zoho_lookup.find_nip_by_website_data(
                domain=keys["domain"],
                phones=[keys["phone"]] if keys["phone"] else [],
                email_domains=[keys["domain"]] if keys["domain"] else [],
            )
            
            if zoho_nip:
                self.logger.info("[CHAOTIC_ROUTER] Zoho HIT: NIP %s", zoho_nip)
                step.candidates_found = 1
                step.best_candidate = zoho_nip
                step.results_count = 1
            else:
                self.logger.debug("[CHAOTIC_ROUTER] Zoho: no match")
            
            step.duration_ms = int((time.time() - step_start) * 1000)
            # Zoho = FREE
            step.cost_usd = 0.0
            trace.add_step(step)
            
            return zoho_nip
            
        except Exception as e:
            self.logger.warning("[CHAOTIC_ROUTER] Zoho lookup failed: %s", e)
            step.skipped = True
            step.skip_reason = str(e)
            step.duration_ms = int((time.time() - step_start) * 1000)
            trace.add_step(step)
            return None
    
    async def _validate_zoho_nip(
        self,
        nip: str,
        parsed: ChaoticLeadParsed,
        trace: DecisionTrace,
    ) -> Optional[NIPCandidate]:
        """Waliduje NIP znaleziony w Zoho przez GUS."""
        step_start = time.time()
        
        step = StrategyStep(
            step_name="Validate Zoho NIP",
            method="checksum + gus",
        )
        
        # Checksum
        if not validate_nip_checksum(nip):
            step.skipped = True
            step.skip_reason = "Invalid checksum"
            trace.add_step(step)
            return None
        
        # GUS
        gus_found = False
        gus_name = None
        gus_city = None
        
        if self.nip_lookup:
            try:
                lookup_result = await self.nip_lookup.lookup(nip)
                gus_found = lookup_result.found
                if gus_found and lookup_result.gus_data:
                    gus_name = lookup_result.gus_data.full_name
                    gus_city = lookup_result.gus_data.city
            except Exception as e:
                self.logger.warning("[CHAOTIC_ROUTER] GUS validation failed: %s", e)
        
        # Scoring - dodaj bonus za Zoho
        candidate = self.scorer.score_and_decide(
            nip=nip,
            gus_found=gus_found,
            gus_name=gus_name,
            gus_city=gus_city,
            input_name=parsed.name,
            zoho_found=True,
            zoho_name=gus_name,
        )
        
        trace.nip_candidates.append(candidate)
        
        step.candidates_found = 1
        step.best_candidate = nip
        step.duration_ms = int((time.time() - step_start) * 1000)
        step.cost_usd = 0.001
        trace.add_step(step)
        
        return candidate
    
    async def _scrape_website_for_nip(
        self,
        parsed: ChaoticLeadParsed,
        trace: DecisionTrace,
    ) -> Optional[str]:
        """Scrapuje stronę WWW w poszukiwaniu NIP."""
        step_start = time.time()
        
        step = StrategyStep(
            step_name="Scrape Website",
            method="nip_finder_v3.privacy_scraper",
        )
        
        if not self.nip_finder_v3:
            step.skipped = True
            step.skip_reason = "NIPFinderV3 not available"
            trace.add_step(step)
            return None
        
        try:
            # Użyj NIPFinderV3 który ma wbudowany scraper
            # Tworzymy fake company name z website
            domain = parsed.website
            if domain.startswith("http"):
                from urllib.parse import urlparse
                domain = urlparse(domain).netloc
            domain = domain.replace("www.", "")
            
            fake_email = f"info@{domain}"
            
            result = await self.nip_finder_v3.find_nip(
                company_name=parsed.name or domain,
                city=parsed.city,
                email=fake_email,
                skip_cache=True,
            )
            
            if result and result.found and result.nip:
                self.logger.info(
                    "[CHAOTIC_ROUTER] Website scrape: found NIP %s via %s",
                    result.nip,
                    result.strategy_used.value if result.strategy_used else "?",
                )
                step.candidates_found = 1
                step.best_candidate = result.nip
                step.results_count = 1
                step.duration_ms = int((time.time() - step_start) * 1000)
                # NIPFinderV3 cost varies
                step.cost_usd = 0.005
                trace.add_step(step)
                return result.nip
            
            step.duration_ms = int((time.time() - step_start) * 1000)
            step.cost_usd = 0.002
            trace.add_step(step)
            return None
            
        except Exception as e:
            self.logger.warning("[CHAOTIC_ROUTER] Website scrape failed: %s", e)
            step.skipped = True
            step.skip_reason = str(e)
            step.duration_ms = int((time.time() - step_start) * 1000)
            trace.add_step(step)
            return None
    
    async def _validate_scraped_nip(
        self,
        nip: str,
        parsed: ChaoticLeadParsed,
        trace: DecisionTrace,
    ) -> Optional[NIPCandidate]:
        """Waliduje NIP znaleziony przez scraping."""
        step_start = time.time()
        
        step = StrategyStep(
            step_name="Validate Scraped NIP",
            method="checksum + gus + domain",
        )
        
        # Checksum
        if not validate_nip_checksum(nip):
            step.skipped = True
            step.skip_reason = "Invalid checksum"
            trace.add_step(step)
            return None
        
        # GUS
        gus_found = False
        gus_name = None
        gus_city = None
        
        if self.nip_lookup:
            try:
                lookup_result = await self.nip_lookup.lookup(nip)
                gus_found = lookup_result.found
                if gus_found and lookup_result.gus_data:
                    gus_name = lookup_result.gus_data.full_name
                    gus_city = lookup_result.gus_data.city
            except Exception:
                pass
        
        # Scoring - dodaj bonus za NIP na domenie
        domain = parsed.website
        if domain and domain.startswith("http"):
            from urllib.parse import urlparse
            domain = urlparse(domain).netloc
        
        candidate = self.scorer.score_and_decide(
            nip=nip,
            gus_found=gus_found,
            gus_name=gus_name,
            gus_city=gus_city,
            input_name=parsed.name,
            nip_on_domain=True,
            domain=domain,
        )
        
        trace.nip_candidates.append(candidate)
        
        step.candidates_found = 1
        step.best_candidate = nip
        step.duration_ms = int((time.time() - step_start) * 1000)
        step.cost_usd = 0.001
        trace.add_step(step)
        
        return candidate
    
    async def _search_for_nip(
        self,
        parsed: ChaoticLeadParsed,
        trace: DecisionTrace,
    ) -> Optional[NIPCandidate]:
        """Szuka NIP przez Google/Brave search."""
        step_start = time.time()
        
        step = StrategyStep(
            step_name="Search for NIP",
            method="nip_finder_v3.google_search",
        )
        
        if not self.nip_finder_v3:
            step.skipped = True
            step.skip_reason = "NIPFinderV3 not available"
            trace.add_step(step)
            return None
        
        try:
            # Buduj zapytania
            queries = self.query_builder.build_nip_search_queries(parsed)
            
            if not queries:
                step.skipped = True
                step.skip_reason = "No search queries generated"
                trace.add_step(step)
                return None
            
            step.query = queries[0].query  # Loguj pierwsze zapytanie
            
            # Użyj NIPFinderV3 (ma wbudowany Google Search + AI validation)
            result = await self.nip_finder_v3.find_nip(
                company_name=parsed.name or parsed.short_name,
                city=parsed.city,
                skip_cache=True,
            )
            
            if result and result.found and result.nip:
                self.logger.info(
                    "[CHAOTIC_ROUTER] Search: found NIP %s via %s",
                    result.nip,
                    result.strategy_used.value if result.strategy_used else "?",
                )
                
                # Waliduj przez GUS
                gus_found = False
                gus_name = None
                
                if self.nip_lookup:
                    try:
                        lookup = await self.nip_lookup.lookup(result.nip)
                        gus_found = lookup.found
                        if gus_found and lookup.gus_data:
                            gus_name = lookup.gus_data.full_name
                    except Exception:
                        pass
                
                candidate = self.scorer.score_and_decide(
                    nip=result.nip,
                    gus_found=gus_found,
                    gus_name=gus_name,
                    input_name=parsed.name,
                    source_url=result.source_url if hasattr(result, 'source_url') else None,
                )
                
                trace.nip_candidates.append(candidate)
                
                step.candidates_found = 1
                step.best_candidate = result.nip
                step.results_count = 1
                step.duration_ms = int((time.time() - step_start) * 1000)
                step.cost_usd = 0.01  # Search + AI validation
                trace.add_step(step)
                
                return candidate
            
            step.duration_ms = int((time.time() - step_start) * 1000)
            step.cost_usd = 0.005
            trace.add_step(step)
            return None
            
        except Exception as e:
            self.logger.warning("[CHAOTIC_ROUTER] Search failed: %s", e)
            step.skipped = True
            step.skip_reason = str(e)
            step.duration_ms = int((time.time() - step_start) * 1000)
            trace.add_step(step)
            return None
    
    async def _find_website_for_nip(
        self,
        parsed: ChaoticLeadParsed,
        candidate: NIPCandidate,
        trace: DecisionTrace,
    ) -> None:
        """Szuka strony WWW dla zaakceptowanego NIP."""
        step_start = time.time()
        
        step = StrategyStep(
            step_name="Find Website",
            method="search",
        )
        
        # Buduj zapytania
        queries = self.query_builder.build_website_search_queries(
            parsed,
            gus_name=candidate.gus_name,
            gus_city=candidate.gus_city,
        )
        
        if not queries:
            step.skipped = True
            step.skip_reason = "No queries"
            trace.add_step(step)
            return
        
        step.query = queries[0].query
        
        # TODO: Implementacja wyszukiwania WWW
        # Na razie placeholder - zostawiamy bez WWW
        
        step.duration_ms = int((time.time() - step_start) * 1000)
        trace.add_step(step)
    
    def _get_best_suspect(self, trace: DecisionTrace) -> Optional[NIPCandidate]:
        """Zwraca najlepszego kandydata ze statusem SUSPECT."""
        suspects = [
            c for c in trace.nip_candidates
            if c.decision == CandidateDecision.SUSPECT
        ]
        
        if not suspects:
            return None
        
        # Sortuj po total_score
        return max(suspects, key=lambda c: c.total_score)
