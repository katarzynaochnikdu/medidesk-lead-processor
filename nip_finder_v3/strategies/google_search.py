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
from ..models import NIPResult, SearchStrategy
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

        # Prepare optimized query variants (PRIORITY: full name first, base name as fallback)
        queries = []

        # Variant 1: Full name + city + NIP (MOST SPECIFIC - exact match priority)
        if city:
            queries.append(f'"{company_name}" "{city}" NIP')

        # Variant 2: Full name + NIP (exact name, any location)
        queries.append(f'"{company_name}" NIP')

        # Variant 3: Full name + city (no NIP keyword - find official site)
        if city:
            queries.append(f'"{company_name}" "{city}"')

        # Variant 4: Full name alone (find official site)
        queries.append(f'"{company_name}"')

        # Variant 5: Base name + city + NIP (FALLBACK - less specific)
        if city and base_name and base_name != company_name.lower():
            queries.append(f'{base_name} {city} NIP')

        # Variant 6: Base name + NIP (LAST RESORT)
        if base_name and base_name != company_name.lower():
            queries.append(f'{base_name} NIP')

        logger.info("Google Search: trying %d query variants", len(queries))

        # MULTI-PASS VALIDATION: Collect all NIP candidates, then choose the best
        candidates = []

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

            # Extract NIP from snippets
            for result in results:
                # Combine title + description
                text = f"{result['title']} {result['description']}"
                nip = extract_nip_from_text(text)

                if not nip:
                    continue

                # Skip if already found this NIP
                if any(c['nip'] == nip for c in candidates):
                    logger.debug("Google Search: NIP %s already in candidates - skipping", nip)
                    continue

                # Found NIP!
                logger.info("Google Search: NIP found in snippet (variant %d): %s", i, nip)

                # PRE-FILTER: Fuzzy matching to avoid expensive AI calls
                title = result.get("title", "")
                name_match_score = calculate_name_match_score(company_name, title)
                logger.info("Google Search: Fuzzy match score for '%s': %.2f", title, name_match_score)

                if name_match_score < 0.5:
                    logger.warning(
                        "Google Search: PRE-FILTER REJECT - name match score %.2f < 0.5 for '%s'",
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
                ai_validation_result = None
                if self._ai_validator and self.settings.enable_ai_semantic_validation:
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
                        continue  # Try next result

                    if ai_validation_result.get("confidence", 0.0) < 0.7:
                        logger.warning(
                            "Google Search: AI confidence too low (%.2f) for NIP %s",
                            ai_validation_result.get("confidence", 0.0),
                            nip
                        )
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

            return NIPResult(
                company_name=company_name,
                city=city,
                found=True,
                nip=best['nip'],
                nip_formatted=format_nip(best['nip']),
                confidence=best['confidence'],
                strategy_used=SearchStrategy.GOOGLE_SEARCH,
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
                    "rejected_candidates": [c['nip'] for c in candidates[1:]],
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
