"""
Test batch dla wszystkich 3 scenariuszy wejsciowych:
1. Z NIP - walidacja + uzupelnienie danych
2. Z website - scraping NIP ze strony  
3. Chaotic (tylko slowa kluczowe)

Uruchomienie:
    py -3 -m company_intel.test_all_scenarios
"""

import asyncio
import logging
import json
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# Reduce noise
for logger_name in ["httpx", "httpcore", "company_intel.chaotic_router", 
                    "company_intel.candidate_scorer", "company_intel.query_builder",
                    "nip_finder_v3"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)


@dataclass
class TestCase:
    """Przypadek testowy."""
    name: str  # Nazwa firmy
    city: str  # Miasto
    nip: str  # Oczekiwany NIP
    website: str  # Oczekiwana strona


# Dane testowe - te same firmy dla wszystkich scenariuszy
TEST_CASES = [
    TestCase("Medyczna Gdynia", "Gdynia", "5882422041", "medycznagdynia.pl"),
    TestCase("Centrum Medyczne Stanley", "Poznan", "7831865315", "centrummedycznestanley.pl"),
    TestCase("Klinika OT.CO", "Warszawa", "5213873364", "klinikaotco.pl"),
    TestCase("Awodent", "Warszawa", "1131088680", "awodent.com"),
    TestCase("SPA ProBody", "Gdansk", "5842809779", "spaprobody.pl"),
    TestCase("Perspecteeth", "Warszawa", "5214104768", "perspecteeth.pl"),
    TestCase("Voltamed", "Warszawa", "5213691717", "voltamed.pl"),
    TestCase("Aldent", "Wroclaw", "8941864949", "aldent.wroclaw.pl"),
    TestCase("Fabskin", "Warszawa", "5223210470", "fabskin.pl"),
    TestCase("Klinika Ambroziak", "Warszawa", "1231243387", "klinikaambroziak.pl"),
]


async def test_scenario_with_nip(orchestrator, tc: TestCase) -> dict:
    """Scenariusz 1: Dane wejsciowe zawieraja NIP."""
    # Symuluj dane z NIP
    raw_text = f"{tc.name} {tc.city} NIP: {tc.nip}"
    
    result, trace = await orchestrator.analyze_chaotic(
        raw_text=raw_text,
        skip_zoho=True,
        skip_search=False,
        full_analysis=False,
    )
    
    return {
        "scenario": "WITH_NIP",
        "input": raw_text,
        "expected_nip": tc.nip,
        "found_nip": trace.final_nip,
        "nip_match": trace.final_nip == tc.nip,
        "expected_website": tc.website,
        "found_website": _normalize_domain(trace.final_website),
        "website_match": _normalize_domain(trace.final_website) == tc.website if trace.final_website else None,
        "decision": trace.final_nip_decision.value if trace.final_nip_decision else "NONE",
        "duration_ms": trace.total_duration_ms,
        "cost_usd": trace.total_cost_usd,
    }


async def test_scenario_with_website(orchestrator, tc: TestCase) -> dict:
    """Scenariusz 2: Dane wejsciowe zawieraja website."""
    # Symuluj dane z website
    raw_text = f"{tc.name} {tc.city} www.{tc.website}"
    
    result, trace = await orchestrator.analyze_chaotic(
        raw_text=raw_text,
        skip_zoho=True,
        skip_search=False,
        full_analysis=False,
    )
    
    return {
        "scenario": "WITH_WEBSITE",
        "input": raw_text,
        "expected_nip": tc.nip,
        "found_nip": trace.final_nip,
        "nip_match": trace.final_nip == tc.nip,
        "expected_website": tc.website,
        "found_website": _normalize_domain(trace.final_website),
        "website_match": _normalize_domain(trace.final_website) == tc.website if trace.final_website else None,
        "decision": trace.final_nip_decision.value if trace.final_nip_decision else "NONE",
        "duration_ms": trace.total_duration_ms,
        "cost_usd": trace.total_cost_usd,
    }


async def test_scenario_chaotic(orchestrator, tc: TestCase) -> dict:
    """Scenariusz 3: Tylko slowa kluczowe (chaotic)."""
    # Symuluj chaotic input
    raw_text = f"{tc.name} {tc.city}"
    
    result, trace = await orchestrator.analyze_chaotic(
        raw_text=raw_text,
        skip_zoho=True,
        skip_search=False,
        full_analysis=False,
    )
    
    return {
        "scenario": "CHAOTIC",
        "input": raw_text,
        "expected_nip": tc.nip,
        "found_nip": trace.final_nip,
        "nip_match": trace.final_nip == tc.nip,
        "expected_website": tc.website,
        "found_website": _normalize_domain(trace.final_website),
        "website_match": _normalize_domain(trace.final_website) == tc.website if trace.final_website else None,
        "decision": trace.final_nip_decision.value if trace.final_nip_decision else "NONE",
        "duration_ms": trace.total_duration_ms,
        "cost_usd": trace.total_cost_usd,
    }


def _normalize_domain(url: Optional[str]) -> Optional[str]:
    """Normalizuje URL do domeny."""
    if not url:
        return None
    return url.lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


async def run_all_tests():
    """Uruchamia wszystkie testy."""
    from .orchestrator import CompanyIntelOrchestrator
    
    print("\n" + "=" * 80)
    print("TEST ALL SCENARIOS - NIP / WEBSITE / CHAOTIC")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Test cases: {len(TEST_CASES)}")
    print("=" * 80)
    
    orchestrator = CompanyIntelOrchestrator()
    
    all_results = {
        "WITH_NIP": [],
        "WITH_WEBSITE": [],
        "CHAOTIC": [],
    }
    
    total_cost = 0.0
    total_time = 0
    
    # Test each case in all 3 scenarios
    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] Testing: '{tc.name}' ({tc.city})")
        print(f"  Expected: NIP={tc.nip}, Website={tc.website}")
        
        # Scenario 1: WITH_NIP
        try:
            print(f"  [1/3] WITH_NIP...")
            result = await test_scenario_with_nip(orchestrator, tc)
            all_results["WITH_NIP"].append(result)
            status = "OK" if result["nip_match"] else "FAIL"
            print(f"        NIP: {status} | Found: {result['found_nip']} | {result['duration_ms']}ms")
            total_cost += result["cost_usd"]
            total_time += result["duration_ms"]
        except Exception as e:
            print(f"        ERROR: {e}")
            all_results["WITH_NIP"].append({"scenario": "WITH_NIP", "error": str(e), "nip_match": False})
        
        # Scenario 2: WITH_WEBSITE
        try:
            print(f"  [2/3] WITH_WEBSITE...")
            result = await test_scenario_with_website(orchestrator, tc)
            all_results["WITH_WEBSITE"].append(result)
            status = "OK" if result["nip_match"] else "FAIL"
            print(f"        NIP: {status} | Found: {result['found_nip']} | {result['duration_ms']}ms")
            total_cost += result["cost_usd"]
            total_time += result["duration_ms"]
        except Exception as e:
            print(f"        ERROR: {e}")
            all_results["WITH_WEBSITE"].append({"scenario": "WITH_WEBSITE", "error": str(e), "nip_match": False})
        
        # Scenario 3: CHAOTIC
        try:
            print(f"  [3/3] CHAOTIC...")
            result = await test_scenario_chaotic(orchestrator, tc)
            all_results["CHAOTIC"].append(result)
            status = "OK" if result["nip_match"] else "FAIL"
            print(f"        NIP: {status} | Found: {result['found_nip']} | {result['duration_ms']}ms")
            total_cost += result["cost_usd"]
            total_time += result["duration_ms"]
        except Exception as e:
            print(f"        ERROR: {e}")
            all_results["CHAOTIC"].append({"scenario": "CHAOTIC", "error": str(e), "nip_match": False})
    
    await orchestrator.close()
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY BY SCENARIO")
    print("=" * 80)
    
    for scenario, results in all_results.items():
        nip_ok = sum(1 for r in results if r.get("nip_match"))
        nip_wrong = sum(1 for r in results if r.get("found_nip") and not r.get("nip_match"))
        nip_not_found = sum(1 for r in results if not r.get("found_nip") and not r.get("error"))
        errors = sum(1 for r in results if r.get("error"))
        
        print(f"\n{scenario}:")
        print(f"  OK:        {nip_ok}/{len(TEST_CASES)} ({100*nip_ok/len(TEST_CASES):.0f}%)")
        print(f"  Wrong:     {nip_wrong}/{len(TEST_CASES)}")
        print(f"  Not Found: {nip_not_found}/{len(TEST_CASES)}")
        print(f"  Errors:    {errors}/{len(TEST_CASES)}")
    
    print(f"\nTotal Performance:")
    print(f"  Total Time: {total_time/1000:.1f}s ({total_time/1000/30:.1f}s avg per test)")
    print(f"  Total Cost: ${total_cost:.4f} (${total_cost/30:.4f} avg)")
    
    # Detailed table
    print("\n" + "-" * 100)
    print(f"{'Company':<25} {'WITH_NIP':<15} {'WITH_WEBSITE':<15} {'CHAOTIC':<15}")
    print("-" * 100)
    
    for i, tc in enumerate(TEST_CASES):
        nip_result = all_results["WITH_NIP"][i]
        web_result = all_results["WITH_WEBSITE"][i]
        chaotic_result = all_results["CHAOTIC"][i]
        
        def status(r):
            if r.get("error"):
                return "ERROR"
            if r.get("nip_match"):
                return "OK"
            if r.get("found_nip"):
                return "WRONG"
            return "NOT_FOUND"
        
        print(f"{tc.name:<25} {status(nip_result):<15} {status(web_result):<15} {status(chaotic_result):<15}")
    
    print("-" * 100)
    
    # Save results
    output_file = f"company_intel/test_all_scenarios_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to: {output_file}")
    
    return all_results


if __name__ == "__main__":
    asyncio.run(run_all_tests())
