"""
Google Search Strategy - wyszukuje NIP przez Google Search (Apify lub JSON API).

Google Search provides:
- Best search results for Polish companies
- Structured data (snippets, URLs)
- Higher accuracy than Brave
- Cost: $0.005-0.01/query

Success rate: 80-85%
"""

import asyncio
import logging
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from ..ai.validator import AIValidator
from ..config import NIPFinderV3Settings, get_settings
from ..models import NIPResult, NIPCandidate, SearchStrategy
from ..utils import (
    calculate_name_match_score,
    extract_company_base_name,
    extract_nip_from_text,
    format_nip,
)
from .base import BaseStrategy

logger = logging.getLogger(__name__)


class GoogleSearchStrategy(BaseStrategy):
    """
    Google Search Strategy.

    Uses Apify Google Search Actor or Google Custom Search JSON API.
    Extracts NIP from search result snippets (no need to scrape URLs).
    """

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()
        self._apify_client = None
        self._apify_initialized = False
        self._ai_validator = AIValidator(self.settings) if self.settings.enable_ai_semantic_validation else None

    def _init_apify(self) -> bool:
        """Initialize Apify client (lazy)."""
        if self._apify_initialized:
            return self._apify_client is not None

        try:
            from apify_client import ApifyClient

            if not self.settings.apify_api_token:
                logger.warning("Google Search: brak Apify API token")
                self._apify_initialized = True
                return False

            self._apify_client = ApifyClient(self.settings.apify_api_token)
            self._apify_initialized = True
            logger.info("Google Search: Apify client initialized")
            return True

        except ImportError:
            logger.error("Google Search: apify-client not installed - install: pip install apify-client")
            self._apify_initialized = True
            return False
        except Exception as e:
            logger.error("Google Search: Apify init error: %s", e)
            self._apify_initialized = True
            return False

    async def _google_search_apify(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[dict]:
        """
        Execute Google Search via Apify Actor.

        Args:
            query: Search query
            max_results: Max results to return

        Returns:
            List of search results with {title, description, url}
        """
        if not self._init_apify():
            return []

        try:
            logger.info("Google Search (Apify): query='%s'", query)

            # Prepare Actor input
            run_input = {
                "queries": query,  # Single query
                "maxPagesPerQuery": 1,  # Only first page
                "resultsPerPage": max_results,
                "countryCode": self.settings.google_search_country,
                "languageCode": self.settings.google_search_language,
                "mobileResults": False,
                "includeUnfilteredResults": False,
            }

            # Run Actor (synchronous call, runs in thread pool)
            logger.debug("Google Search: running Apify actor %s", self.settings.apify_google_actor_id)

            # Run in thread pool (Apify SDK is sync)
            run = await asyncio.to_thread(
                lambda: self._apify_client.actor(self.settings.apify_google_actor_id).call(
                    run_input=run_input,
                    timeout_secs=self.settings.apify_actor_timeout_sec,
                )
            )

            if run.get("status") != "SUCCEEDED":
                logger.error("Google Search: Actor failed with status %s", run.get("status"))
                return []

            # Get results from dataset
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                logger.error("Google Search: no dataset ID")
                return []

            # Iterate items (sync call)
            items = await asyncio.to_thread(
                lambda: list(self._apify_client.dataset(dataset_id).iterate_items())
            )

            # Extract organic results
            results = []
            for item in items:
                organic_results = item.get("organicResults", [])
                for result in organic_results:
                    results.append({
                        "title": result.get("title", ""),
                        "description": result.get("description", ""),
                        "url": result.get("url", ""),
                    })

            logger.info("Google Search (Apify): found %d results", len(results))
            return results

        except Exception as e:
            logger.error("Google Search (Apify): error: %s", e)
            return []

    async def _google_search_json_api(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[dict]:
        """
        Execute Google Search via Google Custom Search JSON API (fallback).

        Args:
            query: Search query
            max_results: Max results to return

        Returns:
            List of search results with {title, description, url}
        """
        if not self.settings.google_api_key or not self.settings.google_search_engine_id:
            logger.warning("Google Search (JSON API): missing API key or search engine ID")
            return []

        try:
            logger.info("Google Search (JSON API): query='%s'", query)

            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": self.settings.google_api_key,
                "cx": self.settings.google_search_engine_id,
                "q": query,
                "num": min(max_results, 10),  # Max 10 per request
                "gl": self.settings.google_search_country,
                "hl": self.settings.google_search_language,
            }

            async with httpx.AsyncClient(timeout=self.settings.request_timeout_sec) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            # Extract items
            items = data.get("items", [])
            results = []
            for item in items:
                results.append({
                    "title": item.get("title", ""),
                    "description": item.get("snippet", ""),  # Note: JSON API uses "snippet"
                    "url": item.get("link", ""),
                })

            logger.info("Google Search (JSON API): found %d results", len(results))
            return results

        except httpx.HTTPStatusError as e:
            logger.error("Google Search (JSON API): HTTP error %s: %s", e.response.status_code, e)
            return []
        except Exception as e:
            logger.error("Google Search (JSON API): error: %s", e)
            return []

    def _extract_short_name(self, company_name: str) -> Optional[str]:
        """
        Extract short company name from full name.
        
        Examples:
        - "SPA ProBody - masaż Gdańsk, Gdynia, Sopot" -> "ProBody"
        - "Klinika Ambroziak Sp. z o.o." -> "Ambroziak"
        - "ALDENT Wrocław - stomatologia" -> "ALDENT"
        - "Centrum Medyczne ABC" -> "ABC"
        
        Returns the most distinctive word (usually brand name).
        """
        import re
        
        # Remove common suffixes and prefixes
        text = company_name
        
        # Remove legal forms
        text = re.sub(r'\b(sp\.?\s*z\.?\s*o\.?\s*o\.?|spółka|s\.?a\.?|sp\.?\s*j\.?)\b', '', text, flags=re.IGNORECASE)
        
        # Remove common generic words
        generic_words = [
            'centrum', 'medyczne', 'klinika', 'przychodnia', 'gabinet', 'spa', 'salon',
            'stomatologia', 'stomatologiczna', 'stomatologiczny', 'dental', 'dent',
            'masaż', 'masaze', 'massage', 'beauty', 'wellness',
            'poland', 'polska', 'pl', 'com', 'eu',
        ]
        
        # Split by common separators
        parts = re.split(r'[-–—|,;/\\()]|\s+', text)
        
        # Find the most distinctive word (capitalized, not generic, not a city)
        cities = ['warszawa', 'kraków', 'krakow', 'wrocław', 'wroclaw', 'gdańsk', 'gdansk', 
                  'poznań', 'poznan', 'łódź', 'lodz', 'szczecin', 'lublin', 'katowice',
                  'gdynia', 'sopot', 'bydgoszcz', 'białystok', 'bialystok', 'mielec']
        
        candidates = []
        for part in parts:
            part = part.strip()
            if not part or len(part) < 3:
                continue
            
            part_lower = part.lower()
            
            # Skip generic words and cities
            if part_lower in generic_words or part_lower in cities:
                continue
            
            # Skip if all lowercase and short (likely a common word)
            if part.islower() and len(part) < 5:
                continue
            
            # Prefer words that start with uppercase or are all uppercase
            if part[0].isupper() or part.isupper():
                candidates.append(part)
        
        # Return the first candidate (usually the brand name)
        if candidates:
            return candidates[0]
        
        return None

    async def find_nip(
        self,
        company_name: str,
        city: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> NIPResult:
        """
        Find NIP using Google Search.

        Strategy:
        1. Try multiple query variants (optimized for best results)
        2. Extract NIP from search result snippets (descriptions)
        3. If Apify fails, fallback to Google Custom Search JSON API
        4. Return domain from URL if NIP found

        Args:
            company_name: Company name
            city: City (optional)
            domain: Company domain (optional, for verification)

        Returns:
            NIPResult
        """
        logger.info("Google Search: searching NIP for '%s' (%s)", company_name, city or "no city")

        # Extract base name (remove generic words like "centrum medyczne")
        base_name = extract_company_base_name(company_name)
        logger.info("Google Search: base name extracted: '%s' (from '%s')", base_name, company_name)
        
        # Extract short name (first word that looks like company name)
        # "SPA ProBody - masaż Gdańsk" -> "ProBody"
        short_name = self._extract_short_name(company_name)
        logger.info("Google Search: short name extracted: '%s'", short_name)

        # Prepare query list
        queries: list[str] = []

        def add_query(query: str) -> None:
            cleaned = query.strip()
            if cleaned and cleaned not in queries:
                queries.append(cleaned)

        # === STEP 0: Short name + NIP (FASTEST - try first!) ===
        # Simple queries like "ProBody nip" often work best
        if short_name:
            add_query(f'{short_name} nip')
            if city:
                add_query(f'{short_name} {city} nip')
        
        # Also try base_name + NIP early (not just at the end)
        if base_name and base_name != company_name.lower():
            add_query(f'{base_name} nip')

        # === STEP 1: AI-Generated Queries (PRIMARY) ===
        if self._ai_validator:
            try:
                ai_queries = await self._ai_validator.generate_search_queries(
                    company_name=company_name,
                    city=city,
                    domain=domain,
                    max_queries=5,
                )
                for q in ai_queries:
                    add_query(q)
                logger.info("Google Search: AI generated %d queries", len(ai_queries))
            except Exception as e:
                logger.warning("Google Search: AI query generation failed: %s", e)

        # === STEP 2: Static Fallback Queries (SECONDARY) ===
        # These are added after AI queries as backup

        # Variant 1: Full name + city + NIP (MOST SPECIFIC - exact match priority)
        if city:
            add_query(f'"{company_name}" "{city}" NIP')

        # Variant 2: Full name + NIP (exact name, any location)
        add_query(f'"{company_name}" NIP')

        # Variant 3: Full name + city (no NIP keyword - find official site)
        if city:
            add_query(f'"{company_name}" "{city}"')

        # Variant 4: Full name alone (find official site)
        add_query(f'"{company_name}"')

        # Variant 5: Full name (no quotes) + NIP (less strict than quoted)
        if city:
            add_query(f'{company_name} {city} NIP')
        add_query(f'{company_name} NIP')

        # Variant 6: Abbreviation for "centrum medyczne" → "CM" (if present)
        if "centrum medyczne" in company_name:
            cm_name = company_name.replace("centrum medyczne", "cm").strip()
            if city:
                add_query(f'{cm_name} {city} NIP')
            add_query(f'{cm_name} NIP')

        # Variant 7: Base name + city + NIP (FALLBACK - less specific)
        if city and base_name and base_name != company_name.lower():
            add_query(f'{base_name} {city} NIP')

        # Variant 8: Base name + NIP (LAST RESORT)
        if base_name and base_name != company_name.lower():
            add_query(f'{base_name} NIP')

        logger.info("Google Search: trying %d total query variants (AI + static)", len(queries))

        # MULTI-PASS VALIDATION: Collect all NIP candidates, then choose the best
        candidates = []
        rejected_nips = set()  # Track NIPs that were rejected by AI to avoid re-validation

        # Try each query variant
        for i, query in enumerate(queries, 1):
            logger.info("Google Search: variant %d/%d: %s", i, len(queries), query)

            # Try Apify first
            results = await self._google_search_apify(
                query,
                max_results=self.settings.max_google_results,
            )

            # If Apify failed or returned no results, try JSON API as fallback
            if not results:
                logger.info("Google Search: Apify returned no results, trying JSON API fallback")
                results = await self._google_search_json_api(
                    query,
                    max_results=self.settings.max_google_results,
                )

            if not results:
                logger.info("Google Search: variant %d returned no results (both APIs)", i)
                continue

            # Blacklisted domains - aggregators that show NIP of OTHER companies (not the searched one)
            # UWAGA: NIE blacklistuj rejestrów firm (aleo.com, rejestr.io) - one mają poprawne NIP!
            BLACKLISTED_DOMAINS = [
                # Portale z prezentami/voucherami - pokazują NIP sklepu, nie firmy
                'wyjatkowyprezent.pl', 'prezentmarzen.pl', 'groupon.pl', 'groupon.com',
                # Marketplace - pokazują NIP sprzedawcy, nie firmy
                'allegro.pl', 'olx.pl', 'ceneo.pl',
                # Social media - nie mają NIP w snippetach
                'facebook.com', 'instagram.com', 'linkedin.com', 'twitter.com',
                'youtube.com', 'tiktok.com',
                # Turystyka/opinie - nie mają NIP lub pokazują inny
                'tripadvisor.pl', 'tripadvisor.com', 'booking.com', 'yelp.com',
                # Wikipedia/mapy - nie mają NIP
                'wikipedia.org', 'maps.google.com', 'google.com/maps',
            ]
            # DOBRE źródła NIP (NIE na blackliście):
            # aleo.com, rejestr.io, krs-online.com.pl, infoveriti.pl, panoramafirm.pl
            # - pobierają dane z KRS/GUS więc NIP jest poprawny

            # Extract NIP from snippets
            for result in results:
                # Skip blacklisted domains (aggregators, directories)
                result_url = result.get('url', '').lower()
                if any(bl in result_url for bl in BLACKLISTED_DOMAINS):
                    logger.debug("Google Search: SKIP blacklisted domain: %s", result_url[:50])
                    continue

                # Combine title + description
                text = f"{result['title']} {result['description']}"
                nip = extract_nip_from_text(text)

                if not nip:
                    continue

                # Skip if already found this NIP in candidates
                if any(c['nip'] == nip for c in candidates):
                    logger.debug("Google Search: NIP %s already in candidates - skipping", nip)
                    continue

                # Skip if this NIP was already rejected by AI
                if nip in rejected_nips:
                    logger.debug("Google Search: NIP %s was previously rejected - skipping", nip)
                    continue

                # Found NIP!
                logger.info("Google Search: NIP found in snippet (variant %d): %s", i, nip)

                # PRE-FILTER: Fuzzy matching to avoid expensive AI calls
                title = result.get("title", "")
                text_for_match = f"{title} {result.get('description', '')}"
                
                # Use short_name for matching if available (more accurate for brand searches)
                # "ProBody" matches "Probody Clinic" better than full name "SPA ProBody - masaż Gdańsk..."
                name_for_match = short_name if short_name else company_name
                name_match_score = calculate_name_match_score(name_for_match, text_for_match)
                
                # Also check base_name if short_name didn't match well
                if name_match_score < 0.3 and base_name and base_name != name_for_match:
                    base_score = calculate_name_match_score(base_name, text_for_match)
                    if base_score > name_match_score:
                        name_match_score = base_score
                        logger.info("Google Search: Using base_name score: %.2f", base_score)
                
                logger.info("Google Search: Fuzzy match score for '%s' vs '%s': %.2f", 
                           title[:40], name_for_match, name_match_score)

                if name_match_score < 0.15:
                    logger.warning(
                        "Google Search: PRE-FILTER REJECT - name match score %.2f < 0.15 for '%s'",
                        name_match_score,
                        title
                    )
                    continue  # Skip AI validation - obviously wrong company

                # Extract domain from URL if not provided
                discovered_domain = None
                if not domain:
                    url = result.get("url", "")
                    if url:
                        # Extract domain from URL
                        parsed = urlparse(url)
                        discovered_domain = parsed.netloc.replace("www.", "")
                        logger.info("Google Search: discovered domain from URL: %s", discovered_domain)

                # AI SEMANTIC VALIDATION: Verify company identity match
                # SKIP AI if fuzzy match score is very high (obvious match)
                ai_validation_result = None
                if name_match_score >= 0.7:
                    logger.info("Google Search: SKIP AI validation - high match score %.2f (>= 0.7)", name_match_score)
                    ai_validation_result = {"valid": True, "confidence": name_match_score, "reasoning": "High fuzzy match"}
                elif self._ai_validator and self.settings.enable_ai_semantic_validation:
                    logger.info("Google Search: AI validating company identity for NIP %s", nip)

                    source_data = {
                        "title": result.get("title", ""),
                        "description": result.get("description", ""),
                        "url": result.get("url", ""),
                        "found_nip": nip,
                        "query": query,
                    }

                    ai_validation_result = await self._ai_validator.validate_company_identity(
                        company_name=company_name,
                        city=city,
                        nip=nip,
                        source_data=source_data,
                    )

                    logger.info(
                        "Google Search: AI validation result: valid=%s, confidence=%.2f, reasoning='%s'",
                        ai_validation_result.get("valid"),
                        ai_validation_result.get("confidence", 0.0),
                        ai_validation_result.get("reasoning", "")
                    )

                    # Reject if AI says it's not valid or confidence too low
                    if not ai_validation_result.get("valid", False):
                        logger.warning(
                            "Google Search: AI REJECTED NIP %s - %s",
                            nip,
                            ai_validation_result.get("reasoning", "unknown reason")
                        )
                        rejected_nips.add(nip)  # Remember this NIP was rejected
                        continue  # Try next result

                    if ai_validation_result.get("confidence", 0.0) < 0.7:
                        logger.warning(
                            "Google Search: AI confidence too low (%.2f) for NIP %s",
                            ai_validation_result.get("confidence", 0.0),
                            nip
                        )
                        rejected_nips.add(nip)  # Remember this NIP was rejected
                        continue  # Try next result

                # AI approved or AI disabled - add to candidates
                confidence = 0.85  # Base confidence
                if ai_validation_result:
                    # Adjust confidence based on AI validation
                    ai_confidence = ai_validation_result.get("confidence", 0.85)
                    confidence = min(0.95, (confidence + ai_confidence) / 2)  # Average, max 0.95

                candidate = {
                    "nip": nip,
                    "confidence": confidence,
                    "query": query,
                    "variant": i,
                    "discovered_domain": discovered_domain,
                    "source_url": result.get("url"),
                    "source_title": result.get("title"),
                    "ai_validation": ai_validation_result,
                    "name_match_score": name_match_score,
                }

                candidates.append(candidate)
                logger.info("Google Search: Added candidate NIP %s with confidence %.2f", nip, confidence)

            logger.info("Google Search: variant %d - found %d candidates so far", i, len(candidates))

            # EARLY EXIT: If we found a very high confidence candidate, stop searching
            if any(c['confidence'] >= 0.90 for c in candidates):
                logger.info("Google Search: Found high-confidence candidate (>= 0.90) - stopping search")
                break

        # Select best candidate (highest confidence)
        if candidates:
            # Sort by confidence (descending)
            candidates.sort(key=lambda c: c['confidence'], reverse=True)
            best = candidates[0]

            logger.info(
                "Google Search: Selected best candidate: NIP %s with confidence %.2f (from %d candidates)",
                best['nip'],
                best['confidence'],
                len(candidates)
            )

            # Build alternatives list (max 5, excluding best)
            alternatives = []
            for alt in candidates[1:6]:  # Skip best, take up to 5
                alternatives.append(NIPCandidate(
                    nip=alt['nip'],
                    nip_formatted=format_nip(alt['nip']),
                    company_name_found=alt.get('source_title'),
                    confidence=alt['confidence'],
                    source_url=alt.get('source_url'),
                    source_domain=alt.get('discovered_domain'),
                    reasoning=alt.get('ai_validation', {}).get('reasoning') if alt.get('ai_validation') else None,
                ))

            return NIPResult(
                company_name=company_name,
                city=city,
                found=True,
                nip=best['nip'],
                nip_formatted=format_nip(best['nip']),
                confidence=best['confidence'],
                strategy_used=SearchStrategy.GOOGLE_SEARCH,
                alternatives=alternatives,  # Add alternatives list
                warnings=[],
                cost_usd=0.015,  # Google Search + AI validation cost
                metadata={
                    "query": best['query'],
                    "variant": best['variant'],
                    "base_name": base_name,
                    "discovered_domain": best['discovered_domain'],
                    "source_url": best['source_url'],
                    "source_title": best['source_title'],
                    "ai_validation": best['ai_validation'],
                    "name_match_score": best['name_match_score'],
                    "total_candidates": len(candidates),
                },
            )

        logger.info("Google Search: No valid candidates found")

        # Not found
        logger.info("Google Search: NIP not found in any variant")
        return self._create_not_found_result(company_name, city)

    def _create_not_found_result(self, company_name: str, city: Optional[str]) -> NIPResult:
        """Create not found result."""
        return NIPResult(
            company_name=company_name,
            city=city,
            found=False,
            nip=None,
            confidence=0.0,
            strategy_used=None,
            cost_usd=0.005,  # Still costs money even if not found
        )

    async def close(self):
        """Close resources."""
        # Apify client doesn't need closing
        if self._ai_validator:
            await self._ai_validator.close()
