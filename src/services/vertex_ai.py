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
NORMALIZATION_SYSTEM_PROMPT = """Jesteś ekspertem od ekstrakcji i normalizacji danych B2B w Polsce - dla systemu Medidesk (rozwiązania IT dla placówek medycznych).
Przetwarzasz chaotyczne dane (surowy tekst, HTML, forwarded, quoted, podpisy mailowe, stopki).
Zwracasz wyłącznie jeden obiekt JSON w określonym formacie.
Bez markdown, bez komentarzy, bez wyjaśnień, bez tekstu przed ani po JSON.

KONTEKST BIZNESOWY:
Medidesk dostarcza rozwiązania dla placówek medycznych do komunikacji z pacjentem.
Relewantne firmy: placówki medyczne (przychodnie, kliniki, szpitale, NZOZ, gabinety), integratorzy systemów medycznych (HIS, EDM, HMS).
NIErelewantne firmy: technologiczne zagraniczn (Amazon, Google, Microsoft), budowlane, produkcyjne, handel (chyba że hurtownie medyczne).

ZASADY EKSTRAKCJI:
1. Wyodrębnij z treści dane osoby i firmy.
2. Ignoruj: reklamy, social media, automatyczne podpisy (np. "Sent from iPhone"), bannery, klauzule/disclaimery.
3. NIE ignoruj PODPISU SŁUŻBOWEGO - z niego wyciągaj dane (imię+nazwisko, stanowisko, firma, telefon/email).

ZASADY NORMALIZACJI:
1. Imiona i nazwiska: 
   - Pierwsza litera każdego słowa WIELKA, reszta małe (Jan Kowalski, Maria Nowak-Kowalska)
   - Dozwolone spacje i myślniki (nazwiska dwuczłonowe)
   - Sprawdź literówki, ALE nie zmieniaj na siłę imion obcych (ukraińskie, angielskie - George zostaje George, nie Grzegorz)
   - Jeśli w polu "Firma" jest imię osoby - przepisz do first_name/last_name, a company_name ustaw na null
2. title: wyciągnij tytuł naukowy/zawodowy (dr, prof., lek., mgr, inż.) - NIE włączaj do first_name/last_name.
3. Nazwy firm: 
   - Rozdziel nazwę od formy prawnej (sp. z o.o., S.A., sp.k.)
   - WAŻNE: Jeśli firma to wielka zagraniczna tech (Amazon, Google, Microsoft, Apple, Facebook/Meta) lub firma budowlana/produkcyjna - ustaw company_name na null (nierelewantna)
   - Jeśli to placeholder ("Właściciel firmy", "Firma osoby prywatnej") - ustaw null
   - Jeśli to Facebook/LinkedIn ID (długie cyfry) - ustaw null
4. company_keyword: 1-2 unikalne słowa (NIE ogólniki jak MEDICAL, CLINIC).
5. Telefony:
   - Polskie: +48 XXX XXX XXX
   - Zagraniczne: zachowaj prefix kraju +XX i formatuj
6. Email: WSZYSTKO MAŁYMI literami.
7. NIP: tylko 10 cyfr.
8. Województwa: MAŁYMI literami (małopolskie, mazowieckie).
9. Płeć: wykryj z polskiego imienia.
10. Polskie znaki diakrytyczne - KORYGUJ brakujące:
   - POPRAWIAJ imiona/nazwiska do poprawnej polskiej pisowni
   - Michal → Michał, Malgorzata → Małgorzata, Lukasz → Łukasz
   - Grazyna → Grażyna, Zolnierz → Żołnierz, Slawomir → Sławomir
   - Dab → Dąb, Zak → Żak, Sniezko → Śnieżko
   - Zawsze używaj poprawnych polskich znaków: ą, ć, ę, ł, ń, ó, ś, ź, ż
   - Przykład: "Michal Dab" → first_name: "Michał", last_name: "Dąb"
11. Adresy w surowym tekście:
   - Rozpoznaj wzorce adresów: ul./al./pl. + Nazwa + Numer, kody pocztowe XX-XXX
   - Jeśli raw_name zawiera "Ulica Numer Nazwisko" → wydziel adres do street, zachowaj nazwisko
   - Przykład: "Nowowiejska 11 Jasiewicz" → last_name: "Jasiewicz", street: "Nowowiejska 11"
   - Ulica/numer NIE są częścią nazwiska osoby
   - Jeśli brak imienia ale jest nazwisko → first_name: null, last_name: wypełnij
12. Zdrobnienia polskich imion (rozpoznaj ale NIE zamieniaj):
   - Rozpoznaj: Asia (=Joanna), Kasia (=Katarzyna), Gosia (=Małgorzata), Basia (=Barbara)
   - Zachowaj zdrobnienie w danych (Asia pozostaje Asia) - system rozwiąże je osobno

Nie zgaduj danych — jeśli brak lub nierelewantne → null."""


NORMALIZATION_USER_PROMPT_TEMPLATE = """Przetwórz poniższe chaotyczne dane i zwróć ustrukturyzowany JSON:

DANE WEJŚCIOWE:
{input_data}

PRZYKŁADY WALIDACJI FIRM:
- "Amazon", "Google", "Microsoft" → company_name: null (nierelewantne, zagraniczne tech)
- "Właściciel firmy", "2016610662466100" → company_name: null (placeholder/Facebook ID)
- "Waldemar" w polu Firma → first_name: "Waldemar", company_name: null (to imię osoby)
- "NZOZ Przychodnia Centrum", "Kamsoft" (integrator HIS) → company_name: OK (relewantne)

PRZYKŁADY PARSOWANIA ADRESÓW:
- "Nowowiejska 11 Katarzyna Jasiewicz" → first_name: "Katarzyna", last_name: "Jasiewicz", street: "Nowowiejska 11"
- "ul. Kowalskiego 5 Jan Nowak" → first_name: "Jan", last_name: "Nowak", street: "ul. Kowalskiego 5"
- "Consensus sp z o.o. Nowowiejska 11 Jasiewicz" → last_name: "Jasiewicz", company_name: "Consensus", street: "Nowowiejska 11"

Zwróć JSON:
{{
  "first_name": "imię lub null",
  "last_name": "nazwisko lub null",
  "title": "tytuł naukowy/zawodowy (dr, prof., lek., mgr) lub null",
  "gender": "male/female/unknown",
  "salutation": "Pan/Pani lub null",
  "role": "stanowisko/funkcja lub null",
  "company_name": "nazwa firmy bez formy prawnej lub null (null jeśli nierelewantna)",
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
            
            # Wywołaj model z retry
            max_retries = 2
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    response = self._model.generate_content(
                        prompt,
                        generation_config={
                            "temperature": 0.1 + (attempt * 0.1),  # Zwiększ temperaturę przy retry
                            "max_output_tokens": 4096,  # Duży limit - płacimy tylko za użyte
                            "response_mime_type": "application/json",
                        },
                    )
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning("AI attempt %d failed: %s, retrying...", attempt + 1, str(e)[:50])
                        import asyncio
                        await asyncio.sleep(1)
                    else:
                        raise last_error
            
            # Parsuj odpowiedź
            response_text = response.text.strip()
            
            # Cleanup - usuń markdown code blocks i trailing content
            if response_text.startswith("```"):
                # Usuń ```json lub ```
                response_text = response_text.split("\n", 1)[1] if "\n" in response_text else response_text[3:]
                # Usuń końcowe ```
                if response_text.endswith("```"):
                    response_text = response_text.rsplit("```", 1)[0]
            
            # Znajdź JSON object { ... }
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                response_text = response_text[start:end]
            
            # Próba naprawy częstych błędów JSON
            try:
                normalized_dict = json.loads(response_text)
            except json.JSONDecodeError as e:
                # Próba naprawy - dodaj brakujące zamknięcia
                logger.warning("Próba naprawy JSON: %s", str(e)[:50])
                
                # Napraw niekompletne stringi - zamknij ostatni string i obiekt
                fixed_text = response_text
                
                # Policz niezamknięte cudzysłowy
                in_string = False
                escape_next = False
                for i, c in enumerate(fixed_text):
                    if escape_next:
                        escape_next = False
                        continue
                    if c == '\\':
                        escape_next = True
                        continue
                    if c == '"':
                        in_string = not in_string
                
                # Jeśli w środku stringa, zamknij go
                if in_string:
                    fixed_text += '"'
                
                # Zamknij brakujące nawiasy
                open_braces = fixed_text.count('{') - fixed_text.count('}')
                fixed_text += '}' * open_braces
                
                try:
                    normalized_dict = json.loads(fixed_text)
                    logger.info("JSON naprawiony pomyślnie")
                except json.JSONDecodeError:
                    # Ostatnia próba - weź tylko to co się da sparsować
                    raise e  # Rzuć oryginalny błąd
            
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
            
            # Użyj Pro modelu do klasyfikacji (ten sam co do normalizacji)
            from vertexai.generative_models import GenerativeModel
            
            classification_model = GenerativeModel(
                self.settings.vertex_ai_model,  # gemini-2.5-pro
                system_instruction=CLASSIFICATION_SYSTEM_PROMPT,
            )
            
            response = classification_model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 2048,
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
    
    async def extract_locations(
        self,
        company_name: str,
        nip: str,
        raw_data: dict,
    ) -> dict:
        """
        Wyodrębnia listę placówek organizacji z surowych danych wyszukiwania.
        Używa chunkingu dla dużych list adresów.
        
        Args:
            company_name: Nazwa firmy/organizacji
            nip: NIP organizacji
            raw_data: Surowe dane z Brave Search (snippets, urls)
        
        Returns:
            Dict z listą placówek i metadanymi
        """
        if not self._ensure_initialized():
            logger.warning("Vertex AI niedostępne - brak ekstrakcji")
            return {"error": "AI niedostępne", "locations": []}
        
        try:
            import asyncio
            from vertexai.generative_models import GenerativeModel
            
            # Zbierz pełny tekst ze scraped pages
            scraped_pages = raw_data.get("scraped_pages", [])
            all_locations = []
            
            if scraped_pages:
                for page in scraped_pages:
                    if page.get("success"):
                        source_url = page.get("url", "")
                        # Użyj pełnego tekstu - priorytet dla dłuższego
                        text_content = page.get("text_content", "")
                        full_text_sample = page.get("full_text_sample", "")
                        full_text = text_content if len(text_content) > 500 else full_text_sample
                        
                        if not full_text or len(full_text) < 500:
                            logger.warning("Skipping %s - text too short (%d chars)", source_url, len(full_text))
                            continue
                        
                        # Podziel tekst na chunki (max 12k znaków per chunk)
                        chunk_size = 12000
                        text_chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
                        
                        logger.info(
                            "Extracting from %s: %d chars in %d chunks",
                            source_url,
                            len(full_text),
                            len(text_chunks),
                        )
                        
                        # Przetwórz każdy chunk tekstu
                        for idx, text_chunk in enumerate(text_chunks, 1):
                            prompt = f"""Extract ALL locations for: {company_name} (NIP: {nip})

TEXT FROM PAGE (part {idx}):
{text_chunk}

Find all locations with addresses. Return valid JSON array:
[
  {{"name": "location name or null", "city": "city", "address": "full street address", "postal_code": "XX-XXX", "phone": "phone or null", "source_url": "{source_url}"}}
]

Return ONLY the JSON array, nothing else."""

                            try:
                                model = GenerativeModel(
                                    self.settings.vertex_ai_model,
                                    system_instruction="Extract structured location data from text. Return ONLY valid JSON arrays.",
                                )
                                
                                # Większy token limit dla rozszerzonej struktury adresów
                                # ~250 tokenów na lokalizację (więcej pól)
                                estimated_locs = len(text_chunk) // 500  # Gruba estymacja
                                max_tokens = min(8192, max(4096, estimated_locs * 300))
                                
                                response = model.generate_content(
                                    prompt,
                                    generation_config={
                                        "temperature": 0.0,
                                        "max_output_tokens": max_tokens,
                                    },
                                )
                                
                                response_text = response.text.strip()
                                
                                # Cleanup
                                if response_text.startswith("```"):
                                    lines = response_text.split("\n")
                                    response_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                                
                                # Znajdź JSON array
                                start = response_text.find("[")
                                end = response_text.rfind("]") + 1
                                if start >= 0 and end > start:
                                    response_text = response_text[start:end]
                                
                                chunk_locations = json.loads(response_text)
                                if isinstance(chunk_locations, list):
                                    all_locations.extend(chunk_locations)
                                    logger.info("Chunk %d: extracted %d locations", idx, len(chunk_locations))
                                
                            except Exception as e:
                                logger.warning("Chunk %d extraction error: %s", idx, str(e)[:100])
                            
                            # Rate limit
                            if idx < len(text_chunks):
                                await asyncio.sleep(1)
            
            # Deduplikacja po adresie
            seen_addresses = set()
            unique_locations = []
            for loc in all_locations:
                addr_key = f"{loc.get('city', '')}|{loc.get('address', '')}"
                if addr_key not in seen_addresses:
                    seen_addresses.add(addr_key)
                    unique_locations.append(loc)
            
            # Multi-agent processing: Coordinator zarządza przepływem
            from ..services.location_processor import CoordinatorAgent
            from ..services.brave_search import get_brave_search_service
            
            brave = get_brave_search_service()
            coordinator = CoordinatorAgent(brave)
            
            # Strategy z raw_data lub domyślnie "balanced"
            strategy = raw_data.get("processing_strategy", "balanced")
            
            processed = await coordinator.process_locations(
                raw_locations=unique_locations,
                strategy=strategy
            )
            
            unique_locations = processed["locations"]
            processing_stats = processed["stats"]
            
            logger.info(
                "Multi-agent processing completed: %d locations, %d complete (%.1f%%)",
                processing_stats["total"],
                processing_stats["complete"],
                100 * processing_stats["complete"] / processing_stats["total"] if processing_stats["total"] > 0 else 0
            )
            
            logger.info(
                "Wyodrębniono %d unikalnych placówek dla '%s' (NIP: %s)",
                len(unique_locations),
                company_name,
                nip,
            )
            
            result = {
                "organization_name": company_name,
                "total_found": len(unique_locations),
                "locations": unique_locations,
                "notes": f"Multi-agent: {len(all_locations)} extracted, {len(unique_locations)} unique, {processing_stats['complete']} complete",
                "processing_stats": processing_stats,
            }
            
            return result
            
        except Exception as e:
            logger.error("Błąd ekstrakcji lokalizacji: %s", e, exc_info=True)
            return {
                "error": str(e),
                "organization_name": company_name,
                "total_found": 0,
                "locations": [],
            }


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
        
        # Firma - waliduj czy relewantna
        company_raw = input_data.get("company") or input_data.get("firma") or ""
        company_name, legal_form = self._extract_legal_form(company_raw)
        
        # Walidacja: odrzuć nierelewantne firmy
        if company_name:
            company_lower = company_name.lower()
            # Firmy zagraniczne tech (nierelewantne)
            irrelevant_companies = ["amazon", "google", "microsoft", "apple", "facebook", "meta", "linkedin"]
            # Placeholdery
            placeholders = ["właściciel", "firma osoby", "prywatna", "brak"]
            
            if any(irr in company_lower for irr in irrelevant_companies):
                company_name = None
                legal_form = None
            elif any(ph in company_lower for ph in placeholders):
                company_name = None
                legal_form = None
            # Facebook/LinkedIn ID (długie cyfry)
            elif company_raw.isdigit() and len(company_raw) > 10:
                company_name = None
                legal_form = None
        
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
