"""
AI-Powered Input Enrichment (Level 0).

Uses Vertex AI Gemini to:
- Normalize company names (handle typos, variants)
- Extract base company name (remove generic words)
- Predict likely domain even without email
- Extract city/address if mentioned in name
"""

import json
import logging
from typing import Optional

from google.cloud import aiplatform
from vertexai.preview.generative_models import GenerativeModel

from ..config import NIPFinderV3Settings, get_settings

logger = logging.getLogger(__name__)


class AIEnrichment:
    """
    AI-Powered Input Enrichment.

    Uses Vertex AI Gemini to enrich and normalize input data.
    """

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()
        self._model: Optional[GenerativeModel] = None
        self._initialized = False

    def _ensure_initialized(self) -> bool:
        """Initialize Vertex AI (lazy)."""
        if self._initialized:
            return self._model is not None

        try:
            if not self.settings.vertex_ai_project_id:
                logger.warning("AI Enrichment: no Vertex AI project ID")
                self._initialized = True
                return False

            # Initialize Vertex AI
            aiplatform.init(
                project=self.settings.vertex_ai_project_id,
                location=self.settings.vertex_ai_location,
            )

            # Load model
            self._model = GenerativeModel(self.settings.vertex_ai_model)
            self._initialized = True
            logger.info("AI Enrichment: Vertex AI initialized (model=%s)", self.settings.vertex_ai_model)
            return True

        except Exception as e:
            logger.error("AI Enrichment: initialization failed: %s", e)
            self._initialized = True
            return False

    async def enrich_input(
        self,
        company_name: str,
        city: Optional[str] = None,
        email: Optional[str] = None,
    ) -> dict:
        """
        Enrich input data using AI.

        Args:
            company_name: Company name
            city: City (optional)
            email: Email (optional)

        Returns:
            Dict with:
                - normalized_name: Normalized company name
                - base_name: Base company name (without generic words)
                - predicted_domain: Predicted domain (even without email)
                - extracted_city: Extracted city from company name
                - confidence: Confidence score (0.0-1.0)
        """
        if not self._ensure_initialized():
            # Fallback: return basic normalization
            return {
                "normalized_name": company_name.lower().strip(),
                "base_name": company_name.lower().strip(),
                "predicted_domain": None,
                "extracted_city": city,
                "confidence": 0.5,
            }

        try:
            prompt = f"""
Analyze this Polish company information and extract key details:

Company Name: {company_name}
City: {city or "unknown"}
Email: {email or "unknown"}

Tasks:
1. Normalize the company name (fix typos, standardize)
2. Extract the base company name (remove generic words like "Centrum Medyczne", "Przychodnia", "Sp. z o.o.", etc.)
3. Predict the most likely company domain (website), even if email is not provided
4. Extract the city if mentioned in the company name

Return JSON with ONLY these fields:
{{
    "normalized_name": "normalized company name",
    "base_name": "base name without generic words",
    "predicted_domain": "predicted-domain.pl or null",
    "extracted_city": "extracted city or provided city",
    "confidence": 0.0-1.0
}}

Example:
Input: "Centrum Medyczne PragaMed", city="Warszawa"
Output:
{{
    "normalized_name": "Centrum Medyczne PragaMed",
    "base_name": "PragaMed",
    "predicted_domain": "pragamed.pl",
    "extracted_city": "Warszawa",
    "confidence": 0.9
}}

Important: Return ONLY valid JSON, no additional text.
"""

            # Generate response
            response = self._model.generate_content(
                prompt,
                generation_config={
                    "temperature": self.settings.ai_temperature,
                    "max_output_tokens": 500,
                },
            )

            # Parse JSON response
            text = response.text.strip()

            # Remove markdown code blocks if present
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            result = json.loads(text)

            logger.info(
                "AI Enrichment: '%s' → base_name='%s', predicted_domain='%s'",
                company_name,
                result.get("base_name"),
                result.get("predicted_domain"),
            )

            return result

        except Exception as e:
            logger.error("AI Enrichment: error: %s", e)
            # Fallback
            return {
                "normalized_name": company_name.lower().strip(),
                "base_name": company_name.lower().strip(),
                "predicted_domain": None,
                "extracted_city": city,
                "confidence": 0.5,
            }

    async def close(self):
        """Close resources."""
        pass
