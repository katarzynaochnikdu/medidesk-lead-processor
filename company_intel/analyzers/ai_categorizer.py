"""
AI Categorizer - kategoryzacja placówki przez Vertex AI.

Analizuje tekst strony WWW i zwraca:
- Płatnik usług (NFZ, Komercyjne, Ubezpieczenie)
- Specjalizacja (POZ, Stomatologia, Szpital...)
- Wielospecjalistyczne (kardiologia, ortopedia...)
- Typ własności (Prywatny, Publiczny)
- Kategoria konta (Podmiot leczniczy, Partner...)
- Branża (jeśli nie podmiot leczniczy)
"""

import json
import logging
from typing import Optional

from ..config import CompanyIntelSettings, get_settings
from ..models import KategoryzacjaAI


logger = logging.getLogger(__name__)


# Definicje możliwych wartości dla pól
ALLOWED_VALUES = {
    "platnik_uslug": ["NFZ", "Komercyjne", "Ubezpieczenie", "none"],
    "specjalizacja": [
        "POZ", "Przychodnia Wielospecjalistyczna", "Szpital",
        "Poradnia Zdrowia Psychicznego", "Rehabilitacja", "Stomatologia",
        "Diagnostyka", "Medycyna Estetyczna", "Diagnostyka Obrazowa",
        "Laboratorium", "Weterynaria", "Usługi Niemedyczne", "none"
    ],
    "wielospecjalistyczne": [
        "chirurgia ogólna", "chirurgia plastyczna", "gastroenterologia",
        "ginekologia/położnictwo/leczenie niepłodności", "kardiologia",
        "laryngologia", "okulistyka", "ortopedia", "dermatologia"
    ],
    "typ_wlasnosci": [
        "-None-", "Prywatny (Private)", "Partnerstwo PP (Partnership)", "Publiczny (Public)"
    ],
    "kategoria_konta": [
        "-None-", "Podmiot leczniczy (Inne)", "Partner", "Konkurencja", "Poddostawca", "Pozostałe"
    ],
    "branza": [
        "Agencje reklamowe (Placówka medyczna)", "Fundacja/Stowarzyszenie/Spółdzielnia (Konkurencja)",
        "Kancelaria prawna (Partner)", "Media/Eventy medyczne (Okołomedyczne inne)",
        "Okołomedyczne inne (Poddostawca)", "Sprzedaż sprzętu i jednorazówki medycznej (Pozostałe)",
        "Szkolenia/Consulting", "Edukacja kliniczna (Edukacja medyczna)", "Usługi finansowe",
        "Wdrożeniowiec systemów medycznych", "Inne", "Ratownictwo", "Dystrybutor", None
    ],
}

# Prompt do kategoryzacji - ultra-zwięzły, wymusza jedną linię
CATEGORIZATION_PROMPT = """Kategoryzuj placówkę. Zwróć TYLKO jednolinijkowy JSON bez formatowania.

FIRMA: {company_name}
TEKST: {page_text}

Zwróć dokładnie taki format (jedna linia, bez newlines):
{{"platnik_uslug":["Komercyjne"],"specjalizacja":["Medycyna Estetyczna"],"wielospecjalistyczne":["chirurgia plastyczna"],"typ_wlasnosci":"Prywatny (Private)","confidence":0.95,"reasoning":"opis"}}

Wartości do wyboru:
- platnik_uslug: NFZ, Komercyjne
- specjalizacja: Stomatologia, Medycyna Estetyczna, POZ, Rehabilitacja, Diagnostyka, Szpital
- wielospecjalistyczne: chirurgia plastyczna, dermatologia, ginekologia, kardiologia, ortopedia, laryngologia, okulistyka
- typ_wlasnosci: Prywatny (Private), Publiczny (Public)"""


class AICategorizer:
    """
    Kategoryzuje placówkę używając Vertex AI.
    """
    
    def __init__(self, settings: Optional[CompanyIntelSettings] = None):
        self.settings = settings or get_settings()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._client = None
        self._initialized = False
    
    def _init_vertex_ai(self) -> bool:
        """Inicjalizuje Vertex AI client."""
        if self._initialized:
            return self._client is not None
        
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            
            if not self.settings.has_vertex_ai_credentials:
                self.logger.warning("Brak Vertex AI credentials")
                self._initialized = True
                return False
            
            vertexai.init(
                project=self.settings.gcp_project_id,
                location=self.settings.gcp_region,
            )
            
            self._client = GenerativeModel(self.settings.vertex_ai_model)
            self._initialized = True
            self.logger.info("Vertex AI initialized: %s", self.settings.vertex_ai_model)
            return True
            
        except ImportError:
            self.logger.error("Brak google-cloud-aiplatform - zainstaluj: pip install google-cloud-aiplatform")
            self._initialized = True
            return False
        except Exception as e:
            self.logger.error("Vertex AI init error: %s", e)
            self._initialized = True
            return False
    
    async def categorize(
        self,
        page_text: str,
        company_name: str,
    ) -> KategoryzacjaAI:
        """
        Kategoryzuje placówkę na podstawie tekstu strony.
        
        Args:
            page_text: Tekst ze strony WWW
            company_name: Nazwa firmy
        
        Returns:
            KategoryzacjaAI z sugestiami
        """
        self.logger.info("Categorizing: %s (text: %d chars)", company_name, len(page_text))
        
        if not self._init_vertex_ai():
            self.logger.warning("Vertex AI not available - returning empty categorization")
            return KategoryzacjaAI(
                ai_confidence=0.0,
                ai_reasoning="Vertex AI not available",
            )
        
        # Przygotuj prompt - użyj tylko pierwszych 5000 znaków tekstu (wystarczy do kategoryzacji)
        truncated_text = page_text[:5000] if len(page_text) > 5000 else page_text
        prompt = CATEGORIZATION_PROMPT.format(
            page_text=truncated_text,
            company_name=company_name,
        )
        
        try:
            import asyncio
            
            # Wywołaj Vertex AI (sync w thread pool)
            response = await asyncio.to_thread(
                lambda: self._client.generate_content(
                    prompt,
                    generation_config={
                        "temperature": 0.1,  # Niska temperatura = bardziej deterministyczne
                        "max_output_tokens": 2048,  # Zwiększone dla pełnego JSON
                    }
                )
            )
            
            # Parsuj odpowiedź
            response_text = response.text.strip()
            self.logger.debug("AI response: %s", response_text[:500])
            
            # Wyciągnij JSON
            result = self._parse_response(response_text)
            
            self.logger.info(
                "Categorization result: spec=%s, platnik=%s, confidence=%.2f",
                result.specjalizacja,
                result.platnik_uslug,
                result.ai_confidence,
            )
            
            return result
            
        except Exception as e:
            self.logger.exception("Categorization failed: %s", e)
            return KategoryzacjaAI(
                ai_confidence=0.0,
                ai_reasoning=f"Error: {str(e)}",
            )
    
    def _parse_response(self, response_text: str) -> KategoryzacjaAI:
        """Parsuje odpowiedź AI do KategoryzacjaAI."""
        import re
        
        self.logger.info("Raw AI response (%d chars)", len(response_text))
        
        # Usuń markdown code blocks jeśli są
        cleaned = response_text.strip()
        cleaned = re.sub(r"```json\s*", "", cleaned)
        cleaned = re.sub(r"```\s*", "", cleaned)
        cleaned = cleaned.strip()
        
        # Metoda 1: Znajdź JSON od pierwszego { do ostatniego }
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        
        self.logger.debug("Braces at: first=%d, last=%d", first_brace, last_brace)
        
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_str = cleaned[first_brace:last_brace + 1]
            
            try:
                data = json.loads(json_str)
                self.logger.info("Parsed JSON successfully with keys: %s", list(data.keys()))
                return self._build_kategoryzacja(data)
            except json.JSONDecodeError as e:
                self.logger.debug("First attempt failed: %s", e)
                
                # Metoda 2: Spróbuj naprawić - usuń trailing comma
                json_str = re.sub(r",\s*}", "}", json_str)
                json_str = re.sub(r",\s*]", "]", json_str)
                
                try:
                    data = json.loads(json_str)
                    self.logger.info("Parsed JSON after fix: %s", list(data.keys()))
                    return self._build_kategoryzacja(data)
                except json.JSONDecodeError:
                    pass
        
        # Metoda 3: Jeśli JSON jest niekompletny - napraw go
        if first_brace != -1:
            partial_json = cleaned[first_brace:]
            self.logger.info("Attempting to repair incomplete JSON (%d chars)", len(partial_json))
            
            repaired = partial_json
            
            # Usuń niekompletne pola tekstowe (np. "key": "wartość bez zamknięcia)
            repaired = re.sub(r',?\s*"[^"]*":\s*"[^"]*$', "", repaired)
            # Usuń niekompletne tablice (np. "key": ["wartość1", "wartość bez zamknięcia)
            repaired = re.sub(r',?\s*"[^"]*":\s*\[[^\]]*$', "", repaired)
            # Usuń trailing commas i whitespace
            repaired = repaired.rstrip(", \n\t")
            
            # Policz otwarte nawiasy
            open_braces = repaired.count("{") - repaired.count("}")
            open_brackets = repaired.count("[") - repaired.count("]")
            
            # Dodaj brakujące zamknięcia
            repaired += "]" * open_brackets + "}" * open_braces
            
            self.logger.debug("Repaired JSON: %s", repaired[:500])
            
            try:
                data = json.loads(repaired)
                self.logger.info("Repaired and parsed JSON: %s", list(data.keys()))
                return self._build_kategoryzacja(data)
            except json.JSONDecodeError as e:
                self.logger.warning("Repair failed: %s | Repaired: %s", e, repaired[:300])
        
        self.logger.warning("No valid JSON found in response: %s", cleaned[:500])
        return KategoryzacjaAI(ai_reasoning=f"No JSON in response: {cleaned[:200]}")
    
    def _build_kategoryzacja(self, data: dict) -> KategoryzacjaAI:
        """Buduje KategoryzacjaAI z rozparsowanego JSON-a."""
        
        # Waliduj i mapuj wartości
        return KategoryzacjaAI(
            platnik_uslug=self._validate_list(data.get("platnik_uslug", []), "platnik_uslug"),
            specjalizacja=self._validate_list(data.get("specjalizacja", []), "specjalizacja"),
            wielospecjalistyczne=self._validate_list(data.get("wielospecjalistyczne", []), "wielospecjalistyczne"),
            typ_wlasnosci=self._validate_single(data.get("typ_wlasnosci"), "typ_wlasnosci"),
            kategoria_konta=self._validate_single(data.get("kategoria_konta"), "kategoria_konta"),
            branza=data.get("branza"),
            ai_confidence=float(data.get("confidence", 0.5)),
            ai_reasoning=data.get("reasoning"),
        )
    
    def _validate_list(self, values: list, field: str) -> list[str]:
        """Waliduje listę wartości."""
        if not values or not isinstance(values, list):
            return []
        
        allowed = ALLOWED_VALUES.get(field, [])
        return [v for v in values if v in allowed]
    
    def _validate_single(self, value: str, field: str) -> Optional[str]:
        """Waliduje pojedynczą wartość."""
        if not value:
            return None
        
        allowed = ALLOWED_VALUES.get(field, [])
        return value if value in allowed else None
    
    async def close(self) -> None:
        """Zamyka zasoby."""
        pass
