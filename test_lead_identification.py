"""
Test end-to-end: Lead Identification System.

Testuje pełny flow:
1. Normalizacja danych (AI)
2. Szukanie NIP (NIPFinderV3) + zbieranie danych kontaktowych
3. Search w Zoho
4. Generowanie IdentificationResult
"""

import asyncio
import json
import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Wyłącz verbose logi z httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def test_nip_finder_with_scraping():
    """Test NIPFinderV3 z zbieraniem danych kontaktowych."""
    from nip_finder_v3.core.orchestrator import NIPFinderV3

    print("\n" + "=" * 60)
    print("TEST 1: NIPFinderV3 z zbieraniem danych kontaktowych")
    print("=" * 60)

    finder = NIPFinderV3()

    # Test case: firma z domeną z email
    test_cases = [
        {
            "company_name": "Hollywood Smile",
            "city": None,
            "email": "mariusz@dentysta.pl",
        },
        {
            "company_name": "Centrum Medyczne PragaMed",
            "city": "Warszawa",
            "email": None,
        },
        {
            "company_name": "Klinika Witaminowa",
            "city": None,
            "email": None,
        },
    ]

    for i, tc in enumerate(test_cases, 1):
        print(f"\n--- Test case {i}: {tc['company_name']} ---")

        result = await finder.find_nip(
            company_name=tc["company_name"],
            city=tc["city"],
            email=tc["email"],
        )

        print(f"  Found: {result.found}")
        if result.found:
            print(f"  NIP: {result.nip_formatted}")
            print(f"  Confidence: {result.confidence:.0%}")
            print(f"  Strategy: {result.strategy_used.value if result.strategy_used else 'N/A'}")

        if result.scraped_data:
            sd = result.scraped_data
            print(f"  Scraped data:")
            print(f"    - Domain: {sd.domain}")
            print(f"    - Emails: {sd.emails[:3] if sd.emails else []}")
            print(f"    - Phones: {sd.phones[:3] if sd.phones else []}")
            print(f"    - Social: {list(sd.social_links.keys()) if sd.social_links else []}")
        else:
            print(f"  Scraped data: None")

    await finder.close()
    print("\n✅ Test 1 completed")


async def test_data_normalizer_with_nip_finder():
    """Test DataNormalizerService z NIPFinderV3."""
    from src.services.data_normalizer import DataNormalizerService

    print("\n" + "=" * 60)
    print("TEST 2: DataNormalizerService z NIPFinderV3")
    print("=" * 60)

    service = DataNormalizerService(use_mocks=False)

    # Test lead
    raw_data = {
        "company": "Hollywood Smile",
        "email": "mariusz@dentysta.pl",
        "first_name": None,
        "last_name": None,
        "phone": None,
    }

    print(f"\nInput: {json.dumps(raw_data, indent=2)}")

    result = await service.process_lead(raw_data, skip_duplicates=True, skip_gus=True)

    print(f"\nOutput:")
    print(f"  Success: {result.success}")
    print(f"  Processing time: {result.processing_time_ms}ms")
    print(f"\n  Normalized:")
    print(f"    - Company: {result.normalized.company_name}")
    print(f"    - Email: {result.normalized.email}")
    print(f"    - NIP: {result.normalized.nip_formatted}")
    print(f"    - NIP valid: {result.normalized.nip_valid}")
    print(f"\n  Warnings: {result.warnings}")

    # Sprawdź czy scraped_data zostało zapisane
    if service._scraped_company_data:
        sd = service._scraped_company_data
        print(f"\n  Scraped company data:")
        print(f"    - Domain: {sd.domain}")
        print(f"    - Emails: {sd.emails[:3] if sd.emails else []}")
        print(f"    - Phones: {sd.phones[:3] if sd.phones else []}")

    await service.close()
    print("\n✅ Test 2 completed")


async def test_zoho_mapper():
    """Test mapowania do pól Zoho."""
    from src.models.lead_output import NormalizedData, GUSData, ScrapedContactData
    from src.utils.zoho_mapper import (
        build_contact_create_data,
        build_account_create_data,
    )

    print("\n" + "=" * 60)
    print("TEST 3: Zoho Mapper")
    print("=" * 60)

    # Dane testowe
    normalized = NormalizedData(
        first_name="Mariusz",
        last_name="Kowalski",
        email="mariusz@dentysta.pl",
        phone="+48123456789",
        phone_formatted="+48 123 456 789",
        company_name="Hollywood Smile",
        nip="1234567890",
        nip_formatted="123-456-78-90",
        city="Warszawa",
    )

    gus_data = GUSData(
        found=True,
        full_name="HOLLYWOOD SMILE SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
        regon="123456789",
        street="Marszałkowska",
        building_number="1",
        city="Warszawa",
        zip_code="00-001",
    )

    scraped_data = ScrapedContactData(
        domain="dentysta.pl",
        emails=["kontakt@dentysta.pl", "rejestracja@dentysta.pl"],
        phones=["+48221234567"],
        social_links={"facebook": "https://facebook.com/dentystapl"},
    )

    # Test Contact mapping
    contact_data = build_contact_create_data(
        data=normalized,
        account_id="zcrm_123456789",
        scraped_data=scraped_data,
    )
    print(f"\nContact create_data:")
    print(json.dumps(contact_data, indent=2, default=str))

    # Test Account mapping
    account_data = build_account_create_data(
        data=normalized,
        gus_data=gus_data,
        scraped_data=scraped_data,
    )
    print(f"\nAccount create_data:")
    print(json.dumps(account_data, indent=2, default=str))

    print("\n✅ Test 3 completed")


async def test_detect_new_fields():
    """Test wykrywania nowych pól."""
    from src.models.lead_output import NormalizedData, ScrapedContactData
    from src.services.zoho_search import detect_new_contact_fields, detect_new_account_fields

    print("\n" + "=" * 60)
    print("TEST 4: Detect new fields")
    print("=" * 60)

    # Symulowany rekord z Zoho (niepełny)
    existing_contact = {
        "id": "zcrm_123",
        "First_Name": "Mariusz",
        "Last_Name": "Kowalski",
        "Email": "mariusz@gmail.com",
        "Phone": None,
        "Mobile": None,
        "Secondary_Email": None,
    }

    # Nowe dane z leada
    incoming_data = NormalizedData(
        email="mariusz@dentysta.pl",  # Nowy email firmowy
        phone="+48123456789",
        phone_formatted="+48 123 456 789",
    )

    # Dane ze scrapingu
    scraped = ScrapedContactData(
        emails=["kontakt@dentysta.pl"],
        phones=["+48221234567"],
    )

    updates = detect_new_contact_fields(existing_contact, incoming_data, scraped)

    print(f"\nExisting record: {json.dumps(existing_contact, indent=2)}")
    print(f"\nIncoming data: email={incoming_data.email}, phone={incoming_data.phone}")
    print(f"\nScraped data: emails={scraped.emails}, phones={scraped.phones}")
    print(f"\nDetected updates ({len(updates)}):")
    for u in updates:
        print(f"  - {u.field_name}: {u.new_value} ({u.reason})")

    print("\n✅ Test 4 completed")


async def main():
    """Uruchom wszystkie testy."""
    print("=" * 60)
    print("LEAD IDENTIFICATION SYSTEM - END-TO-END TESTS")
    print("=" * 60)

    try:
        await test_nip_finder_with_scraping()
    except Exception as e:
        print(f"\n❌ Test 1 failed: {e}")

    try:
        await test_data_normalizer_with_nip_finder()
    except Exception as e:
        print(f"\n❌ Test 2 failed: {e}")

    try:
        await test_zoho_mapper()
    except Exception as e:
        print(f"\n❌ Test 3 failed: {e}")

    try:
        await test_detect_new_fields()
    except Exception as e:
        print(f"\n❌ Test 4 failed: {e}")

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
