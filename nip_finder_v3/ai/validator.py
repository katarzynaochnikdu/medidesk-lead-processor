"""
AI-Powered Semantic Validator.

Uses Vertex AI Gemini to validate NIP with semantic understanding.
"""

import asyncio
import json
import logging
import re
import time
from typing import Optional

import httpx
from google.api_core.exceptions import ResourceExhausted
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel  # Removed .preview (deprecated)

from ..config import NIPFinderV3Settings, get_settings

logger = logging.getLogger(__name__)


class AIValidator:
    """
    AI-Powered Semantic Validator.

    Uses AI to:
    - Verify company identity matches extracted data
    - Cross-reference multiple sources
    - Detect anomalies (wrong company, wrong location)
    """

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()
        self._model: Optional[GenerativeModel] = None
        self._initialized = False
        self._use_api_key = False  # Use REST API with API key instead of Vertex AI SDK

    def _ensure_initialized(self) -> bool:
        """Initialize AI (lazy) - prefers API key over Vertex AI SDK."""
        if self._initialized:
            return self._model is not None or self._use_api_key

        try:
            # Prefer Vertex AI SDK when project is configured
            if self.settings.vertex_ai_project_id:
                logger.info("AI Validator: using Vertex AI SDK")
                aiplatform.init(
                    project=self.settings.vertex_ai_project_id,
                    location=self.settings.vertex_ai_location,
                )
                self._model = GenerativeModel(self.settings.vertex_ai_model)
                self._initialized = True
                return True

            # Fallback to API key approach if available
            if self.settings.ai_google_platform_models_api_key:
                logger.info("AI Validator: using Google AI Platform API key (REST API)")
                self._use_api_key = True
                self._initialized = True
                return True

            self._initialized = True
            return False

        except Exception as e:
            logger.error("AI Validator: init failed: %s", e)
            self._initialized = True
            return False

    async def _call_gemini_rest_api(self, prompt: str, max_retries: int = 5) -> str:
        """Call Gemini API using REST API with API key."""
        # Use Vertex AI endpoint with API key and configured model
        model = self.settings.vertex_ai_model or "gemini-2.5-pro"
        url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"
        params = {"key": self.settings.ai_google_platform_models_api_key}

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 300,
                "responseMimeType": "application/json",
            }
        }

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, params=params, json=payload)
                    response.raise_for_status()
                    data = response.json()

                    # Extract text from response
                    candidates = data.get("candidates", [])
                    if not candidates:
                        raise ValueError("No candidates in response")

                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if not parts:
                        raise ValueError("No parts in response")

                    return parts[0].get("text", "")

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 3.0
                    logger.warning("AI REST API: rate limit (429) - retry %d/%d after %.1fs", attempt + 1, max_retries, wait_time)
                    await asyncio.sleep(wait_time)
                    continue
                raise
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0)
                    continue
                raise

    async def validate_company_identity(
        self,
        company_name: str,
        city: Optional[str],
        nip: str,
        source_data: dict,
        max_retries: int = 5,
    ) -> dict:
        """
        Validate that NIP belongs to the correct company using AI.

        Args:
            company_name: Expected company name
            city: Expected city
            nip: Found NIP
            source_data: Data from source (webpage content, search results, etc.)
            max_retries: Max retry attempts for rate limiting (429 errors)

        Returns:
            Dict with {valid, confidence, reasoning}
        """
        if not self._ensure_initialized():
            return {"valid": True, "confidence": 0.5, "reasoning": "AI not available"}

        prompt = f"""You are a STRICT validator. Analyze if this NIP belongs to EXACTLY the correct company.

Expected Company: {company_name}
Expected City: {city or "unknown"}
Found NIP: {nip}

Source Data:
{json.dumps(source_data, indent=2)[:2000]}

Question: Does NIP {nip} belong to EXACTLY company "{company_name}" in {city or "Poland"}?

CRITICAL RULES - MUST FOLLOW:
1. Company name must contain ALL WORDS from expected name
   - Expected: "Centrum Medyczne PragaMed"
   - Found: "PRAGAMED Sp. z o.o." → REJECT (missing "Centrum Medyczne")
   - Found: "Centrum Medyczne PragaMed" → ACCEPT (all words present)

2. Partial name match = DIFFERENT COMPANY
   - "PRAGAMED" is NOT a match for "Centrum Medyczne PragaMed"
   - Base name alone is NOT sufficient
   - Missing key words = REJECT

3. Different legal forms may indicate different companies
   - "Sp. z o.o." vs no legal form
   - "S.A." vs "Sp. z o.o."
   - Consider this in confidence scoring

4. Different addresses in same city = likely different companies
   - Check if address matches (if available)
   - Different street = lower confidence

5. Confidence thresholds:
   - 0.95+: Exact name match + same address
   - 0.85-0.94: All words present, minor differences (e.g., "CM" vs "Centrum Medyczne")
   - 0.70-0.84: Most words present but missing some key words
   - < 0.70: REJECT - likely different company (set valid=false)

Respond with ONLY a JSON object, no other text before or after:
{{
    "valid": false,
    "confidence": 0.60,
    "reasoning": "Missing 'Centrum Medyczne' - likely different company"
}}

Do not include markdown code blocks. Return raw JSON only."""

        # Retry with exponential backoff for rate limiting
        for attempt in range(max_retries):
            try:
                # Use REST API with API key if available
                if self._use_api_key:
                    text = await self._call_gemini_rest_api(prompt, max_retries=1)
                else:
                    # Use Vertex AI SDK
                    response = self._model.generate_content(
                        prompt,
                        generation_config={
                            "temperature": 0.1,
                            "max_output_tokens": 1024,
                            "response_mime_type": "application/json",
                        },
                    )
                    text = response.text

                text = text.strip()

                # Remove markdown code blocks (handle blocks not at start)
                if "```" in text:
                    block_start = text.find("```")
                    block_end = text.find("```", block_start + 3)
                    if block_end != -1:
                        block = text[block_start + 3:block_end].strip()
                        if block.startswith("json"):
                            block = block[4:].strip()
                        text = block
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

                # Try to extract JSON from text (handle cases where AI adds extra text)
                if "{" in text and "}" in text:
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    text = text[start:end]

                try:
                    result = json.loads(text)
                except json.JSONDecodeError as json_err:
                    # Attempt to salvage partial JSON with regex (handles truncated output)
                    valid_match = re.search(r'"valid"\s*:\s*(true|false)', text, re.IGNORECASE)
                    conf_match = re.search(r'"confidence"\s*:\s*([0-9]+(?:\.[0-9]+)?)', text)
                    reason_match = re.search(r'"reasoning"\s*:\s*"([^"]*)"', text)

                    if valid_match or conf_match or reason_match:
                        result = {
                            "valid": valid_match.group(1).lower() == "true" if valid_match else False,
                            "confidence": float(conf_match.group(1)) if conf_match else 0.5,
                            "reasoning": reason_match.group(1) if reason_match else "Partial JSON extracted",
                        }
                        logger.info(
                            "AI Validator: extracted partial JSON for NIP %s (valid=%s, confidence=%.2f)",
                            nip,
                            result.get("valid"),
                            result.get("confidence", 0.0),
                        )
                        return result

                    logger.error(
                        "AI Validator: JSON parsing failed for NIP %s: %s\nResponse text: %s",
                        nip,
                        json_err,
                        text[:500]
                    )
                    # Retry on JSON errors (might be transient)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1.0)
                        continue
                    else:
                        return {"valid": True, "confidence": 0.5, "reasoning": f"JSON parsing failed: {json_err}"}

                logger.info(
                    "AI Validator: NIP %s for '%s' → valid=%s, confidence=%.2f",
                    nip,
                    company_name,
                    result.get("valid"),
                    result.get("confidence", 0.0),
                )

                return result

            except ResourceExhausted as e:
                # 429 Rate Limit - retry with exponential backoff (AGGRESSIVE)
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 3.0  # 3s, 6s, 12s, 24s, 48s
                    logger.warning(
                        "AI Validator: rate limit (429) - retry %d/%d after %.1fs (aggressive backoff)",
                        attempt + 1,
                        max_retries,
                        wait_time
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error("AI Validator: rate limit exhausted after %d retries", max_retries)
                    return {"valid": True, "confidence": 0.5, "reasoning": "Rate limit exceeded"}

            except Exception as e:
                logger.error("AI Validator: error: %s", e)
                return {"valid": True, "confidence": 0.5, "reasoning": f"Error: {str(e)}"}

        # Should not reach here, but just in case
        return {"valid": True, "confidence": 0.5, "reasoning": "Unknown error"}

    async def generate_search_queries(
        self,
        company_name: str,
        city: Optional[str] = None,
        email: Optional[str] = None,
        domain: Optional[str] = None,
        max_queries: int = 5,
    ) -> list[str]:
        """
        Generate optimized Google search queries using AI.
        
        Works with minimal input (just company name) or full data.
        
        Args:
            company_name: Company name (required, may be messy/partial)
            city: City (optional)
            email: Email (optional, for domain extraction)
            domain: Known domain (optional)
            max_queries: Max queries to return (default 5)
        
        Returns:
            List of optimized search queries
        """
        def _agent_log(hypothesis_id: str, location: str, message: str, data: dict[str, object]) -> None:
            try:
                payload = {
                    "sessionId": "debug-session",
                    "runId": "pre-fix",
                    "hypothesisId": hypothesis_id,
                    "location": location,
                    "message": message,
                    "data": data,
                    "timestamp": int(time.time() * 1000),
                }
                with open(
                    r"c:\Users\kochn\.cursor\Medidesk\Leads_extraction\.cursor\debug.log",
                    "a",
                    encoding="utf-8",
                ) as log_file:
                    log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except Exception:
                pass

        company_name_str = company_name or ""
        company_word_count = len(company_name_str.strip().split()) if company_name_str else 0
        company_len = len(company_name_str.strip()) if company_name_str else 0
        company_has_digits = any(ch.isdigit() for ch in company_name_str)
        company_has_quotes = '"' in company_name_str or "'" in company_name_str
        has_city = bool(city and city.strip())
        has_email = bool(email and "@" in email)
        has_domain = bool(domain and domain.strip())
        has_api_key = bool(self.settings.ai_google_platform_models_api_key)
        domain_from_email = False
        domain_is_public = False

        # region agent log
        _agent_log(
            "H1",
            "validator.py:generate_search_queries:entry",
            "Query generation entry summary",
            {
                "company_len": company_len,
                "company_word_count": company_word_count,
                "company_has_digits": company_has_digits,
                "company_has_quotes": company_has_quotes,
                "has_city": has_city,
                "has_email": has_email,
                "has_domain": has_domain,
                "has_api_key": has_api_key,
                "max_queries": max_queries,
            },
        )
        # endregion

        if not self._ensure_initialized():
            logger.warning("AI Query Generator: AI not available - using fallback")
            # region agent log
            _agent_log(
                "H4",
                "validator.py:generate_search_queries:fallback_no_ai",
                "AI unavailable, using fallback queries",
                {
                    "has_city": has_city,
                    "has_domain": has_domain,
                    "company_word_count": company_word_count,
                },
            )
            # endregion
            return self._fallback_queries(company_name, city, domain)

        # Extract domain from email if not provided
        if not domain and email and "@" in email:
            domain = email.split("@")[-1]
            domain_from_email = True
            if any(x in domain for x in ["gmail", "outlook", "hotmail", "yahoo", "wp.pl", "onet.pl", "interia.pl"]):
                domain_is_public = True
                domain = None  # Generic email, not useful

        # Build context for AI
        context_parts = [f'Nazwa firmy: "{company_name}"']
        if city:
            context_parts.append(f'Miasto: "{city}"')
        if domain:
            context_parts.append(f'Domena: "{domain}"')
        
        context = "\n".join(context_parts)

        # region agent log
        _agent_log(
            "H2",
            "validator.py:generate_search_queries:context",
            "Context built for AI query generation",
            {
                "context_lines": len(context_parts),
                "context_len": len(context),
                "has_city": has_city,
                "has_domain": bool(domain),
                "domain_from_email": domain_from_email,
                "domain_is_public": domain_is_public,
            },
        )
        # endregion
        
        prompt = f"""Wygeneruj {max_queries} najlepszych zapytań Google do znalezienia NIP polskiej firmy medycznej.

DANE WEJŚCIOWE (użyj WSZYSTKIE dostępne):
{context}

STRATEGIE DO ROZWAŻENIA:
1. Dokładna nazwa + "NIP" (podstawowe)
2. Nazwa z formą prawną: sp. z o.o., S.A., NZOZ, CM (centrum medyczne)
3. Skróty nazwy: "Centrum Medyczne XYZ" → "CM XYZ", "NZOZ XYZ"
4. Nazwa + "KRS" lub "REGON" (rejestry zawierają NIP)
5. Nazwa + "polityka prywatności" (NIP w RODO)
6. site:domena NIP (jeśli znana domena)
7. Nazwa + miasto + "przychodnia" / "klinika"
8. Warianty pisowni: myślniki, spacje, wielkie/małe litery

ZASADY:
- Zapytania MUSZĄ być po polsku
- Priorytet: najpierw dokładne, potem szersze
- Różnicuj zapytania (nie powtarzaj tej samej strategii)
- Jeśli nazwa wygląda na sieć klinik (np. "Nu-Med Elbląg"), szukaj też głównej spółki
- Maksymalnie {max_queries} zapytań
- Jeśli masz tylko krótką frazę (brak miasta/domeny/email) NIE zgaduj dodatkowych danych
- Przy krótkiej frazie bazuj wyłącznie na niej + słowach kluczowych (NIP/KRS/REGON/polityka prywatności)
- Zwróć poprawny JSON, bez markdown i bez komentarzy (tylko podwójne cudzysłowy)

Zwróć TYLKO JSON:
{{"queries": ["query1", "query2", ...]}}"""

        try:
            if self._use_api_key:
                text = await self._call_gemini_rest_api(prompt)
            else:
                response = self._model.generate_content(
                    prompt,
                    generation_config={
                        "temperature": 0.3,
                        "max_output_tokens": 512,
                        "response_mime_type": "application/json",
                    },
                )
                try:
                    candidates = getattr(response, "candidates", []) or []
                    candidate_count = len(candidates)
                    part_counts = []
                    part_text_lengths = []
                    for c in candidates:
                        parts = getattr(getattr(c, "content", None), "parts", []) or []
                        part_counts.append(len(parts))
                        for p in parts:
                            text_part = getattr(p, "text", None)
                            if isinstance(text_part, str):
                                part_text_lengths.append(len(text_part))
                    # region agent log
                    _agent_log(
                        "H2",
                        "validator.py:generate_search_queries:ai_response_parts",
                        "AI response parts summary",
                        {
                            "candidate_count": candidate_count,
                            "part_counts": part_counts,
                            "parts_text_count": len(part_text_lengths),
                            "parts_text_len_min": min(part_text_lengths) if part_text_lengths else 0,
                            "parts_text_len_max": max(part_text_lengths) if part_text_lengths else 0,
                            "parts_text_len_sum": sum(part_text_lengths),
                        },
                    )
                    # endregion
                except Exception:
                    pass
                text = response.text

            # Parse response
            text = text.strip()
            text_len = len(text)
            first_char = text[:1] if text else ""
            has_code_fence = text.startswith("```")
            has_brace_pair = "{" in text and "}" in text
            has_queries_key = '"queries"' in text or "'queries'" in text
            brace_open = text.count("{")
            brace_close = text.count("}")
            bracket_open = text.count("[")
            bracket_close = text.count("]")

            # region agent log
            _agent_log(
                "H2",
                "validator.py:generate_search_queries:ai_response_shape",
                "AI response shape before JSON parsing",
                {
                    "text_len": text_len,
                    "first_char": first_char,
                    "has_code_fence": has_code_fence,
                    "has_brace_pair": has_brace_pair,
                    "has_queries_key": has_queries_key,
                    "brace_open": brace_open,
                    "brace_close": brace_close,
                    "bracket_open": bracket_open,
                    "bracket_close": bracket_close,
                    "use_api_key": self._use_api_key,
                },
            )
            # endregion

            if not self._use_api_key and has_queries_key and not has_brace_pair and has_api_key:
                try:
                    rest_text = await self._call_gemini_rest_api(prompt)
                    rest_text = rest_text.strip() if rest_text else ""
                    rest_has_brace_pair = "{" in rest_text and "}" in rest_text
                    rest_has_queries_key = '"queries"' in rest_text or "'queries'" in rest_text
                    # region agent log
                    _agent_log(
                        "H2",
                        "validator.py:generate_search_queries:ai_response_rest_retry",
                        "AI retry via REST API",
                        {
                            "rest_text_len": len(rest_text),
                            "rest_has_brace_pair": rest_has_brace_pair,
                            "rest_has_queries_key": rest_has_queries_key,
                        },
                    )
                    # endregion
                    if rest_text:
                        text = rest_text
                        has_brace_pair = rest_has_brace_pair
                except Exception:
                    pass

            if not self._use_api_key and has_queries_key and not has_brace_pair:
                try:
                    retry_response = self._model.generate_content(
                        prompt,
                        generation_config={
                            "temperature": 0.3,
                            "max_output_tokens": 512,
                        },
                    )
                    retry_text = retry_response.text.strip()
                    retry_has_brace_pair = "{" in retry_text and "}" in retry_text
                    retry_has_queries_key = '"queries"' in retry_text or "'queries'" in retry_text
                    # region agent log
                    _agent_log(
                        "H2",
                        "validator.py:generate_search_queries:ai_response_retry",
                        "AI retry without response_mime_type",
                        {
                            "retry_text_len": len(retry_text),
                            "retry_has_brace_pair": retry_has_brace_pair,
                            "retry_has_queries_key": retry_has_queries_key,
                        },
                    )
                    # endregion
                    if retry_text:
                        text = retry_text
                except Exception:
                    pass
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]

            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                # Attempt a minimal repair for truncated JSON
                fixed_text = text
                in_string = False
                escape_next = False
                for c in fixed_text:
                    if escape_next:
                        escape_next = False
                        continue
                    if c == "\\":
                        escape_next = True
                        continue
                    if c == '"':
                        in_string = not in_string
                if in_string:
                    fixed_text += '"'
                open_braces = fixed_text.count("{") - fixed_text.count("}")
                open_brackets = fixed_text.count("[") - fixed_text.count("]")
                if open_brackets > 0:
                    fixed_text += "]" * open_brackets
                if open_braces > 0:
                    fixed_text += "}" * open_braces
                try:
                    result = json.loads(fixed_text)
                    # region agent log
                    _agent_log(
                        "H2",
                        "validator.py:generate_search_queries:ai_response_repair",
                        "JSON repair succeeded",
                        {
                            "fixed_text_len": len(fixed_text),
                            "added_braces": open_braces if open_braces > 0 else 0,
                            "added_brackets": open_brackets if open_brackets > 0 else 0,
                        },
                    )
                    # endregion
                except json.JSONDecodeError:
                    # region agent log
                    _agent_log(
                        "H2",
                        "validator.py:generate_search_queries:ai_response_repair",
                        "JSON repair failed",
                        {
                            "fixed_text_len": len(fixed_text),
                        },
                    )
                    # endregion
                    raise

            queries = result.get("queries", [])
            
            if queries:
                cleaned = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
                core_keywords = ("nip", "krs", "regon", "polityka", "site:")
                has_core_keyword = any(
                    any(kw in q.lower() for kw in core_keywords) for q in cleaned
                )
                if not cleaned or not has_core_keyword:
                    logger.warning("AI Query Generator: queries incomplete - using fallback")
                    # region agent log
                    _agent_log(
                        "H3",
                        "validator.py:generate_search_queries:ai_output_invalid",
                        "AI queries rejected (missing core keywords)",
                        {
                            "queries_count": len(cleaned),
                            "has_core_keyword": has_core_keyword,
                        },
                    )
                    # endregion
                    return self._fallback_queries(company_name, city, domain)

                any_site = any("site:" in q.lower() for q in queries if isinstance(q, str))
                any_nip = any("nip" in q.lower() for q in queries if isinstance(q, str))
                any_krs = any("krs" in q.lower() for q in queries if isinstance(q, str))
                any_privacy = any("polityka" in q.lower() for q in queries if isinstance(q, str))
                any_city = False
                if city:
                    city_lower = city.lower()
                    any_city = any(city_lower in q.lower() for q in queries if isinstance(q, str))
                q_lengths = [len(q) for q in queries if isinstance(q, str)]
                min_len = min(q_lengths) if q_lengths else 0
                max_len = max(q_lengths) if q_lengths else 0

                # region agent log
                _agent_log(
                    "H3",
                    "validator.py:generate_search_queries:ai_output",
                    "AI query generation output summary",
                    {
                        "queries_count": len(queries),
                        "any_site": any_site,
                        "any_nip": any_nip,
                        "any_krs": any_krs,
                        "any_privacy": any_privacy,
                        "any_city": any_city,
                        "min_query_len": min_len,
                        "max_query_len": max_len,
                    },
                )
                # endregion
                logger.info("AI Query Generator: generated %d queries for '%s'", len(cleaned), company_name)
                return cleaned[:max_queries]
            else:
                logger.warning("AI Query Generator: no queries returned - using fallback")
                # region agent log
                _agent_log(
                    "H4",
                    "validator.py:generate_search_queries:fallback_empty_ai",
                    "AI returned empty queries, using fallback",
                    {
                        "has_city": has_city,
                        "has_domain": bool(domain),
                        "company_word_count": company_word_count,
                    },
                )
                # endregion
                return self._fallback_queries(company_name, city, domain)

        except Exception as e:
            logger.error("AI Query Generator: error: %s - using fallback", e)
            # region agent log
            _agent_log(
                "H4",
                "validator.py:generate_search_queries:fallback_error",
                "AI query generation error, using fallback",
                {
                    "error_type": type(e).__name__,
                    "has_city": has_city,
                    "has_domain": bool(domain),
                },
            )
            # endregion
            return self._fallback_queries(company_name, city, domain)

    def _fallback_queries(
        self,
        company_name: str,
        city: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> list[str]:
        """Fallback queries when AI is not available."""
        queries = []
        
        # Basic queries
        if city:
            queries.append(f'"{company_name}" "{city}" NIP')
        queries.append(f'"{company_name}" NIP')
        queries.append(f'"{company_name}" KRS')
        
        # Domain search
        if domain:
            queries.append(f'site:{domain} NIP')
        
        # Privacy policy (often contains NIP)
        queries.append(f'"{company_name}" polityka prywatności')
        
        return queries[:5]

    async def close(self):
        """Close resources."""
        pass
