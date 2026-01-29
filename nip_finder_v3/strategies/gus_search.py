"""
GUS API Search - wyszukuje firmę po nazwie w oficjalnym rejestrze.

GUS (Główny Urząd Statystyczny) to oficjalne źródło danych o firmach.
Success rate: 60-70% (depends on name matching)
Cost: FREE
Time: 1-3s
"""

import logging
from typing import Optional
from xml.etree import ElementTree as ET

from zeep import Client
from zeep.exceptions import Fault

from ..config import NIPFinderV3Settings, get_settings
from ..models import NIPResult, SearchStrategy
from ..utils import format_nip, fuzzy_match, normalize_company_name
from .base import BaseStrategy

logger = logging.getLogger(__name__)


class GUSSearchStrategy(BaseStrategy):
    """
    Strategia: Wyszukiwanie w GUS API po nazwie firmy.

    Używa SOAP API GUS BIR1 do wyszukiwania firm po nazwie.
    """

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()
        self._client: Optional[Client] = None
        self._session_id: Optional[str] = None

    @property
    def client(self) -> Optional[Client]:
        """Lazy SOAP client."""
        if self._client is None and self.settings.gus_api_key:
            try:
                self._client = Client(self.settings.gus_api_url)
            except Exception as e:
                logger.error("GUS: nie można utworzyć klienta SOAP: %s", e)
                return None
        return self._client

    async def find_nip(
        self,
        company_name: str,
        city: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> NIPResult:
        """
        Szuka firmy w GUS API po nazwie.

        Args:
            company_name: Nazwa firmy
            city: Miasto (używane do filtrowania wyników)
            domain: Domena (nieużywana)

        Returns:
            NIPResult
        """
        if not self.settings.gus_api_key:
            logger.warning("GUS: brak API key - pomijam")
            return self._create_not_found_result(company_name, city)

        if not self.client:
            logger.warning("GUS: klient SOAP niedostępny - pomijam")
            return self._create_not_found_result(company_name, city)

        logger.info("GUS search: szukam '%s' w GUS", company_name)

        try:
            # Zaloguj się do GUS API
            if not self._session_id:
                self._session_id = self.client.service.Zaloguj(self.settings.gus_api_key)
                logger.debug("GUS: zalogowano, session_id=%s", self._session_id)

            # Normalizuj nazwę do wyszukiwania
            search_name = normalize_company_name(company_name)

            # Wyszukaj firmy po nazwie
            # Używamy DaneSzukajPodmioty z parametrem Nazwa
            results = self.client.service.DaneSzukajPodmioty({
                "Nazwa": search_name
            })

            if not results:
                logger.info("❌ GUS search: brak wyników dla '%s'", company_name)
                return self._create_not_found_result(company_name, city)

            # Parsuj wyniki XML
            candidates = self._parse_gus_results(results)

            if not candidates:
                logger.warning("⚠️ GUS search: brak wyników dla '%s'", company_name)
                return self._create_not_found_result(company_name, city)

            # Dopasuj fuzzy do najlepszego kandydata
            best_match = None
            best_score = 0.0

            for candidate in candidates:
                score = fuzzy_match(company_name, candidate.get("name", ""))

                # Bonus za dopasowanie miasta
                if city and candidate.get("city"):
                    city_match = normalize_company_name(city) == normalize_company_name(candidate["city"])
                    if city_match:
                        score += 0.2  # Boost za matching city

                if score > best_score:
                    best_score = score
                    best_match = candidate

            # Próg akceptacji (70%)
            if best_score < self.settings.fuzzy_match_threshold:
                logger.warning(
                    "⚠️ GUS search: najlepsze dopasowanie %.2f < %.2f (threshold) dla '%s'",
                    best_score,
                    self.settings.fuzzy_match_threshold,
                    company_name
                )
                return self._create_not_found_result(company_name, city)

            nip = best_match.get("nip", "")
            if not nip:
                logger.warning("⚠️ GUS search: brak NIP w wyniku dla '%s'", company_name)
                return self._create_not_found_result(company_name, city)

            logger.info(
                "✅ GUS search: found NIP=%s for '%s' (match=%.2f, gus_name='%s')",
                nip,
                company_name,
                best_score,
                best_match.get("name", "")
            )

            return NIPResult(
                found=True,
                nip=self._format_nip(nip),
                nip_formatted=self._format_nip(nip, formatted=True),
                confidence=1.0,  # GUS jest oficjalnym źródłem = 100% pewności
                strategy_used=SearchStrategy.GUS_SEARCH,
                metadata={
                    "gus_company_name": best_match.get("name"),
                    "gus_city": best_match.get("city"),
                    "gus_voivodeship": best_match.get("voivodeship"),
                    "gus_regon": best_match.get("regon"),
                    "fuzzy_match_score": best_score,
                },
            )

        except Fault as e:
            logger.error("GUS SOAP Fault: %s", e)
            return self._create_not_found_result(company_name, city)
        except Exception as e:
            logger.error("GUS error: %s", e)
            return self._create_not_found_result(company_name, city)

    def _parse_gus_results(self, xml_string: str) -> list[dict]:
        """
        Parsuje XML response z GUS API.

        Args:
            xml_string: XML string z wynikami

        Returns:
            Lista słowników z danymi firm
        """
        if not xml_string or not xml_string.strip():
            return []

        try:
            root = ET.fromstring(xml_string)

            candidates = []

            # GUS zwraca listę elementów <dane> z danymi firm
            for dane in root.findall(".//dane"):
                nip = dane.findtext("Nip", "")
                regon = dane.findtext("Regon", "")
                name = dane.findtext("Nazwa", "")
                voivodeship = dane.findtext("Wojewodztwo", "")
                city = dane.findtext("Miejscowosc", "")

                if nip and name:
                    candidates.append({
                        "nip": nip.strip(),
                        "regon": regon.strip(),
                        "name": name.strip(),
                        "voivodeship": voivodeship.strip(),
                        "city": city.strip(),
                    })

            logger.debug("GUS: znaleziono %d kandydatów", len(candidates))
            return candidates

        except ET.ParseError as e:
            logger.error("GUS: błąd parsowania XML: %s", e)
            return []
        except Exception as e:
            logger.error("GUS: nieoczekiwany błąd podczas parsowania: %s", e)
            return []

    def _format_nip(self, nip: str, formatted: bool = False) -> str:
        """Format NIP number."""
        return format_nip(nip, formatted=formatted)

    async def close(self):
        """Wyloguj z GUS API."""
        if self._session_id and self.client:
            try:
                self.client.service.Wyloguj(self._session_id)
                self._session_id = None
                logger.debug("GUS: wylogowano")
            except Exception as e:
                logger.error("GUS: błąd podczas wylogowania: %s", e)
