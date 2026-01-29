"""
Test NIP Finder - testy jednostkowe i integracyjne.
"""

import asyncio
import pytest

from nip_finder.models import NIPRequest
from nip_finder.orchestrator import NIPFinder


class TestNIPFinder:
    """Testy NIPFinder."""
    
    @pytest.mark.asyncio
    async def test_single_search_simple(self):
        """Test pojedynczego wyszukiwania - prosta nazwa."""
        finder = NIPFinder(use_cache=False)  # Bez cache dla testów
        
        result = await finder.find_nip(
            company_name="Medidesk sp. z o.o.",
            city="Wrocław",
        )
        
        assert result is not None
        assert result.company_name == "Medidesk sp. z o.o."
        
        # Jeśli znaleziono
        if result.found:
            assert result.nip is not None
            assert len(result.nip) == 10
            assert result.confidence > 0
        
        await finder.close()
    
    @pytest.mark.asyncio
    async def test_single_search_with_email(self):
        """Test z domeną email."""
        finder = NIPFinder(use_cache=False)
        
        result = await finder.find_nip(
            company_name="Medidesk",
            email="kontakt@medidesk.pl",
        )
        
        assert result is not None
        
        await finder.close()
    
    @pytest.mark.asyncio
    async def test_batch_processing(self):
        """Test batch processing."""
        finder = NIPFinder(use_cache=False)
        
        requests = [
            NIPRequest(company_name="Medidesk sp. z o.o.", city="Wrocław"),
            NIPRequest(company_name="Kamsoft", city="Katowice"),
            NIPRequest(company_name="Luxmed", city="Warszawa"),
        ]
        
        results = await finder.batch_find_nip(requests, max_concurrent=2)
        
        assert len(results) == 3
        assert all(r.company_name for r in results)
        
        await finder.close()
    
    @pytest.mark.asyncio
    async def test_cache(self):
        """Test cache."""
        finder = NIPFinder(use_cache=True)
        
        # Pierwsze wyszukiwanie - cache miss
        result1 = await finder.find_nip(
            company_name="Test Firma",
            city="Warszawa",
        )
        
        # Drugie wyszukiwanie - cache hit
        result2 = await finder.find_nip(
            company_name="Test Firma",
            city="Warszawa",
        )
        
        # Cache powinien zwrócić ten sam wynik szybciej
        assert result2.strategy_used == "cache" or result1.processing_time_ms >= result2.processing_time_ms
        
        await finder.close()


def test_checksum():
    """Test walidacji checksum NIP."""
    from nip_finder.validator import NIPValidator
    
    validator = NIPValidator()
    
    # Prawidłowy NIP (przykład)
    assert validator._validate_checksum("5260250995")  # Medidesk sp. z o.o.
    
    # Nieprawidłowy NIP
    assert not validator._validate_checksum("1234567890")
    assert not validator._validate_checksum("123")
    assert not validator._validate_checksum("abc")


def test_fuzzy_matching():
    """Test fuzzy matching nazw firm."""
    from nip_finder.validator import NIPValidator
    
    validator = NIPValidator()
    
    # Identyczne
    score1 = validator._fuzzy_match_names(
        "MEDIDESK SP. Z O.O.",
        "MEDIDESK SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ"
    )
    assert score1 > 0.8
    
    # Podobne
    score2 = validator._fuzzy_match_names(
        "Przychodnia ABC",
        "NZOZ Przychodnia ABC"
    )
    assert score2 > 0.7
    
    # Różne
    score3 = validator._fuzzy_match_names(
        "Firma A",
        "Firma B"
    )
    assert score3 < 0.8


if __name__ == "__main__":
    # Uruchom testy
    pytest.main([__file__, "-v", "-s"])
