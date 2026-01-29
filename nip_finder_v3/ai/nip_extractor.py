"""
AI-Powered NIP Extractor.

Uses Vertex AI Gemini to extract NIP from text with semantic validation.
"""

import json
import logging
from typing import Optional

from google.cloud import aiplatform
from vertexai.preview.generative_models import GenerativeModel

from ..config import NIPFinderV3Settings, get_settings

logger = logging.getLogger(__name__)


class AINIPExtractor:
    """
    AI-Powered NIP Extractor.

    Uses AI to:
    - Extract NIP from text
    - Verify NIP belongs to specific company (not another company mentioned)
    - Provide confidence score
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
                self._initialized = True
                return False

            aiplatform.init(
                project=self.settings.vertex_ai_project_id,
                location=self.settings.vertex_ai_location,
            )

            self._model = GenerativeModel(self.settings.vertex_ai_model)
            self._initialized = True
            return True

        except Exception as e:
            logger.error("AI NIP Extractor: init failed: %s", e)
            self._initialized = True
            return False

    async def extract_nip(
        self,
        text: str,
        company_name: str,
    ) -> Optional[dict]:
        """
        Extract NIP from text using AI with context awareness.

        Args:
            text: Text to extract from
            company_name: Expected company name (for verification)

        Returns:
            Dict with {nip, confidence, reasoning} or None
        """
        if not self._ensure_initialized():
            return None

        try:
            prompt = f"""
Extract the NIP (Polish tax ID) for company "{company_name}" from this text.

Text:
{text[:5000]}  # Limit to 5000 chars

Rules:
- NIP is a 10-digit number (may have dashes like 123-456-78-90)
- Extract ONLY the NIP that belongs to "{company_name}"
- Do NOT return NIP of other companies mentioned in text
- Return null if uncertain which NIP belongs to this company

Return JSON:
{{
    "nip": "1234567890 or null",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}

Important: Return ONLY valid JSON.
"""

            response = self._model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 200,
                },
            )

            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            result = json.loads(text)

            if result.get("nip") and result.get("confidence", 0) >= 0.7:
                logger.info(
                    "AI NIP Extractor: found NIP=%s for '%s' (confidence=%.2f)",
                    result["nip"],
                    company_name,
                    result["confidence"],
                )
                return result
            else:
                return None

        except Exception as e:
            logger.error("AI NIP Extractor: error: %s", e)
            return None

    async def close(self):
        """Close resources."""
        pass
