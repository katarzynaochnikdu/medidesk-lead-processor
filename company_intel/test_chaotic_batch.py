"""
Test batch dla Chaotic Data Processing.

Testuje 10 przygotowanych przypadków z oczekiwanymi NIP i website.

Uruchomienie:
    py -3 -m company_intel.test_chaotic_batch
"""

import asyncio
import logging
import sys
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# Wyłącz szczegółowe logi dla testów batch
logging.getLogger("company_intel.chaotic_router").setLevel(logging.WARNING)
logging.getLogger("company_intel.candidate_scorer").setLevel(logging.WARNING)
logging.getLogger("company_intel.query_builder").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@dataclass
class TestCase:
    """Pojedynczy przypadek testowy."""
    input_text: str
    expected_nip: str
    expected_website: str


# Dane testowe z planu
TEST_CASES = [
    TestCase("Medyczna Gdynia Władysława IV", "5882422041", "medycznagdynia.pl"),
    TestCase("Centrum Medyczne Stanley Poznań", "7831865315", "centrummedycznestanley.pl"),
    TestCase("OT.CO Bartycka", "5213873364", "klinikaotco.pl"),
    TestCase("Awodent Gołębiowskiego Warszawa", "1131088680", "awodent.com"),
    TestCase("SPA ProBody Gdańsk Marina", "5842809779", "spaprobody.pl"),
    TestCase("Perspecteeth stomatologia", "5214104768", "perspecteeth.pl"),
    TestCase("Voltamed psychiatria Warszawa", "5213691717", "voltamed.pl"),
    TestCase("Aldent Wrocław", "8941864949", "aldent.wroclaw.pl"),
    TestCase("Fabskin Warszawa", "5223210470", "fabskin.pl"),
    TestCase("Ambroziak Warszawa", "1231243387", "klinikaambroziak.pl"),
]


async def run_batch_test(skip_zoho: bool = True, skip_search: bool = False):
    """
    Uruchamia testy batch.
    
    Args:
        skip_zoho: Pomiń Zoho lookup
        skip_search: Pomiń Google/Brave search
    """
    from .orchestrator import CompanyIntelOrchestrator
    from .models import CandidateDecision
    
    print("\n" + "=" * 80)
    print("CHAOTIC DATA PROCESSING - BATCH TEST")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Skip Zoho: {skip_zoho}, Skip Search: {skip_search}")
    print("=" * 80)
    
    orchestrator = CompanyIntelOrchestrator()
    
    results = []
    total_cost = 0.0
    total_time = 0
    
    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] Testing: '{tc.input_text}'")
        print(f"  Expected: NIP={tc.expected_nip}, Website={tc.expected_website}")
        
        try:
            result, trace = await orchestrator.analyze_chaotic(
                raw_text=tc.input_text,
                skip_zoho=skip_zoho,
                skip_search=skip_search,
                full_analysis=False,  # Tylko NIP/WWW, bez social
            )
            
            # Sprawdź wyniki
            nip_match = trace.final_nip == tc.expected_nip
            
            # Sprawdź website (może być None jeśli nie szukamy)
            found_website = trace.final_website
            if found_website:
                # Normalizuj domenę
                found_website = found_website.lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
            website_match = found_website == tc.expected_website if found_website else None
            
            decision = trace.final_nip_decision.value if trace.final_nip_decision else "NONE"
            
            # Status
            if nip_match:
                status = "OK"
            elif trace.final_nip:
                status = "WRONG_NIP"
            else:
                status = "NOT_FOUND"
            
            print(f"  Result:   NIP={trace.final_nip} ({decision}), Website={found_website}")
            print(f"  Status:   {status} | NIP: {'OK' if nip_match else 'FAIL'} | Website: {'OK' if website_match else 'FAIL' if website_match is False else 'N/A'}")
            print(f"  Time: {trace.total_duration_ms}ms, Cost: ${trace.total_cost_usd:.4f}")
            
            # Log steps
            print(f"  Steps:")
            for step in trace.steps:
                step_status = "SKIP" if step.skipped else "OK"
                reason = f" ({step.skip_reason})" if step.skipped else ""
                candidate_info = f" -> {step.best_candidate}" if step.best_candidate else ""
                print(f"    - {step.step_name}: {step_status}{reason}{candidate_info}")
            
            # Log candidates
            if trace.nip_candidates:
                print(f"  Candidates:")
                for c in trace.nip_candidates:
                    mark = ">>>" if c.nip == tc.expected_nip else "   "
                    print(f"    {mark} {c.nip}: {c.decision.value} (score={c.total_score})")
                    if c.gus_name:
                        print(f"          GUS: {c.gus_name[:50]}")
            
            results.append({
                "input": tc.input_text,
                "expected_nip": tc.expected_nip,
                "found_nip": trace.final_nip,
                "nip_match": nip_match,
                "decision": decision,
                "expected_website": tc.expected_website,
                "found_website": found_website,
                "website_match": website_match,
                "status": status,
                "duration_ms": trace.total_duration_ms,
                "cost_usd": trace.total_cost_usd,
            })
            
            total_cost += trace.total_cost_usd
            total_time += trace.total_duration_ms
            
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "input": tc.input_text,
                "expected_nip": tc.expected_nip,
                "found_nip": None,
                "nip_match": False,
                "decision": "ERROR",
                "status": "ERROR",
                "error": str(e),
            })
    
    await orchestrator.close()
    
    # Podsumowanie
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    nip_ok = sum(1 for r in results if r.get("nip_match"))
    nip_wrong = sum(1 for r in results if r.get("found_nip") and not r.get("nip_match"))
    nip_not_found = sum(1 for r in results if not r.get("found_nip") and r.get("status") != "ERROR")
    errors = sum(1 for r in results if r.get("status") == "ERROR")
    
    print(f"\nNIP Results:")
    print(f"  OK:        {nip_ok}/{len(TEST_CASES)} ({100*nip_ok/len(TEST_CASES):.1f}%)")
    print(f"  Wrong:     {nip_wrong}/{len(TEST_CASES)}")
    print(f"  Not Found: {nip_not_found}/{len(TEST_CASES)}")
    print(f"  Errors:    {errors}/{len(TEST_CASES)}")
    
    print(f"\nPerformance:")
    print(f"  Total Time: {total_time}ms ({total_time/len(TEST_CASES):.0f}ms avg)")
    print(f"  Total Cost: ${total_cost:.4f} (${total_cost/len(TEST_CASES):.4f} avg)")
    
    # Tabela wyników
    print("\n" + "-" * 80)
    print(f"{'Input':<40} {'Expected':<12} {'Found':<12} {'Status':<10}")
    print("-" * 80)
    for r in results:
        input_short = r["input"][:38] + ".." if len(r["input"]) > 40 else r["input"]
        expected = r["expected_nip"]
        found = r.get("found_nip") or "-"
        status = r["status"]
        print(f"{input_short:<40} {expected:<12} {found:<12} {status:<10}")
    print("-" * 80)
    
    return results


async def main():
    """Główna funkcja."""
    # Domyślnie: skip_zoho=True (test), skip_search=False (używaj NIPFinderV3)
    skip_search = "--no-search" in sys.argv
    use_zoho = "--zoho" in sys.argv
    
    results = await run_batch_test(
        skip_zoho=not use_zoho,
        skip_search=skip_search,
    )
    
    # Zapisz wyniki do JSON
    import json
    output_file = f"company_intel/chaotic_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
