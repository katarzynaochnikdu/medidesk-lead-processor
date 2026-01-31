"""Quick test for single chaotic case."""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

async def main():
    from .orchestrator import CompanyIntelOrchestrator
    
    orchestrator = CompanyIntelOrchestrator()
    
    test_input = "Awodent Gołębiowskiego Warszawa"
    expected_nip = "1131088680"
    
    print(f"\n{'='*60}")
    print(f"Testing: '{test_input}'")
    print(f"Expected NIP: {expected_nip}")
    print('='*60)
    
    result, trace = await orchestrator.analyze_chaotic(
        raw_text=test_input,
        skip_zoho=True,
        skip_search=False,
        full_analysis=False,
    )
    
    print(f"\n{'='*60}")
    print("RESULT:")
    print(f"  Found NIP: {trace.final_nip}")
    print(f"  Decision: {trace.final_nip_decision}")
    print(f"  Match: {'OK' if trace.final_nip == expected_nip else 'FAIL'}")
    print(f"  Time: {trace.total_duration_ms}ms")
    print(f"  Cost: ${trace.total_cost_usd:.4f}")
    print('='*60)
    
    if trace.nip_candidates:
        print("\nCandidates:")
        for c in trace.nip_candidates:
            mark = ">>>" if c.nip == expected_nip else "   "
            print(f"  {mark} {c.nip}: {c.decision.value} (score={c.total_score})")
    
    await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
