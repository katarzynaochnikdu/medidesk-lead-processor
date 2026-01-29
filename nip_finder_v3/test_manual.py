"""
Test NIP Finder V3 na 3 przykładowych firmach.

Firmy testowe (z V2 test):
1. Nu-med (Elbląg) - Expected: 7411906987
2. Medicover (Warszawa) - Expected: 5262057270
3. Centrum Medyczne PragaMed (Warszawa) - Expected: 5223194230
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from nip_finder_v3 import NIPFinderV3, NIPRequest

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# Test cases
TEST_CASES = [
    {
        "name": "Nu-med",
        "city": "Elbląg",
        "email": "recepcja@nu-med.pl",  # DOMENA - uruchomi privacy/homepage strategies!
        "expected_nip": "7411906987",
    },
    {
        "name": "Medicover",
        "city": "Warszawa",
        "email": "kontakt@medicover.pl",  # DOMENA!
        "expected_nip": "5262057270",
    },
    {
        "name": "Centrum Medyczne PragaMed",
        "city": "Warszawa",
        "email": None,  # Brak domeny - test Brave Search fallback
        "expected_nip": "5223194230",
    },
]


async def test_single(finder: NIPFinderV3, test_case: dict) -> dict:
    """Test pojedynczy przypadek."""
    name = test_case["name"]
    city = test_case.get("city")
    email = test_case.get("email")
    expected = test_case.get("expected_nip")

    print(f"\n{'='*60}")
    print(f"TEST: {name} ({city})")
    if email:
        print(f"Email: {email}")
    print(f"{'='*60}")

    result = await finder.find_nip(name, city, email)

    # Podsumowanie
    print(f"\n[RESULT]")
    print(f"  Found: {result.found}")
    print(f"  NIP: {result.nip}")
    print(f"  NIP formatted: {result.nip_formatted}")
    print(f"  Strategy: {result.strategy_used}")
    print(f"  Confidence: {result.confidence:.2f}")
    print(f"  Time: {result.processing_time_ms}ms")
    print(f"  Cost: ${result.cost_usd:.4f}")
    print(f"  From cache: {result.from_cache}")

    if result.validation:
        print(f"\n[VALIDATION]")
        print(f"  Validated: {result.validation.validated}")
        print(f"  Checksum: {result.validation.checksum_valid}")
        print(f"  Domain: {result.validation.domain_valid}")
        if result.validation.errors:
            print(f"  Errors: {result.validation.errors}")

    if result.warnings:
        print(f"\n[WARNINGS]")
        for warning in result.warnings:
            print(f"  - {warning}")

    if expected:
        match = result.nip == expected
        print(f"\n[EXPECTED]")
        print(f"  Expected NIP: {expected}")
        print(f"  Match: {'OK' if match else 'MISMATCH'}")

    return {
        "name": name,
        "city": city,
        "found": result.found,
        "nip": result.nip,
        "strategy": str(result.strategy_used) if result.strategy_used else None,
        "confidence": result.confidence,
        "time_ms": result.processing_time_ms,
        "cost_usd": result.cost_usd,
        "match": result.nip == expected if expected else None,
    }


async def run_tests():
    """Uruchamia wszystkie testy."""
    print("\n" + "="*60)
    print("NIP FINDER V3 - MANUAL TEST")
    print("="*60)

    # Initialize finder
    finder = NIPFinderV3()

    results = []

    for test_case in TEST_CASES:
        try:
            result = await test_single(finder, test_case)
            results.append(result)
        except Exception as e:
            print(f"\n[ERROR] {test_case['name']}: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "name": test_case["name"],
                "error": str(e),
            })

    # Close finder
    await finder.close()

    # Podsumowanie
    print("\n" + "="*60)
    print("PODSUMOWANIE")
    print("="*60)

    found = sum(1 for r in results if r.get("found"))
    total = len(results)

    print(f"\nZnaleziono: {found}/{total} ({100*found/total:.0f}%)")

    total_cost = sum(r.get("cost_usd", 0.0) for r in results)
    print(f"Całkowity koszt: ${total_cost:.4f}")

    matched = sum(1 for r in results if r.get("match") == True)
    total_with_expected = sum(1 for r in results if r.get("match") is not None)
    if total_with_expected > 0:
        print(f"Dopasowane (vs expected): {matched}/{total_with_expected} ({100*matched/total_with_expected:.0f}%)")

    print("\nWyniki:")
    for r in results:
        status = "[OK]" if r.get("found") else "[--]"
        nip = r.get("nip", "N/A")
        strategy = r.get("strategy", "N/A")
        match_status = ""
        if r.get("match") is True:
            match_status = " [MATCH]"
        elif r.get("match") is False:
            match_status = " [MISMATCH]"
        print(f"  {status} {r['name']}: NIP={nip} ({strategy}){match_status}")


if __name__ == "__main__":
    asyncio.run(run_tests())
