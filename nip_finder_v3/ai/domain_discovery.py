"""
AI-Powered Domain Discovery (Level 4).

Uses Vertex AI Gemini to:
- Analyze Google search results
- Identify which domain belongs to the company
- Verify domain matches company identity
"""

import json
import logging
from typing import List, Optional

from google.cloud import aiplatform
from vertexai.preview.generative_models import GenerativeModel

from ..config import NIPFinderV3Settings, get_settings

logger = logging.getLogger(__name__)


class AIDomainDiscovery:
    """
    AI-Powered Domain Discovery.

    Analyzes search results to find company's domain.
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
                logger.warning("AI Domain Discovery: no Vertex AI project ID")
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
            logger.info("AI Domain Discovery: initialized")
            return True

        except Exception as e:
            logger.error("AI Domain Discovery: initialization failed: %s", e)
            self._initialized = True
            return False

    async def discover_domain(
        self,
        company_name: str,
        city: Optional[str],
        search_results: List[dict],
    ) -> Optional[str]:
        """
        Discover company domain from search results using AI.

        Args:
            company_name: Company name
            city: City
            search_results: List of search results with {title, description, url}

        Returns:
            Domain (e.g. "company.pl") or None
        """
        if not self._ensure_initialized():
            return None

        if not search_results:
            return None

        try:
            # Prepare search results for AI
            results_text = ""
            for i, result in enumerate(search_results[:10], 1):
                results_text += f"\n{i}. URL: {result.get('url', '')}\n"
                results_text += f"   Title: {result.get('title', '')}\n"
                results_text += f"   Description: {result.get('description', '')}\n"

            prompt = f"""
Analyze these search results and identify the official company domain.

Company: {company_name}
City: {city or "unknown"}

Search Results:
{results_text}

Task:
Find the domain (website) that belongs to THIS specific company "{company_name}" in {city or "Poland"}.

Rules:
- Look for exact company name match in URL or title
- Prefer .pl domains for Polish companies
- Ignore: portals (e.g. znanylekarz.pl), directories, social media, maps
- Ignore: companies with similar names but different locations
- Return null if uncertain

Return JSON with ONLY these fields:
{{
    "domain": "company-domain.pl or null",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}

Example:
Input: "PragaMed", city="Warszawa"
Results: [... pragamed.pl ...]
Output:
{{
    "domain": "pragamed.pl",
    "confidence": 0.95,
    "reasoning": "URL pragamed.pl matches company name PragaMed and title confirms location in Warsaw"
}}

Important: Return ONLY valid JSON, no additional text.
"""

            # Generate response
            response = self._model.generate_content(
                prompt,
                generation_config={
                    "temperature": self.settings.ai_temperature,
                    "max_output_tokens": 300,
                },
            )

            # Parse JSON
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            result = json.loads(text)

            domain = result.get("domain")
            confidence = result.get("confidence", 0.0)
            reasoning = result.get("reasoning", "")

            if domain and confidence >= 0.7:
                logger.info(
                    "AI Domain Discovery: '%s' → %s (confidence=%.2f, reason=%s)",
                    company_name,
                    domain,
                    confidence,
                    reasoning,
                )
                return domain
            else:
                logger.info("AI Domain Discovery: low confidence or no domain found")
                return None

        except Exception as e:
            logger.error("AI Domain Discovery: error: %s", e)
            return None

    async def close(self):
        """Close resources."""
        pass
