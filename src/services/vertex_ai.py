"""
Serwis Vertex AI - normalizacja danych przez Gemini.
Modułowy design - łatwy do rozszerzenia o nowe funkcje AI.
"""

import json
import logging
from typing import Any, Optional

from ..config import Settings, get_settings
from ..models.lead_output import NormalizedData

logger = logging.getLogger(__name__)


# Prompt systemowy dla normalizacji danych
NORMALIZATION_SYSTEM_PROMPT = """Jesteś ekspertem od normalizacji danych kontaktowych i firmowych w Polsce.
Twoje zadanie to przyjąć chaotyczne dane i zwrócić je w ustrukturyzowanej formie.

ZASADY:
1. Imiona i nazwiska: popraw wielkość liter (Jan Kowalski, nie JAN KOWALSKI)
2. Rozdziel imię od nazwiska jeśli są razem
3. Wykryj płeć na podstawie polskiego imienia (męskie/żeńskie)
4. Nazwy firm: rozdziel nazwę od formy prawnej (sp. z o.o., S.A., etc.)
5. Telefony: znormalizuj do formatu +48XXXXXXXXX
6. Email: lowercase
7. NIP: tylko 10 cyfr (bez myślników)
8. Adresy: popraw wielkość liter w nazwach miast i ulic

POLSKIE IMIONA MĘSKIE (przykłady): Jan, Piotr, Andrzej, Krzysztof, Tomasz, Michał, Marcin, Adam, Paweł, Marek
POLSKIE IMIONA ŻEŃSKIE (przykłady): Anna, Maria, Katarzyna, Małgorzata, Agnieszka, Barbara, Ewa, Magdalena, Joanna, Monika

FORMY PRAWNE FIRM: sp. z o.o., spółka z ograniczoną odpowiedzialnością, S.A., spółka akcyjna, sp.k., sp.j., s.c.

Odpowiadaj TYLKO w formacie JSON bez dodatkowego tekstu."""


NORMALIZATION_USER_PROMPT_TEMPLATE = """Znormalizuj poniższe dane:

DANE WEJŚCIOWE:
{input_data}

Zwróć JSON z polami:
{{
  "first_name": "imię lub null",
  "last_name": "nazwisko lub null", 
  "gender": "male/female/unknown",
  "salutation": "Pan/Pani lub null",
  "company_name": "nazwa firmy bez formy prawnej lub null",
  "company_legal_form": "forma prawna lub null",
  "company_full_name": "pełna nazwa z formą prawną lub null",
  "email": "email lowercase lub null",
  "phone": "telefon +48XXXXXXXXX lub null",
  "nip": "10 cyfr lub null",
  "street": "ulica lub null",
  "city": "miasto lub null",
  "zip_code": "kod pocztowy XX-XXX lub null"
}}"""


class VertexAIService:
    """
    Serwis do komunikacji z Vertex AI (Gemini).
    Obsługuje normalizację danych i inne zadania AI.
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._client = None
        self._model = None
        self._initialized = False
    
    def _ensure_initialized(self) -> bool:
        """Lazy initialization - inicjalizuj tylko gdy potrzebne."""
        if self._initialized:
            return True
        
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            
            # Inicjalizacja Vertex AI
            vertexai.init(
                project=self.settings.gcp_project_id,
                location=self.settings.gcp_region,
            )
            
            # Załaduj model
            self._model = GenerativeModel(
                self.settings.vertex_ai_model,
                system_instruction=NORMALIZATION_SYSTEM_PROMPT,
            )
            
            self._initialized = True
            logger.info(
                "Vertex AI zainicjalizowany: project=%s, region=%s, model=%s",
                self.settings.gcp_project_id,
                self.settings.gcp_region,
                self.settings.vertex_ai_model,
            )
            return True
            
        except ImportError:
            logger.warning("Brak biblioteki google-cloud-aiplatform - AI niedostępne")
            return False
        except Exception as e:
            logger.error("Błąd inicjalizacji Vertex AI: %s", e)
            return False
    
    async def normalize_data(self, input_data: dict[str, Any]) -> NormalizedData:
        """
        Normalizuje dane wejściowe przy użyciu Gemini.
        
        Args:
            input_data: Surowe dane do normalizacji
        
        Returns:
            NormalizedData - znormalizowane dane
        """
        if not self._ensure_initialized():
            logger.warning("Vertex AI niedostępne - użyj fallbacku")
            raise RuntimeError("Vertex AI not initialized")
        
        try:
            # Przygotuj prompt
            input_json = json.dumps(input_data, ensure_ascii=False, indent=2)
            prompt = NORMALIZATION_USER_PROMPT_TEMPLATE.format(input_data=input_json)
            
            # Wywołaj model
            response = self._model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,  # Niska temperatura = bardziej deterministyczne
                    "max_output_tokens": 1024,
                    "response_mime_type": "application/json",
                },
            )
            
            # Parsuj odpowiedź
            response_text = response.text.strip()
            
            # Usuń ewentualne markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])
            
            normalized_dict = json.loads(response_text)
            
            # Konwertuj na model
            return NormalizedData(
                first_name=normalized_dict.get("first_name"),
                last_name=normalized_dict.get("last_name"),
                gender=normalized_dict.get("gender"),
                salutation=normalized_dict.get("salutation"),
                company_name=normalized_dict.get("company_name"),
                company_legal_form=normalized_dict.get("company_legal_form"),
                company_full_name=normalized_dict.get("company_full_name"),
                email=normalized_dict.get("email"),
                phone=normalized_dict.get("phone"),
                nip=normalized_dict.get("nip"),
                street=normalized_dict.get("street"),
                city=normalized_dict.get("city"),
                zip_code=normalized_dict.get("zip_code"),
            )
            
        except json.JSONDecodeError as e:
            logger.error("Błąd parsowania odpowiedzi AI: %s", e)
            raise  # Rzuć wyjątek, żeby data_normalizer użył fallbacku
        except Exception as e:
            logger.error("Błąd normalizacji przez AI: %s", e)
            raise  # Rzuć wyjątek, żeby data_normalizer użył fallbacku
    
    async def detect_gender(self, first_name: str) -> Optional[str]:
        """
        Wykrywa płeć na podstawie imienia.
        
        Args:
            first_name: Imię
        
        Returns:
            "male", "female" lub None
        """
        if not self._ensure_initialized() or not first_name:
            return None
        
        try:
            prompt = f"""Określ płeć osoby o imieniu: {first_name}

Odpowiedz TYLKO jednym słowem: male, female lub unknown"""
            
            response = self._model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.0,
                    "max_output_tokens": 10,
                },
            )
            
            result = response.text.strip().lower()
            if result in ("male", "female"):
                return result
            return None
            
        except Exception as e:
            logger.error("Błąd wykrywania płci: %s", e)
            return None
    
    async def standardize_company_name(self, company_name: str) -> dict[str, Optional[str]]:
        """
        Standaryzuje nazwę firmy - rozdziela nazwę od formy prawnej.
        
        Args:
            company_name: Nazwa firmy
        
        Returns:
            Dict z "name", "legal_form", "full_name"
        """
        if not self._ensure_initialized() or not company_name:
            return {"name": None, "legal_form": None, "full_name": None}
        
        try:
            prompt = f"""Rozdziel nazwę firmy od formy prawnej:
"{company_name}"

Zwróć JSON:
{{"name": "nazwa bez formy prawnej", "legal_form": "forma prawna lub null", "full_name": "pełna poprawna nazwa"}}"""
            
            response = self._model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.0,
                    "max_output_tokens": 256,
                    "response_mime_type": "application/json",
                },
            )
            
            return json.loads(response.text.strip())
            
        except Exception as e:
            logger.error("Błąd standaryzacji nazwy firmy: %s", e)
            return {"name": company_name, "legal_form": None, "full_name": company_name}


class VertexAIServiceMock:
    """
    Mock serwisu Vertex AI do testów lokalnych bez GCP.
    Używa prostych reguł zamiast AI.
    """
    
    # Polskie imiona i płeć
    MALE_NAMES = {
        "jan", "piotr", "andrzej", "krzysztof", "tomasz", "michał", "marcin",
        "adam", "paweł", "marek", "stanisław", "wojciech", "jacek", "robert",
        "rafał", "jakub", "sebastian", "łukasz", "maciej", "dariusz", "artur",
    }
    
    FEMALE_NAMES = {
        "anna", "maria", "katarzyna", "małgorzata", "agnieszka", "barbara",
        "ewa", "magdalena", "joanna", "monika", "krystyna", "danuta", "zofia",
        "teresa", "halina", "irena", "elżbieta", "aleksandra", "karolina", "natalia",
    }
    
    LEGAL_FORMS = [
        ("spółka z ograniczoną odpowiedzialnością", "sp. z o.o."),
        ("sp. z o.o.", "sp. z o.o."),
        ("sp.z" "o.o.", "sp. z o.o."),
        ("spółka akcyjna", "S.A."),
        ("s.a.", "S.A."),
        ("spółka komandytowa", "sp.k."),
        ("sp.k.", "sp.k."),
        ("spółka jawna", "sp.j."),
        ("sp.j.", "sp.j."),
        ("spółka cywilna", "s.c."),
        ("s.c.", "s.c."),
    ]
    
    async def normalize_data(self, input_data: dict[str, Any]) -> NormalizedData:
        """Prosta normalizacja bez AI."""
        from ..utils.validators import normalize_nip, normalize_phone
        
        # Wyciągnij dane
        raw_name = input_data.get("raw_name") or input_data.get("full_name") or ""
        first_name = input_data.get("first_name") or input_data.get("imie")
        last_name = input_data.get("last_name") or input_data.get("nazwisko")
        
        # Rozdziel imię i nazwisko jeśli trzeba
        if not first_name and not last_name and raw_name:
            parts = raw_name.strip().split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = " ".join(parts[1:])
            elif len(parts) == 1:
                last_name = parts[0]
        
        # Popraw wielkość liter
        if first_name:
            first_name = first_name.strip().title()
        if last_name:
            last_name = last_name.strip().title()
        
        # Wykryj płeć
        gender = None
        if first_name:
            name_lower = first_name.lower()
            if name_lower in self.MALE_NAMES:
                gender = "male"
            elif name_lower in self.FEMALE_NAMES:
                gender = "female"
        
        # Firma
        company_raw = input_data.get("company") or input_data.get("firma") or ""
        company_name, legal_form = self._extract_legal_form(company_raw)
        
        # Kontakt
        email = input_data.get("email")
        if email:
            email = email.strip().lower()
        
        phone = normalize_phone(input_data.get("phone") or input_data.get("telefon_komorkowy"))
        nip = normalize_nip(input_data.get("nip"))
        
        return NormalizedData(
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            salutation="Pan" if gender == "male" else ("Pani" if gender == "female" else None),
            company_name=company_name,
            company_legal_form=legal_form,
            company_full_name=company_raw.strip().title() if company_raw else None,
            email=email,
            phone=phone,
            nip=nip,
            street=input_data.get("street"),
            city=input_data.get("city"),
            zip_code=input_data.get("zip_code"),
        )
    
    def _extract_legal_form(self, company: str) -> tuple[Optional[str], Optional[str]]:
        """Wyciąga formę prawną z nazwy firmy."""
        if not company:
            return None, None
        
        company_lower = company.lower()
        
        for pattern, normalized in self.LEGAL_FORMS:
            if pattern in company_lower:
                # Usuń formę prawną z nazwy
                idx = company_lower.find(pattern)
                name = company[:idx].strip()
                # Usuń końcowe znaki interpunkcyjne
                name = name.rstrip(" -–—,.")
                return name.title() if name else None, normalized
        
        return company.strip().title(), None
    
    async def detect_gender(self, first_name: str) -> Optional[str]:
        """Wykrywa płeć na podstawie listy imion."""
        if not first_name:
            return None
        
        name_lower = first_name.strip().lower()
        if name_lower in self.MALE_NAMES:
            return "male"
        elif name_lower in self.FEMALE_NAMES:
            return "female"
        return None
    
    async def standardize_company_name(self, company_name: str) -> dict[str, Optional[str]]:
        """Standaryzuje nazwę firmy."""
        name, legal_form = self._extract_legal_form(company_name)
        return {
            "name": name,
            "legal_form": legal_form,
            "full_name": company_name.strip().title() if company_name else None,
        }


def get_vertex_ai_service(settings: Optional[Settings] = None, use_mock: bool = False):
    """
    Factory function - zwraca odpowiedni serwis AI.
    
    Args:
        settings: Ustawienia aplikacji
        use_mock: Czy użyć mocka (do testów lokalnych)
    
    Returns:
        VertexAIService lub VertexAIServiceMock
    """
    if use_mock:
        return VertexAIServiceMock()
    
    settings = settings or get_settings()
    
    # Jeśli brak konfiguracji GCP, użyj mocka
    if not settings.gcp_project_id:
        logger.warning("Brak GCP_PROJECT_ID - używam mocka AI")
        return VertexAIServiceMock()
    
    return VertexAIService(settings)
