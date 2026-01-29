"""Test poprawek: zdrobnienia, polskie znaki, adresy."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config import get_settings
from src.services.data_normalizer import DataNormalizerService
from src.utils.validators import expand_diminutive
from src.services.zoho_search import normalize_polish_chars


def test_diminutives():
    """Test zdrobnień."""
    print("=== TEST ZDROBNIEŃ ===")
    
    test_cases = [
        ("asia", "Joanna"),
        ("joasia", "Joanna"),
        ("kasia", "Katarzyna"),
        ("gosia", "Malgorzata"),
        ("basia", "Barbara"),
        ("ela", "Elzbieta"),
    ]
    
    for input_name, expected in test_cases:
        result = expand_diminutive(input_name)
        status = "OK" if result == expected else "FAIL"
        print(f"  {input_name} -> {result} (oczekiwano: {expected}) [{status}]")


def test_polish_normalization():
    """Test normalizacji polskich znaków."""
    print("\n=== TEST NORMALIZACJI POLSKICH ZNAKÓW ===")
    
    test_cases = [
        ("Michał", "Michal"),
        ("Małgorzata", "Malgorzata"),
        ("Łukasz", "Lukasz"),
        ("Żółć", "Zolc"),
        ("ąćęłńóśźż", "acelnoszz"),
    ]
    
    for input_text, expected in test_cases:
        result = normalize_polish_chars(input_text)
        status = "OK" if result == expected else "FAIL"
        print(f"  {input_text} -> {result} (oczekiwano: {expected}) [{status}]")


async def test_ai_parsing():
    """Test parsowania AI na problematycznych przypadkach."""
    print("\n=== TEST PARSOWANIA AI ===")
    
    settings = get_settings()
    service = DataNormalizerService(settings=settings, use_mocks=False)
    
    test_cases = [
        {
            "name": "Adres z nazwiskiem",
            "input": {
                "raw_name": "Nowowiejska 11 Jasiewicz",
                "email": "k.jasiewicz@consensus.med.pl",
            },
            "expected_last_name": "Jasiewicz",
        },
        {
            "name": "Zdrobnienie Asia",
            "input": {
                "first_name": "Asia",
                "last_name": "Adam",
                "email": "nypi77ka@gmail.com",
            },
            "expected_first_name": "Joanna",  # Po expand_diminutive
        },
        {
            "name": "Polskie znaki",
            "input": {
                "first_name": "Michał",
                "last_name": "Dąb",
                "email": "michdabr2@gmail.com",
            },
            "expected_first_name": "Michał",  # Powinno zachować
        },
    ]
    
    for tc in test_cases:
        print(f"\n  [{tc['name']}]")
        print(f"    Input: {tc['input']}")
        
        try:
            output = await service.process_lead(
                raw_data=tc["input"],
                skip_ai=False,
                skip_gus=True,
                skip_duplicates=True,
            )
            
            normalized = output.normalized
            print(f"    Output: first_name={normalized.first_name}, last_name={normalized.last_name}")
            
            if "expected_last_name" in tc:
                status = "OK" if normalized.last_name == tc["expected_last_name"] else "SPRAWDZ"
                print(f"    last_name: {normalized.last_name} (oczekiwano: {tc['expected_last_name']}) [{status}]")
            
            if "expected_first_name" in tc:
                status = "OK" if normalized.first_name == tc["expected_first_name"] else "SPRAWDZ"
                print(f"    first_name: {normalized.first_name} (oczekiwano: {tc['expected_first_name']}) [{status}]")
                
        except Exception as e:
            print(f"    ERROR: {e}")
    
    await service.close()


if __name__ == "__main__":
    test_diminutives()
    test_polish_normalization()
    asyncio.run(test_ai_parsing())
    
    print("\n=== TESTY ZAKOŃCZONE ===")
