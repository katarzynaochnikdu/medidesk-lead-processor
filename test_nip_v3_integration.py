"""Test integracji NIPFinderV3 z company_intel."""
import asyncio
import logging
import os

# Załaduj zmienne środowiskowe (.env) - WYMAGANE dla GOOGLE_APPLICATION_CREDENTIALS
from dotenv import load_dotenv
load_dotenv()

# Ustaw logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

async def test_nip_finder_v3_direct():
    """Test NIPFinderV3 bezpośrednio."""
    from nip_finder_v3 import NIPFinderV3
    
    print("\n" + "="*60)
    print("TEST 1: NIPFinderV3 bezpośrednio")
    print("="*60)
    
    finder = NIPFinderV3()
    
    test_cases = [
        ("ProBody Clinic", "Poznań"),
        ("Aldent Wrocław", "Wrocław"),
        ("Klinika Ambroziak", "Warszawa"),
    ]
    
    for company_name, city in test_cases:
        print(f"\n--- Szukam: {company_name} ({city}) ---")
        result = await finder.find_nip(company_name=company_name, city=city)
        
        print(f"  Found: {result.found}")
        if result.found:
            print(f"  NIP: {result.nip}")
            print(f"  Confidence: {result.confidence:.2f}")
            print(f"  Strategy: {result.strategy_used}")
            if result.validation:
                print(f"  Domain validated: {result.validation.domain_valid}")
        else:
            print(f"  Warnings: {result.warnings}")
    
    await finder.close()


async def test_company_intel_integration():
    """Test integracji przez CompanyIntelOrchestrator."""
    from company_intel.orchestrator import CompanyIntelOrchestrator
    
    print("\n" + "="*60)
    print("TEST 2: Integracja z CompanyIntelOrchestrator")
    print("="*60)
    
    orchestrator = CompanyIntelOrchestrator()
    print(f"NIPFinderV3 available: {orchestrator.nip_finder_v3 is not None}")
    
    # Test: Website -> NIP (używa NIPFinderV3)
    print("\n--- ProBody Clinic (tylko website) ---")
    result = await orchestrator.analyze(
        website="https://probodyclinic.pl",
        skip_social=True,
        skip_reviews=True,
    )
    
    print(f"  NIP znaleziony: {result.nip or 'NIE'}")
    print(f"  Źródła: {result.metadata.sources_used}")
    
    await orchestrator.close()


async def main():
    await test_nip_finder_v3_direct()
    await test_company_intel_integration()


if __name__ == "__main__":
    asyncio.run(main())
