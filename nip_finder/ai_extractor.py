"""
AI Extractor - wykorzystuje Vertex AI do:
1. Generowania optymalnych queries Google
2. Ekstrakcji NIP z tekstów
"""

import json
import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)


class AIExtractor:
    """
    Serwis AI do ekstrakcji NIP i generowania queries.
    Wykorzystuje Vertex AI (Gemini) z istniejącego projektu.
    """
    
    def __init__(self, settings: Optional[object] = None):
        """
        Args:
            settings: NIPFinderSettings (opcjonalne)
        """
        self.settings = settings
        self._vertex_model = None
        self._initialized = False
    
    def _ensure_initialized(self) -> bool:
        """Lazy initialization Vertex AI."""
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
            
            # Model do query generation i extraction
            self._vertex_model = GenerativeModel(
                self.settings.vertex_ai_model,  # gemini-2.5-pro
                system_instruction="""Jesteś ekspertem od wyszukiwania danych firm w Polsce.
Specjalizujesz się w:
1. Generowaniu optymalnych zapytań Google do znalezienia NIP firm
2. Wyciąganiu NIP z tekstów ze stron internetowych
3. Walidacji czy NIP pasuje do konkretnej firmy

Zwracasz TYLKO JSON, bez markdown, bez wyjaśnień."""
            )
            
            self._initialized = True
            logger.info("[OK] Vertex AI zainicjalizowany: model=%s", self.settings.vertex_ai_model)
            return True
            
        except ImportError:
            logger.warning("[WARN] Brak biblioteki google-cloud-aiplatform - AI niedostepne")
            return False
        except Exception as e:
            logger.error("[ERROR] Blad inicjalizacji Vertex AI: %s", e)
            return False
    
    async def generate_queries(
        self,
        company_name: str,
        city: Optional[str] = None,
        email: Optional[str] = None,
    ) -> List[str]:
        """
        Generuje 3-5 optymalnych zapytań Google do znalezienia NIP.
        
        Args:
            company_name: Nazwa firmy (może być chaotyczna)
            city: Miasto (opcjonalne)
            email: Email firmy (opcjonalne, dla domeny)
        
        Returns:
            Lista 3-5 zapytań Google
        """
        if not self._ensure_initialized():
            # Fallback - proste queries bez AI
            return self._generate_fallback_queries(company_name, city, email)
        
        try:
            # Wyciągnij domenę z emaila
            domain = None
            if email and "@" in email:
                domain = email.split("@")[-1]
            
            prompt = f"""Wygeneruj 3-5 najbardziej skutecznych zapytań Google do znalezienia NIP tej firmy:

Nazwa firmy: "{company_name}"
Miasto: "{city or "brak"}"
Domena email: "{domain or "brak"}"

Strategie:
1. Nazwa + miasto + "NIP"
2. Nazwa + "polityka prywatności" (NIP często w RODO)
3. Nazwa + "sp. z o.o." / "S.A." + "NIP" (dla firm z formą prawną)
4. Site search dla domeny: "site:{domain} NIP" (jeśli masz domenę)
5. Nazwa + "kontakt" + miasto

Zwróć JSON:
{{
  "queries": [
    "query 1",
    "query 2",
    ...
  ]
}}

WAŻNE:
- Queries MUSZĄ być po polsku
- Użyj polskich znaków (ą, ć, ę, ł, ń, ó, ś, ź, ż)
- Optymalizuj pod kątem polskich firm medycznych (przychodnie, kliniki, NZOZ)
- Max 5 queries
"""
            
            response = self._vertex_model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.2,  # Niska - chcemy przewidywalnych queries
                    "max_output_tokens": 1024,
                    "response_mime_type": "application/json",
                },
            )
            
            # Parsuj odpowiedź
            response_text = response.text.strip()
            response_text = self._clean_json_response(response_text)
            
            result = json.loads(response_text)
            queries = result.get("queries", [])
            
            if not queries:
                logger.warning("AI nie wygenerował queries - używam fallback")
                return self._generate_fallback_queries(company_name, city, email)
            
            logger.info("[OK] AI wygenerował %d queries", len(queries))
            return queries[:5]  # Max 5
            
        except Exception as e:
            logger.error("[ERROR] Blad generowania queries przez AI: %s", e)
            return self._generate_fallback_queries(company_name, city, email)
    
    async def extract_nip(
        self,
        company_name: str,
        scraped_texts: List[dict],
    ) -> Optional[dict]:
        """
        Wyciąga NIP z tekstów ze stron.
        
        Args:
            company_name: Nazwa firmy
            scraped_texts: Lista dict z {'url': ..., 'text': ...}
        
        Returns:
            Dict z:
            - nip: str (10 cyfr) lub None
            - confidence: float (0-1)
            - source_url: str
            - reasoning: str (wyjaśnienie AI)
            - text_snippet: str (fragment tekstu z NIP)
        """
        if not self._ensure_initialized():
            # Fallback - proste regex bez AI
            return self._extract_nip_fallback(company_name, scraped_texts)
        
        if not scraped_texts:
            logger.warning("Brak tekstów do analizy")
            return None
        
        try:
            # Połącz teksty w jeden korpus (max 50k znaków)
            max_length = self.settings.max_scrape_text_length if self.settings else 50000
            
            combined_sources = []
            total_chars = 0
            
            for item in scraped_texts:
                url = item.get("url", "")
                text = item.get("text", "")
                
                if not text:
                    continue
                
                # Truncate jeśli za długi
                remaining = max_length - total_chars
                if remaining <= 0:
                    break
                
                text_chunk = text[:remaining]
                combined_sources.append(f"=== URL: {url} ===\n{text_chunk}\n")
                total_chars += len(text_chunk)
            
            if not combined_sources:
                logger.warning("Brak tekstów po przetworzeniu")
                return None
            
            combined_text = "\n".join(combined_sources)
            
            prompt = f"""Znajdź NIP firmy "{company_name}" w poniższych tekstach ze stron internetowych.

TEKSTY:
{combined_text}

ZADANIE:
1. Znajdź wszystkie numery NIP (format: 10 cyfr lub XXX-XXX-XX-XX)
2. Zdecyduj który NIP należy do firmy "{company_name}"
3. Oceń pewność (confidence) na skali 0-1:
   - 1.0 = NIP jednoznacznie w kontekście nazwy firmy
   - 0.8 = NIP w stopce/polityce wraz z nazwą firmy
   - 0.5 = NIP znaleziony, ale bez bezpośredniego potwierdzenia nazwy
   - 0.0 = brak NIP

Zwróć JSON:
{{
  "nip": "1234567890" lub null,
  "confidence": 0.95,
  "source_url": "URL gdzie znaleziono",
  "reasoning": "dlaczego ten NIP pasuje do tej firmy",
  "text_snippet": "fragment tekstu z NIP (max 200 znaków)"
}}

WAŻNE:
- NIP MUSI mieć 10 cyfr
- Sprawdź czy nazwa firmy występuje w kontekście NIP
- Nie zgaduj - jeśli nie ma wyraźnego NIP, zwróć null
- Ignoruj NIP innych firm na stronie
"""
            
            response = self._vertex_model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.0,  # Zerowa - chcemy deterministycznej ekstrakcji
                    "max_output_tokens": 2048,
                    "response_mime_type": "application/json",
                },
            )
            
            # Parsuj odpowiedź
            response_text = response.text.strip()
            response_text = self._clean_json_response(response_text)
            
            result = json.loads(response_text)
            
            # Normalizuj NIP (usuń separatory)
            nip = result.get("nip")
            if nip:
                nip = re.sub(r'[-\s]', '', str(nip))
                if len(nip) == 10 and nip.isdigit():
                    result["nip"] = nip
                else:
                    logger.warning("NIP niepoprawny format: %s", nip)
                    result["nip"] = None
                    result["confidence"] = 0.0
            
            logger.info("[OK] AI extraction: nip=%s, confidence=%.2f",
                       result.get("nip") or "brak", result.get("confidence", 0))
            
            # Jesli AI nie znalazl NIP, probuj fallback regex
            if not result.get("nip"):
                logger.info("[INFO] AI nie znalazl NIP - probuje fallback regex")
                fallback_result = self._extract_nip_fallback(company_name, scraped_texts)
                if fallback_result and fallback_result.get("nip"):
                    logger.info("[OK] Fallback znalazl NIP: %s", fallback_result.get("nip"))
                    return fallback_result
            
            return result
            
        except Exception as e:
            logger.error("[ERROR] Blad ekstrakcji NIP przez AI: %s", e)
            return self._extract_nip_fallback(company_name, scraped_texts)
    
    def _generate_fallback_queries(
        self,
        company_name: str,
        city: Optional[str],
        email: Optional[str],
    ) -> List[str]:
        """Proste queries bez AI (fallback)."""
        queries = []
        
        # Wyciagnij bazowa nazwe (bez miasta w nazwie)
        base_name = self._extract_base_company_name(company_name)
        
        # Query 1: Podstawowe
        if city:
            queries.append(f'"{company_name}" "{city}" NIP')
        else:
            queries.append(f'"{company_name}" NIP')
        
        # Query 2: Bazowa nazwa (dla sieci klinik jak Nu-med Elblag -> Nu-med)
        if base_name != company_name:
            queries.append(f'"{base_name}" NIP KRS')
            queries.append(f'"{base_name}" spolka NIP')
        
        # Query 3: Polityka prywatnosci
        queries.append(f'"{company_name}" polityka prywatnosci')
        
        # Query 4: Z forma prawna
        queries.append(f'"{company_name}" sp. z o.o. NIP')
        
        # Query 5: Site search (jesli mamy domene)
        if email and "@" in email:
            domain = email.split("@")[-1]
            if "gmail" not in domain and "outlook" not in domain:
                queries.append(f'site:{domain} NIP')
        
        # Query 5: Kontakt
        if city:
            queries.append(f'"{company_name}" {city} kontakt')
        
        return queries[:5]
    
    def _extract_base_company_name(self, company_name: str) -> str:
        """
        Wyciaga bazowa nazwe firmy usuwajac miasto i inne sufiksy.
        Np. 'Nu-med Elblag' -> 'Nu-med'
            'Klinika XYZ Warszawa' -> 'Klinika XYZ'
        """
        import unicodedata
        
        def normalize_pl(text: str) -> str:
            """Usuwa polskie znaki diakrytyczne."""
            # Mapowanie polskich znakow
            pl_map = {
                'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
                'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
                'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
                'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z',
            }
            for pl, ascii in pl_map.items():
                text = text.replace(pl, ascii)
            return text
        
        # Lista polskich miast (najpopularniejsze)
        cities = [
            'Warszawa', 'Krakow', 'Lodz', 'Wroclaw', 'Poznan', 'Gdansk', 'Szczecin',
            'Bydgoszcz', 'Lublin', 'Katowice', 'Bialystok', 'Gdynia', 'Czestochowa',
            'Radom', 'Sosnowiec', 'Torun', 'Kielce', 'Gliwice', 'Zabrze', 'Bytom',
            'Olsztyn', 'Rzeszow', 'Rybnik', 'Ruda Slaska', 'Tychy', 'Dabrowa Gornicza',
            'Plock', 'Elblag', 'Opole', 'Gorzow Wielkopolski', 'Walbrzych', 'Zielona Gora',
            'Wloclawek', 'Tarnow', 'Chorzow', 'Koszalin', 'Kalisz', 'Legnica', 'Grudziadz',
            'Slupsk', 'Jaworzno', 'Jastrzebie-Zdroj', 'Nowy Sacz', 'Jelenia Gora', 'Siedlce',
            'Myslowice', 'Konin', 'Piotrkow Trybunalski', 'Lubin', 'Inowroclaw', 'Ostrow Wlkp',
            'Suwalki', 'Gniezno', 'Glogow', 'Pruszkow', 'Zamosc', 'Tomaszow Mazowiecki',
        ]
        
        # Normalizuj nazwe (usun polskie znaki dla porownania)
        name_normalized = normalize_pl(company_name).lower()
        
        for city in cities:
            city_lower = city.lower()
            # Sprawdz czy miasto jest na koncu nazwy
            if name_normalized.endswith(' ' + city_lower):
                # Usun miasto z oryginalnej nazwy
                return company_name[:-(len(city)+1)].strip()
            # Sprawdz z myslnikiem
            if name_normalized.endswith('-' + city_lower):
                return company_name[:-(len(city)+1)].strip()
        
        return company_name
    
    def _extract_nip_fallback(
        self,
        company_name: str,
        scraped_texts: List[dict],
    ) -> Optional[dict]:
        """Prosta ekstrakcja NIP regex (fallback bez AI)."""
        # Wzorce NIP - kolejnosc od najdokladniejszych
        patterns = [
            # NIP: XXX-XXX-XX-XX lub NIP: XXXXXXXXXX
            r'NIP\s*[:/]?\s*(?:VAT\s*)?(\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2})',
            r'NIP\s*[:/]?\s*(?:VAT\s*)?(\d{10})',
            # Numer NIP:
            r'[Nn]umer\s+NIP\s*[:/]?\s*(\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2})',
            r'[Nn]umer\s+NIP\s*[:/]?\s*(\d{10})',
            # Standalone format XXX-XXX-XX-XX
            r'\b(\d{3}-\d{3}-\d{2}-\d{2})\b',
            r'\b(\d{3}\s\d{3}\s\d{2}\s\d{2})\b',
        ]
        
        for item in scraped_texts:
            url = item.get("url", "")
            text = item.get("text", "")
            
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    # Normalizuj
                    nip = re.sub(r'[-\s]', '', match)
                    if len(nip) == 10 and nip.isdigit():
                        # Znaleziono NIP - ale bez AI nie wiemy czy to właściwy
                        return {
                            "nip": nip,
                            "confidence": 0.5,  # Niska - bo bez AI validation
                            "source_url": url,
                            "reasoning": "NIP znaleziony przez regex (bez AI validation)",
                            "text_snippet": text[max(0, text.find(match)-50):text.find(match)+50],
                        }
        
        return None
    
    def _clean_json_response(self, text: str) -> str:
        """Czysci odpowiedz AI - usuwa markdown code blocks itp."""
        # Usun markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        
        # Znajdz JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        
        text = text.strip()
        
        # Naprawa typowych bledow JSON
        # 1. Newline wewnatrz stringow - zamien na spacje
        import re
        
        # Znajdz wszystkie stringi i zamien w nich newline na spacje
        def fix_string(match):
            s = match.group(0)
            # Zamien newline na spacje, zachowaj cudzyslow
            return s.replace('\n', ' ').replace('\r', ' ')
        
        # Pattern dla stringow JSON (z escapowaniem)
        try:
            text = re.sub(r'"(?:[^"\\]|\\.)*"', fix_string, text)
        except:
            pass
        
        # 2. Trailing comma przed zamknieciem
        text = re.sub(r',\s*}', '}', text)
        text = re.sub(r',\s*]', ']', text)
        
        return text
