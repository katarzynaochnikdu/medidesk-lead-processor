"""
Walidacja NIP przez GUS API (cross-reference).

Sprawdza czy NIP istnieje w GUS i dopasowuje nazwę firmy.
"""

import logging
from typing import Optional, Tuple

from ..config import NIPFinderV3Settings, get_settings
from ..utils import fuzzy_match

logger = logging.getLogger(__name__)


class GUSValidator:
    """
    Walidator NIP przez GUS API.

    Sprawdza czy NIP istnieje w bazie GUS i czy nazwa firmy pasuje.
    """

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()

    async def validate(
        self,
        nip: str,
        company_name: str,
    ) -> Tuple[bool, Optional[str], float]:
        """
        Sprawdza NIP w GUS i dopasowuje nazwę.

        Args:
            nip: NIP do sprawdzenia
            company_name: Nazwa firmy do dopasowania

        Returns:
            Tuple (found, gus_name, match_score)
            - found: czy NIP znaleziony w GUS
            - gus_name: nazwa firmy z GUS
            - match_score: wynik dopasowania nazwy (0.0-1.0)
        """
        logger.info("GUS validator: sprawdzam NIP %s dla firmy '%s'", nip, company_name)

        # TODO: Implementacja GUS API lookup
        # Na razie zwracamy (False, None, 0.0)

        logger.warning("GUS validator: funkcjonalność nie zaimplementowana (TODO)")
        return (False, None, 0.0)

        # Docelowo:
        # 1. Wywołaj GUS API DanePobierzPelnyRaport(NIP)
        # 2. Pobierz nazwę firmy z GUS
        # 3. Oblicz fuzzy_match(company_name, gus_name)
        # 4. Zwróć (True, gus_name, match_score)


# NOTE: GUS validator is incomplete - requires GUS API integration
# For now, always returns (False, None, 0.0)
# TODO: Implement full GUS API validation
