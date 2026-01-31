"""
Test batch dla pozostalych 6 firm (kontynuacja).

Uruchomienie:
    py -3 -m company_intel.test_remaining
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
    name: str
    city: str
    nip: str
    website: str


# Pozostale 6 firm
TEST_CASES = [
    TestCase("SPA ProBody", "Gdansk", "5842809779", "spaprobody.pl"),
    TestCase("Perspecteeth", "Warszawa", "5214104768", "perspecteeth.pl"),
    TestCase("Voltamed", "Warszawa", "5213691717", "voltamed.pl"),
    TestCase("Aldent", "Wroclaw", "8941864949", "aldent.wroclaw.pl"),
    TestCase("Fabskin", "Warszawa", "5223210470", "fabskin.pl"),
    TestCase("Klinika Ambroziak", "Warszawa", "1231243387", "klinikaambroziak.pl"),
]


async def test_scenario(orchestrator, tc: TestCase, scenario: str, raw_text: str) -> dict:
    """Test pojedynczego scenariusza."""
    try:
        result, trace = await orchestrator.analyze_chaotic(
            raw_text=raw_text,
            skip_zoho=True,
            skip_search=False,
            full_analysis=False,
        )
        
        found_website = trace.final_website
        if found_website:
            found_website = found_website.lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        
        return {
            "scenario": scenario,
            "input": raw_text,
            "expected_nip": tc.nip,
            "found_nip": trace.final_nip,
            "nip_match": trace.final_nip == tc.nip,
            "expected_website": tc.website,
            "found_website": found_website,
            "decision": trace.final_nip_decision.value if trace.final_nip_decision else "NONE",
            "duration_ms": trace.total_duration_ms,
            "cost_usd": trace.total_cost_usd,
        }
    except Exception as e:
        return {
            "scenario": scenario,
            "input": raw_text,
            "expected_nip": tc.nip,
            "error": str(e),
            "nip_match": False,
        }


async def run_tests():
    """Uruchamia testy."""
    from .orchestrator import CompanyIntelOrchestrator
    
    print("\n" + "=" * 80)
    print("TEST REMAINING 6 COMPANIES - 3 SCENARIOS EACH")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 80)
    
    orchestrator = CompanyIntelOrchestrator()
    
    all_results = {"WITH_NIP": [], "WITH_WEBSITE": [], "CHAOTIC": []}
    total_cost = 0.0
    total_time = 0
    
    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] {tc.name} ({tc.city})")
        print(f"  Expected: NIP={tc.nip}, Website={tc.website}")
        
        # WITH_NIP
        print(f"  [1/3] WITH_NIP...", end=" ", flush=True)
        r = await test_scenario(orchestrator, tc, "WITH_NIP", f"{tc.name} {tc.city} NIP: {tc.nip}")
        all_results["WITH_NIP"].append(r)
        status = "OK" if r.get("nip_match") else ("ERR" if r.get("error") else "FAIL")
        print(f"{status} -> {r.get('found_nip', 'N/A')}")
        total_cost += r.get("cost_usd", 0)
        total_time += r.get("duration_ms", 0)
        
        # WITH_WEBSITE
        print(f"  [2/3] WITH_WEBSITE...", end=" ", flush=True)
        r = await test_scenario(orchestrator, tc, "WITH_WEBSITE", f"{tc.name} {tc.city} www.{tc.website}")
        all_results["WITH_WEBSITE"].append(r)
        status = "OK" if r.get("nip_match") else ("ERR" if r.get("error") else "FAIL")
        print(f"{status} -> {r.get('found_nip', 'N/A')}")
        total_cost += r.get("cost_usd", 0)
        total_time += r.get("duration_ms", 0)
        
        # CHAOTIC
        print(f"  [3/3] CHAOTIC...", end=" ", flush=True)
        r = await test_scenario(orchestrator, tc, "CHAOTIC", f"{tc.name} {tc.city}")
        all_results["CHAOTIC"].append(r)
        status = "OK" if r.get("nip_match") else ("ERR" if r.get("error") else "FAIL")
        print(f"{status} -> {r.get('found_nip', 'N/A')}")
        total_cost += r.get("cost_usd", 0)
        total_time += r.get("duration_ms", 0)
    
    await orchestrator.close()
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    for scenario, results in all_results.items():
        ok = sum(1 for r in results if r.get("nip_match"))
        print(f"{scenario}: {ok}/{len(results)} OK ({100*ok/len(results):.0f}%)")
    
    print(f"\nTotal: {total_time/1000:.1f}s, ${total_cost:.4f}")
    
    # Table
    print("\n" + "-" * 80)
    print(f"{'Company':<20} {'WITH_NIP':<12} {'WITH_WWW':<12} {'CHAOTIC':<12}")
    print("-" * 80)
    for i, tc in enumerate(TEST_CASES):
        def st(r): 
            if r.get("error"): return "ERROR"
            if r.get("nip_match"): return "OK"
            if r.get("found_nip"): return f"WRONG"
            return "NOT_FOUND"
        print(f"{tc.name:<20} {st(all_results['WITH_NIP'][i]):<12} {st(all_results['WITH_WEBSITE'][i]):<12} {st(all_results['CHAOTIC'][i]):<12}")
    print("-" * 80)
    
    # Save
    output = f"company_intel/test_remaining_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved: {output}")
    
    return all_results


if __name__ == "__main__":
    asyncio.run(run_tests())
