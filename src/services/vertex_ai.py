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


# Prompt systemowy dla normalizacji danych B2B
NORMALIZATION_SYSTEM_PROMPT = """Jesteś ekspertem od ekstrakcji i normalizacji danych B2B w Polsce.
Przetwarzasz chaotyczne dane (surowy tekst, HTML, forwarded, quoted, podpisy mailowe, stopki).
Zwracasz wyłącznie jeden obiekt JSON w określonym formacie.
Bez markdown, bez komentarzy, bez wyjaśnień, bez tekstu przed ani po JSON.

ZASADY EKSTRAKCJI:
1. Wyodrębnij z treści dane osoby i firmy.
2. Ignoruj: reklamy, social media, automatyczne podpisy (np. "Sent from iPhone"), bannery, klauzule/disclaimery.
3. NIE ignoruj PODPISU SŁUŻBOWEGO - z niego wyciągaj dane (imię+nazwisko, stanowisko, firma, telefon/email).

ZASADY NORMALIZACJI:
1. Imiona i nazwiska: popraw wielkość liter (Jan Kowalski, nie JAN KOWALSKI).
2. title: wyciągnij tytuł naukowy/zawodowy jeśli jest (dr, dr n. med., dr hab., prof., lek., mgr, inż.) - NIE włączaj do first_name/last_name.
3. Nazwy firm: rozdziel nazwę od formy prawnej (sp. z o.o., S.A., sp.k., sp.j., s.c.).
4. company_keyword: 1-2 słowa kluczowe do wyszukiwania firmy (unikalny rdzeń nazwy, NIE ogólniki jak "MEDICAL", "CLINIC", "SP", "ZOO").
5. Telefony: znormalizuj do formatu +48XXXXXXXXX, rozróżnij phone (stacjonarny/służbowy) od mobile (komórkowy).
6. Email: lowercase.
7. NIP: tylko 10 cyfr (bez myślników).
8. Adresy: popraw wielkość liter.
9. Wykryj płeć na podstawie polskiego imienia.

Nie zgaduj danych — jeśli brak → null."""


NORMALIZATION_USER_PROMPT_TEMPLATE = """Przetwórz poniższe chaotyczne dane i zwróć ustrukturyzowany JSON:

DANE WEJŚCIOWE:
{input_data}

Zwróć JSON:
{{
  "first_name": "imię lub null",
  "last_name": "nazwisko lub null",
  "title": "tytuł naukowy/zawodowy (dr, prof., lek., mgr) lub null",
  "gender": "male/female/unknown",
  "salutation": "Pan/Pani lub null",
  "role": "stanowisko/funkcja lub null",
  "company_name": "nazwa firmy bez formy prawnej lub null",
  "company_legal_form": "forma prawna (sp. z o.o., S.A.) lub null",
  "company_full_name": "pełna nazwa z formą prawną lub null",
  "company_keyword": "1-2 słowa kluczowe do wyszukiwania lub null",
  "website": "domena firmowa lub null",
  "email": "email lowercase lub null",
  "phone": "telefon służbowy +48XXXXXXXXX lub null",
  "mobile": "telefon komórkowy +48XXXXXXXXX lub null",
  "nip": "10 cyfr lub null",
  "street": "ulica z numerem lub null",
  "city": "miasto lub null",
  "zip_code": "kod pocztowy XX-XXX lub null"
}}"""


# Prompt do klasyfikacji firmy na podstawie danych z internetu
CLASSIFICATION_SYSTEM_PROMPT = """Klasyfikujesz firmy medyczne w Polsce. Zwracasz TYLKO JSON, bez markdown."""


CLASSIFICATION_USER_PROMPT_TEMPLATE = """Sklasyfikuj firmę:

NAZWA: {company_name}
NIP: {nip}
ADRES: {address}

INFO Z INTERNETU:
{web_snippets}

Zwroc JSON (KROTKI, bez polskich znakow):
{{"industry":"Placowka medyczna","specjalizacja":["POZ"],"platnik_uslug":["NFZ","Komercyjne"],"is_medical_at_address":true,"address_type":"Siedziba i Filia","confidence":0.8,"reasoning":"przychodnia z kontraktem NFZ"}}

ZASADY:
- industry="Placowka medyczna" jesli przychodnia/szpital/klinika/NZOZ/SPZOZ
- specjalizacja - lista pasujacych (moze byc pusta [])
- platnik_uslug - NFZ jesli kontrakt, Komercyjne jesli prywatna (moze byc pusta [])
- is_medical_at_address=true jesli pod adresem sa gabinety/pacjenci
- address_type="Siedziba i Filia" jesli is_medical_at_address=true"""


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
                title=normalized_dict.get("title"),
                gender=normalized_dict.get("gender"),
                salutation=normalized_dict.get("salutation"),
                role=normalized_dict.get("role"),
                company_name=normalized_dict.get("company_name"),
                company_legal_form=normalized_dict.get("company_legal_form"),
                company_full_name=normalized_dict.get("company_full_name"),
                company_keyword=normalized_dict.get("company_keyword"),
                website=normalized_dict.get("website"),
                email=normalized_dict.get("email"),
                phone=normalized_dict.get("phone"),
                mobile=normalized_dict.get("mobile"),
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
    
    async def classify_company(
        self,
        company_name: str,
        nip: Optional[str] = None,
        address: Optional[str] = None,
        web_snippets: Optional[str] = None,
        sources: Optional[list] = None,
    ) -> dict:
        """
        Klasyfikuje firmę na podstawie informacji z internetu.
        
        Args:
            company_name: Nazwa firmy
            nip: NIP firmy
            address: Adres firmy
            web_snippets: Fragmenty tekstu z internetu
            sources: Lista źródeł
        
        Returns:
            Dict z klasyfikacją (industry, specjalizacja, platnik_uslug, address_type)
        """
        if not self._ensure_initialized():
            logger.warning("Vertex AI niedostępne - brak klasyfikacji")
            return {}
        
        try:
            # Przygotuj listę źródeł
            sources_text = ""
            if sources:
                sources_text = "\n".join([
                    f"- {s.get('title', 'brak tytułu')}: {s.get('url', '')}"
                    for s in sources[:5]
                ])
            
            prompt = CLASSIFICATION_USER_PROMPT_TEMPLATE.format(
                company_name=company_name or "brak",
                nip=nip or "brak",
                address=address or "brak",
                web_snippets=web_snippets or "brak informacji z internetu",
                sources=sources_text or "brak źródeł",
            )
            
            # Użyj osobnego modelu z innym system prompt
            from vertexai.generative_models import GenerativeModel
            
            classification_model = GenerativeModel(
                self.settings.vertex_ai_model,
                system_instruction=CLASSIFICATION_SYSTEM_PROMPT,
            )
            
            response = classification_model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 512,
                    "response_mime_type": "application/json",
                },
            )
            
            response_text = response.text.strip()
            
            # Usuń ewentualne markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])
            
            # Próba naprawy JSON - usuń trailing content po ostatnim }
            last_brace = response_text.rfind("}")
            if last_brace > 0:
                response_text = response_text[:last_brace + 1]
            
            result = json.loads(response_text)
            
            logger.info(
                "Sklasyfikowano firmę '%s': industry=%s, specjalizacja=%s",
                company_name,
                result.get("industry"),
                result.get("specjalizacja"),
            )
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error("Błąd parsowania klasyfikacji: %s | response: %s", e, response_text[:200] if response_text else "empty")
            # Zwróć domyślne wartości zamiast pustego dict
            return {
                "industry": None,
                "specjalizacja": [],
                "platnik_uslug": [],
                "is_medical_at_address": None,
                "address_type": None,
                "confidence": 0.0,
                "reasoning": f"Błąd parsowania AI: {str(e)[:50]}",
            }
        except Exception as e:
            logger.error("Błąd klasyfikacji firmy: %s", e)
            return {}


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
            title=input_data.get("title"),
            gender=gender,
            salutation="Pan" if gender == "male" else ("Pani" if gender == "female" else None),
            role=input_data.get("role") or input_data.get("stanowisko"),
            company_name=company_name,
            company_legal_form=legal_form,
            company_full_name=company_raw.strip().title() if company_raw else None,
            company_keyword=company_name.split()[0] if company_name and " " in company_name else company_name,
            website=input_data.get("website") or input_data.get("www"),
            email=email,
            phone=phone,
            mobile=normalize_phone(input_data.get("mobile") or input_data.get("telefon_komorkowy")),
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
