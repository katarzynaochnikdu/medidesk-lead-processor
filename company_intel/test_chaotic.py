"""
Test script dla Chaotic Data Processing.

Testuje:
1. AI parsing chaotycznego tekstu
2. Router i wybór metod
3. Scoring kandydatów
4. Pełną ścieżkę analyze_chaotic

Uruchomienie:
    python -m company_intel.test_chaotic
"""

import asyncio
import json
import logging
import sys
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# Dane testowe - z planu (NIP, Website, Chaotyczne dane)
TEST_CASES = [
    # Format: (nazwa, chaotic_text, expected_nip, expected_website)
    
    # Przypadki z NIP w tekście
    ("Aldent Wroclaw", "Aldent Wrocław 8941864949", "8941864949", None),
    ("Fabskin", "5223210470 Fabskin Warszawa", "5223210470", None),
    
    # Przypadki z website
    ("Klinika Ambroziak", "klinikaambroziak.pl", "1231243387", "klinikaambroziak.pl"),
    
    # Przypadki nazwa + miasto (bez NIP)
    ("ProBody", "ProBody Gdynia", "5842809779", None),
    ("Voltamed", "Voltamed Warszawa", "5213691717", None),
    ("Perspecteeth", "Perspecteeth Warszawa", "5214104768", None),
    
    # Przypadki z branżą
    ("3CityMed", "Medyczna Gdynia stomatolog", None, None),  # Trudny przypadek
]


async def test_ai_parsing():
    """Test parsowania chaotycznego tekstu przez AI."""
    print("\n" + "=" * 60)
    print("TEST: AI Parsing")
    print("=" * 60)
    
    from src.services.vertex_ai import VertexAIServiceMock
    
    mock = VertexAIServiceMock()
    
    test_inputs = [
        "Aldent Wrocław 8941864949",
        "klinikaambroziak.pl",
        "ProBody Gdynia",
        "5223210470 Fabskin Warszawa",
        "Medyczna Gdynia stomatolog",
    ]
    
    for text in test_inputs:
        result = await mock.parse_chaotic_lead(text)
        if result:
            print(f"\nInput: {text}")
            print(f"  NIP: {result.get('nip')}")
            print(f"  Website: {result.get('website')}")
            print(f"  Name: {result.get('name')}")
            print(f"  City: {result.get('city')}")
            print(f"  Keywords: {result.get('keywords')}")
            print(f"  Strongest: {result.get('strongest_signal')}")
        else:
            print(f"\nInput: {text} -> PARSE FAILED")


async def test_query_builder():
    """Test budowania zapytań."""
    print("\n" + "=" * 60)
    print("TEST: Query Builder")
    print("=" * 60)
    
    from .query_builder import QueryBuilder
    from .models import ChaoticLeadParsed, SignalStrength
    
    builder = QueryBuilder(max_queries=5)
    
    # Test 1: name + city
    parsed = ChaoticLeadParsed(
        raw_text="Aldent Wrocław",
        name="Aldent",
        city="Wrocław",
        strongest_signal=SignalStrength.S4_NAME,
    )
    
    queries = builder.build_nip_search_queries(parsed)
    print(f"\nInput: name='Aldent', city='Wrocław'")
    for q in queries:
        print(f"  [{q.priority}] {q.strategy}: {q.query}")
    
    # Test 2: name + city + street
    parsed = ChaoticLeadParsed(
        raw_text="Aldent Wrocław Arbuzowa",
        name="Aldent",
        city="Wrocław",
        street="ul. Arbuzowa 12",
        strongest_signal=SignalStrength.S3_LOCATION,
    )
    
    queries = builder.build_nip_search_queries(parsed)
    print(f"\nInput: name='Aldent', city='Wrocław', street='Arbuzowa 12'")
    for q in queries:
        print(f"  [{q.priority}] {q.strategy}: {q.query}")
    
    # Test 3: with GUS data
    parsed = ChaoticLeadParsed(
        raw_text="ProBody",
        name="ProBody",
        short_name="ProBody",
        strongest_signal=SignalStrength.S4_NAME,
    )
    
    queries = builder.build_nip_search_queries(
        parsed,
        gus_name="SPA PRO BODY SP. Z O.O.",
        gus_city="Gdynia",
    )
    print(f"\nInput: name='ProBody' + GUS='SPA PRO BODY', city_gus='Gdynia'")
    for q in queries:
        print(f"  [{q.priority}] {q.strategy}: {q.query}")


async def test_candidate_scoring():
    """Test scoringu kandydatów."""
    print("\n" + "=" * 60)
    print("TEST: Candidate Scoring")
    print("=" * 60)
    
    from .candidate_scorer import CandidateScorer, validate_nip_checksum
    
    scorer = CandidateScorer()
    
    # Test 1: Valid NIP + GUS hit + name match
    print("\nTest 1: Valid NIP + GUS + name match")
    candidate = scorer.score_and_decide(
        nip="8941864949",
        gus_found=True,
        gus_name="ALDENT SP. Z O.O.",
        gus_city="Wrocław",
        input_name="Aldent",
    )
    print(f"  NIP: {candidate.nip}")
    print(f"  Score: id={candidate.score_id}, match={candidate.score_match}, source={candidate.score_source}, total={candidate.total_score}")
    print(f"  Decision: {candidate.decision.value} - {candidate.decision_reason}")
    
    # Test 2: Valid NIP + GUS hit + name MISMATCH
    print("\nTest 2: Valid NIP + GUS + name MISMATCH")
    candidate = scorer.score_and_decide(
        nip="5842809779",
        gus_found=True,
        gus_name="SPA PRO BODY SP. Z O.O.",
        gus_city="Gdynia",
        input_name="Medyczna Gdynia",  # Nie pasuje!
    )
    print(f"  NIP: {candidate.nip}")
    print(f"  Score: id={candidate.score_id}, match={candidate.score_match}, source={candidate.score_source}, total={candidate.total_score}")
    print(f"  Decision: {candidate.decision.value} - {candidate.decision_reason}")
    
    # Test 3: Invalid checksum
    print("\nTest 3: Invalid NIP checksum")
    candidate = scorer.score_and_decide(
        nip="1234567890",  # Nieprawidłowy checksum
    )
    print(f"  NIP: {candidate.nip}")
    print(f"  Decision: {candidate.decision.value} - {candidate.decision_reason}")
    
    # Test 4: NIP on domain + Zoho hit
    print("\nTest 4: NIP on domain + Zoho")
    candidate = scorer.score_and_decide(
        nip="8941864949",
        gus_found=True,
        gus_name="ALDENT SP. Z O.O.",
        nip_on_domain=True,
        domain="aldent.pl",
        zoho_found=True,
        zoho_name="Aldent Wrocław",
    )
    print(f"  NIP: {candidate.nip}")
    print(f"  Score: id={candidate.score_id}, match={candidate.score_match}, source={candidate.score_source}, total={candidate.total_score}")
    print(f"  Decision: {candidate.decision.value} - {candidate.decision_reason}")


async def test_full_flow_mock():
    """Test pełnego flow z mockami (bez zewnętrznych API)."""
    print("\n" + "=" * 60)
    print("TEST: Full Flow (Mock)")
    print("=" * 60)
    
    from .chaotic_router import ChaoticDataRouter
    from .config import get_settings
    
    settings = get_settings()
    
    # Router bez zewnętrznych serwisów
    router = ChaoticDataRouter(
        settings=settings,
        nip_lookup=None,  # Bez GUS
        zoho_lookup=None,  # Bez Zoho
        nip_finder_v3=None,  # Bez NIPFinderV3
        vertex_ai_service=None,  # Użyje mocka
    )
    
    test_inputs = [
        "Aldent Wrocław 8941864949",
        "5223210470 Fabskin",
    ]
    
    for text in test_inputs:
        print(f"\n--- Processing: '{text}' ---")
        trace = await router.process(
            raw_text=text,
            skip_zoho=True,
            skip_search=True,
        )
        
        print(f"  Final NIP: {trace.final_nip}")
        print(f"  Final Decision: {trace.final_nip_decision.value if trace.final_nip_decision else '?'}")
        print(f"  Steps: {len(trace.steps)}")
        for step in trace.steps:
            status = "SKIP" if step.skipped else "OK"
            print(f"    - {step.step_name}: {status} ({step.duration_ms}ms)")
        print(f"  Candidates: {len(trace.nip_candidates)}")
        for c in trace.nip_candidates:
            print(f"    - {c.nip}: {c.decision.value} (score={c.total_score})")


async def test_full_flow_real():
    """Test pełnego flow z prawdziwymi serwisami."""
    print("\n" + "=" * 60)
    print("TEST: Full Flow (Real APIs)")
    print("=" * 60)
    
    from .orchestrator import CompanyIntelOrchestrator
    
    orchestrator = CompanyIntelOrchestrator()
    
    # Jeden prosty test - NIP w tekście
    test_input = "Aldent Wrocław 8941864949"
    
    print(f"\n--- Processing: '{test_input}' ---")
    result, trace = await orchestrator.analyze_chaotic(
        raw_text=test_input,
        skip_zoho=True,  # Pomiń Zoho (test)
        skip_search=True,  # Pomiń search (test)
        full_analysis=False,  # Tylko NIP/WWW, bez social
    )
    
    print(f"\n  Final NIP: {trace.final_nip}")
    print(f"  Final Decision: {trace.final_nip_decision.value if trace.final_nip_decision else '?'}")
    print(f"  Final Website: {trace.final_website}")
    print(f"  Duration: {trace.total_duration_ms}ms")
    print(f"  Cost: ${trace.total_cost_usd:.4f}")
    
    if result:
        print(f"\n  CompanyIntel:")
        print(f"    NIP: {result.nip}")
        print(f"    Nazwa: {result.nazwa_pelna}")
        if result.adres_siedziby:
            print(f"    Miasto: {result.adres_siedziby.miasto}")
    
    print(f"\n  Steps:")
    for step in trace.steps:
        status = "SKIP" if step.skipped else "OK"
        reason = f" ({step.skip_reason})" if step.skipped else ""
        print(f"    - {step.step_name}: {status}{reason} ({step.duration_ms}ms)")
    
    print(f"\n  Candidates:")
    for c in trace.nip_candidates:
        print(f"    - {c.nip}: {c.decision.value} (score={c.total_score})")
        if c.gus_name:
            print(f"      GUS: {c.gus_name[:40]}")
    
    await orchestrator.close()


async def main():
    """Główna funkcja testowa."""
    print("\n" + "=" * 60)
    print("CHAOTIC DATA PROCESSING - TEST SUITE")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 60)
    
    # Test 1: AI Parsing (mock)
    await test_ai_parsing()
    
    # Test 2: Query Builder
    await test_query_builder()
    
    # Test 3: Candidate Scoring
    await test_candidate_scoring()
    
    # Test 4: Full flow (mock)
    await test_full_flow_mock()
    
    # Test 5: Full flow (real) - tylko jeśli jawnie włączony
    if "--real" in sys.argv:
        await test_full_flow_real()
    else:
        print("\n[INFO] Skipping real API tests. Use --real flag to run them.")
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
