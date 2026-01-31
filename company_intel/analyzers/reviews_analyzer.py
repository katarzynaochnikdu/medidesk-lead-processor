"""
Reviews Analyzer - analiza recenzji Google Maps za pomocą Vertex AI.

Wyciąga insights Z CYTATAMI:
- Najczęstsze skargi + cytaty jako dowody
- Najczęstsze pochwały + cytaty jako dowody
- Główne tematy
- Podsumowanie
- Confidence score
"""

import json
import re
from typing import Optional

import logging
from ..config import CompanyIntelSettings
from ..models import ReviewsInsights, InsightWithCitations, ReviewCitation


class ReviewsAnalyzer:
    """Analyzer recenzji Google Maps z weryfikacją przez cytaty."""
    
    ANALYSIS_PROMPT = """Przeanalizuj poniższe recenzje placówki medycznej i wyciągnij kluczowe insights.

RECENZJE (numerowane):
{reviews_text}

PRIORYTET: Skup się szczególnie na **KOMUNIKACJI Z PACJENTAMI**, czyli:
- **Dodzwanianie** - czy łatwo się dodzwonić, jak długo trzeba czekać na połączenie
- **Oddzwanianie** - czy placówka oddzwania na nieodebrane połączenia
- **Odbieranie telefonów** - jak szybko odbierają, czy w ogóle odbierają
- **Odpowiadanie na maile/wiadomości** - czy i jak szybko odpowiadają na korespondencję
- **Obsługa recepcji** - uprzejmość, kompetencja, organizacja

Zwróć JSON z następującymi polami:
{{
  "top_complaints": [
    {{"insight": "krótka skarga (max 7 słów)", "review_indices": [1, 5, 12]}},
    {{"insight": "inna skarga", "review_indices": [3, 7]}}
  ],
  "top_praises": [
    {{"insight": "krótka pochwała (max 7 słów)", "review_indices": [2, 8, 14]}},
    {{"insight": "inna pochwała", "review_indices": [4]}}
  ],
  "common_themes": ["temat 1", "temat 2", "temat 3"],
  "summary": "Krótkie podsumowanie w 2-3 zdaniach - JAK PLACÓWKA KOMUNIKUJE SIĘ Z PACJENTAMI"
}}

WAŻNE:
- Dla każdej skargi/pochwały podaj INDEKSY recenzji które ją wspierają (numery z listy powyżej)
- Każda skarga/pochwała MUSI mieć co najmniej 1 indeks recenzji jako dowód
- Skup się na NAJCZĘSTSZYCH wzorcach - podawaj te z największą liczbą recenzji
- Priorytetuj aspekty KOMUNIKACJI: dodzwanianie, oddzwanianie, odbieranie telefonów, odpowiadanie na maile
- Bądź konkretny (np. "trudno się dodzwonić", "nie oddzwaniają" zamiast "problemy z kontaktem")
- W insights używaj krótkich fraz (max 7 słów)
- Jeśli nie ma skarg/pochwał o komunikacji - szukaj innych tematów
- Summary skupione na KOMUNIKACJI

Zwróć TYLKO JSON, bez dodatkowych komentarzy."""

    def __init__(self, settings: Optional[CompanyIntelSettings] = None):
        """Inicjalizacja analyzera."""
        self.settings = settings or CompanyIntelSettings()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Import Vertex AI
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            
            vertexai.init(project=self.settings.gcp_project_id)
            self.model = GenerativeModel(self.settings.vertex_ai_model)
            self.logger.info("Vertex AI initialized for reviews analysis")
        except Exception as e:
            self.logger.error("Failed to initialize Vertex AI: %s", e)
            self.model = None
    
    async def analyze(
        self,
        reviews_data: list[dict],
        place_name: str = "Placówka",
    ) -> Optional[ReviewsInsights]:
        """
        Analizuje recenzje i zwraca insights Z CYTATAMI.
        
        Args:
            reviews_data: Lista recenzji z Google Maps (z polami: text, stars, publishedAtDate, reviewUrl, name)
            place_name: Nazwa placówki (do logowania)
        
        Returns:
            ReviewsInsights z cytatami lub None jeśli błąd
        """
        if not self.model:
            self.logger.warning("Vertex AI not available - skipping reviews analysis")
            return None
        
        if not reviews_data:
            self.logger.info("No reviews to analyze for %s", place_name)
            return ReviewsInsights(total_reviews_analyzed=0)
        
        try:
            # Przygotuj tekst recenzji z numerami (indeksami)
            reviews_text, reviews_index = self._prepare_reviews_text(reviews_data)
            
            if not reviews_text:
                return ReviewsInsights(total_reviews_analyzed=0)
            
            # Oblicz średnią ocenę
            ratings = [r.get("stars") for r in reviews_data if r.get("stars")]
            avg_rating = sum(ratings) / len(ratings) if ratings else None
            
            self.logger.info(
                "Analyzing %d reviews for %s (avg rating: %.1f)",
                len(reviews_index),
                place_name,
                avg_rating or 0,
            )
            
            # Wywołaj AI
            prompt = self.ANALYSIS_PROMPT.format(reviews_text=reviews_text)
            
            response = await self._call_vertex_ai(prompt)
            
            if not response:
                return None
            
            # Parse JSON
            insights_data = self._parse_json_response(response)
            
            if not insights_data:
                return None
            
            # Mapuj indeksy na cytaty z pełnymi metadanymi
            top_complaints = self._build_insights_with_citations(
                insights_data.get("top_complaints", []),
                reviews_index,
            )
            top_praises = self._build_insights_with_citations(
                insights_data.get("top_praises", []),
                reviews_index,
            )
            
            # Oblicz confidence na podstawie liczby recenzji wspierających
            total_citations = sum(c.count for c in top_complaints) + sum(p.count for p in top_praises)
            confidence = min(1.0, total_citations / max(1, len(reviews_index)) * 2)  # Skaluj 0-1
            
            # Stwórz model
            insights = ReviewsInsights(
                total_reviews_analyzed=len(reviews_index),
                avg_rating=avg_rating,
                top_complaints=top_complaints,
                top_praises=top_praises,
                common_themes=insights_data.get("common_themes", []),
                summary=insights_data.get("summary"),
                confidence=round(confidence, 2),
            )
            
            self.logger.info(
                "Reviews analyzed: %d complaints, %d praises, %d themes, confidence=%.2f",
                len(insights.top_complaints),
                len(insights.top_praises),
                len(insights.common_themes),
                insights.confidence,
            )
            
            return insights
            
        except Exception as e:
            self.logger.exception("Reviews analysis failed: %s", e)
            return None
    
    def _prepare_reviews_text(self, reviews_data: list[dict]) -> tuple[str, dict]:
        """
        Przygotowuje tekst recenzji do analizy z numerami.
        
        Returns:
            (tekst_dla_AI, słownik indeks->pełna_recenzja)
        """
        lines = []
        reviews_index = {}  # indeks -> pełne dane recenzji
        
        for i, review in enumerate(reviews_data[:50], 1):  # Max 50 recenzji
            stars = review.get("stars", 0)
            text = review.get("text") or review.get("reviewText") or ""
            
            # Obsłuż None
            if text is None:
                continue
            
            text = text.strip()
            
            if not text:
                continue
            
            # Zachowaj pełne dane recenzji
            reviews_index[i] = {
                "text": text,
                "stars": stars,
                "date": review.get("publishedAtDate") or review.get("publishAt"),
                "author": review.get("name"),
                "review_url": review.get("reviewUrl"),
            }
            
            # Skróć bardzo długie recenzje dla AI
            display_text = text
            if len(display_text) > 500:
                display_text = display_text[:500] + "..."
            
            lines.append(f"[{i}] [{stars}★] {display_text}")
        
        return "\n\n".join(lines), reviews_index
    
    def _build_insights_with_citations(
        self,
        insights_list: list[dict],
        reviews_index: dict,
    ) -> list[InsightWithCitations]:
        """
        Buduje InsightWithCitations z cytatami na podstawie indeksów.
        
        Args:
            insights_list: Lista z AI [{"insight": "...", "review_indices": [1, 5, 12]}]
            reviews_index: Słownik indeks -> pełne dane recenzji
        
        Returns:
            Lista InsightWithCitations z cytatami
        """
        result = []
        
        for item in insights_list:
            # Obsłuż stary format (tylko string) dla kompatybilności
            if isinstance(item, str):
                result.append(InsightWithCitations(
                    insight=item,
                    count=1,
                    citations=[],
                ))
                continue
            
            insight_text = item.get("insight", "")
            indices = item.get("review_indices", [])
            
            if not insight_text:
                continue
            
            # Buduj cytaty
            citations = []
            for idx in indices[:3]:  # Max 3 cytaty
                if idx in reviews_index:
                    review = reviews_index[idx]
                    
                    # Skróć cytat do max 200 znaków
                    citation_text = review["text"]
                    if len(citation_text) > 200:
                        citation_text = citation_text[:200] + "..."
                    
                    citations.append(ReviewCitation(
                        text=citation_text,
                        date=self._format_date(review.get("date")),
                        author=review.get("author"),
                        rating=review.get("stars"),
                        review_url=review.get("review_url"),
                    ))
            
            result.append(InsightWithCitations(
                insight=insight_text,
                count=len(indices),
                citations=citations,
            ))
        
        return result
    
    def _format_date(self, date_str: Optional[str]) -> Optional[str]:
        """Formatuje datę do czytelnego formatu z godziną."""
        if not date_str:
            return None
        
        try:
            # ISO format: 2024-10-11T01:23:42.544Z
            if "T" in date_str:
                from datetime import datetime
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M")
            return date_str
        except Exception:
            return date_str
    
    async def _call_vertex_ai(self, prompt: str) -> Optional[str]:
        """Wywołuje Vertex AI."""
        try:
            import asyncio
            
            # Vertex AI nie ma async API - użyj to_thread
            response = await asyncio.to_thread(
                lambda: self.model.generate_content(
                    prompt,
                    generation_config={
                        "temperature": 0.3,
                        "max_output_tokens": 4096,  # Zwiększono dla cytatów
                    }
                )
            )
            
            return response.text
            
        except Exception as e:
            self.logger.error("Vertex AI call failed: %s", e)
            return None
    
    def _parse_json_response(self, response: str) -> Optional[dict]:
        """Parsuje odpowiedź JSON z AI."""
        try:
            # Usuń markdown code blocks jeśli są
            response = re.sub(r"```json\s*", "", response)
            response = re.sub(r"```\s*", "", response)
            response = response.strip()
            
            # Znajdź JSON (obsłuż zagnieżdżone obiekty)
            # Szukamy pierwszego { i ostatniego }
            start = response.find("{")
            end = response.rfind("}") + 1
            
            if start == -1 or end == 0:
                self.logger.error("No JSON found in response")
                self.logger.debug("Response preview: %s", response[:300])
                return None
            
            json_str = response[start:end]
            
            # Napraw częste błędy JSON
            # Usuń trailing commas
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
            
            data = json.loads(json_str)
            
            return data
            
        except json.JSONDecodeError as e:
            self.logger.error("Failed to parse JSON: %s", e)
            self.logger.debug("Response: %s", response[:500])
            
            # Spróbuj naprawić JSON
            try:
                # Usuń komentarze // 
                json_str = re.sub(r'//.*$', '', json_str, flags=re.MULTILINE)
                data = json.loads(json_str)
                return data
            except:
                return None
