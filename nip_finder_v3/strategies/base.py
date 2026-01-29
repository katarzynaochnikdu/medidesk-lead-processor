"""
Bazowa klasa strategii wyszukiwania NIP.
"""

from abc import ABC, abstractmethod
from typing import Optional

from ..models import NIPResult


class BaseStrategy(ABC):
    """
    Bazowa klasa dla strategii wyszukiwania NIP.

    Każda strategia implementuje metodę find_nip() która zwraca NIPResult.
    """

    @abstractmethod
    async def find_nip(
        self,
        company_name: str,
        city: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> NIPResult:
        """
        Szuka NIP firmy.

        Args:
            company_name: Nazwa firmy (znormalizowana)
            city: Miasto (opcjonalne)
            domain: Domena firmowa z emaila (opcjonalne)

        Returns:
            NIPResult z wynikiem wyszukiwania
        """
        pass

    def _create_not_found_result(
        self,
        company_name: str,
        city: Optional[str] = None,
    ) -> NIPResult:
        """
        Tworzy wynik "nie znaleziono".

        Args:
            company_name: Nazwa firmy
            city: Miasto

        Returns:
            NIPResult z found=False
        """
        return NIPResult(
            company_name=company_name,
            city=city,
            found=False,
            nip=None,
            confidence=0.0,
        )
