"""
AI-Powered Semantic Validator.

Uses Vertex AI Gemini to validate NIP with semantic understanding.
"""

import asyncio
import json
import logging
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
            # Prefer API key approach if available (bypasses organizational constraints)
            if self.settings.ai_google_platform_models_api_key:
                logger.info("AI Validator: using Google AI Platform API key (REST API)")
                self._use_api_key = True
                self._initialized = True
                return True

            # Fallback to Vertex AI SDK
            if not self.settings.vertex_ai_project_id:
                self._initialized = True
                return False

            logger.info("AI Validator: using Vertex AI SDK")
            aiplatform.init(
                project=self.settings.vertex_ai_project_id,
                location=self.settings.vertex_ai_location,
            )

            self._model = GenerativeModel(self.settings.vertex_ai_model)
            self._initialized = True
            return True

        except Exception as e:
            logger.error("AI Validator: init failed: %s", e)
            self._initialized = True
            return False

    async def _call_gemini_rest_api(self, prompt: str, max_retries: int = 5) -> str:
        """Call Gemini API using REST API with API key."""
        # Use Vertex AI endpoint with API key - use gemini-2.5-flash-lite (from user's curl)
        url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-2.5-flash-lite:generateContent"
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
                            "max_output_tokens": 300,
                        },
                    )
                    text = response.text

                text = text.strip()

                # Remove markdown code blocks
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

    async def close(self):
        """Close resources."""
        pass
