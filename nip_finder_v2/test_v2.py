"""
Test NIP Finder v2.

Testuje wyszukiwanie NIP na przykladowych firmach.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Dodaj root projektu do path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from nip_finder_v2 import NIPFinderV2, NIPResultV2

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# Przypadki testowe
TEST_CASES = [
    {
        "name": "Centrum Medyczne PragaMed",
        "city": "Warszawa",
        "expected_nip": "5223194230",  # Przykładowy - do weryfikacji
    },
    {
        "name": "Nu-med",
        "city": "Elblag",
        "expected_nip": None,  # Do sprawdzenia
    },
    {
        "name": "Medicover",
        "city": "Warszawa",
        "expected_nip": "5262057270",  # Przykładowy - do weryfikacji
    },
]


async def test_single(finder: NIPFinderV2, test_case: dict) -> dict:
    """Testuje pojedynczy przypadek."""
    name = test_case["name"]
    city = test_case.get("city")
    expected = test_case.get("expected_nip")
    
    print(f"\n{'='*60}")
    print(f"TEST: {name} ({city})")
    print(f"{'='*60}")
    
    result = await finder.find_nip(name, city)
    
    # Podsumowanie
    print(f"\n[RESULT]")
    print(f"  Found: {result.found}")
    print(f"  NIP: {result.nip}")
    print(f"  Strategy: {result.strategy}")
    print(f"  Confidence: {result.confidence}")
    print(f"  Time: {result.processing_time_ms}ms")
    
    if result.errors:
        print(f"  Errors: {result.errors}")
    
    if expected:
        match = result.nip == expected
        print(f"  Expected: {expected} -> {'OK' if match else 'MISMATCH'}")
    
    return {
        "name": name,
        "city": city,
        "found": result.found,
        "nip": result.nip,
        "strategy": str(result.strategy) if result.strategy else None,
        "confidence": result.confidence,
        "time_ms": result.processing_time_ms,
    }


async def run_tests():
    """Uruchamia wszystkie testy."""
    print("\n" + "="*60)
    print("NIP FINDER v2 - TEST")
    print("="*60)
    
    finder = NIPFinderV2()
    
    results = []
    
    for test_case in TEST_CASES:
        try:
            result = await test_single(finder, test_case)
            results.append(result)
        except Exception as e:
            print(f"\n[ERROR] {test_case['name']}: {e}")
            results.append({
                "name": test_case["name"],
                "error": str(e),
            })
    
    await finder.close()
    
    # Podsumowanie
    print("\n" + "="*60)
    print("PODSUMOWANIE")
    print("="*60)
    
    found = sum(1 for r in results if r.get("found"))
    total = len(results)
    
    print(f"Znaleziono: {found}/{total} ({100*found/total:.0f}%)")
    
    for r in results:
        status = "[OK]" if r.get("found") else "[--]"
        nip = r.get("nip", "N/A")
        strategy = r.get("strategy", "N/A")
        print(f"  {status} {r['name']}: NIP={nip} ({strategy})")


if __name__ == "__main__":
    asyncio.run(run_tests())
