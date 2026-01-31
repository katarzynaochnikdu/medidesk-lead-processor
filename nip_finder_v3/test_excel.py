"""
Test NIP Finder V3 na danych z Excel.
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

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
logger = logging.getLogger(__name__)


async def run_test(excel_path: str, num_records: int = 20, skip_cache: bool = False, offset: int = 0):
    """Test NIP Finder na danych z Excel."""
    
    # Load data
    df = pd.read_excel(excel_path, header=None)
    companies = df[0].tolist()[offset:offset + num_records]
    
    print(f"\n{'='*60}")
    print(f"NIP FINDER V3 - TEST NA {num_records} REKORDACH")
    print(f"{'='*60}")
    print(f"Plik: {excel_path}")
    print(f"Liczba firm do przetestowania: {len(companies)}")
    print(f"Skip cache: {skip_cache}")
    
    # Initialize finder
    finder = NIPFinderV3()
    
    results = []
    found_count = 0
    total_cost = 0.0
    start_time = time.time()
    
    for i, company_name in enumerate(companies):
        print(f"\n[{i+1}/{len(companies)}] {company_name}")
        print("-" * 50)
        
        try:
            result = await finder.find_nip(company_name, city=None, email=None, skip_cache=skip_cache)
            
            if result.found:
                found_count += 1
                print(f"  [OK] NIP: {result.nip_formatted}")
                print(f"       Strategia: {result.strategy_used}")
                print(f"       Confidence: {result.confidence:.2f}")
                if result.alternatives:
                    print(f"       Alternatywy ({len(result.alternatives)}):")
                    for alt in result.alternatives[:3]:  # Show max 3
                        print(f"         - {alt.nip_formatted} (conf: {alt.confidence:.2f})")
            else:
                print(f"  [--] Nie znaleziono")
            
            print(f"     Czas: {result.processing_time_ms}ms")
            print(f"     Koszt: ${result.cost_usd:.4f}")
            
            total_cost += result.cost_usd
            
            # Build alternatives JSON
            alternatives_data = []
            for alt in result.alternatives:
                alternatives_data.append({
                    "nip": alt.nip,
                    "nip_formatted": alt.nip_formatted,
                    "company_name_found": alt.company_name_found,
                    "confidence": alt.confidence,
                })
            
            results.append({
                "company": company_name,
                "found": result.found,
                "nip": result.nip,
                "nip_formatted": result.nip_formatted,
                "strategy": str(result.strategy_used) if result.strategy_used else None,
                "confidence": result.confidence,
                "alternatives_count": len(result.alternatives),
                "alternatives_json": str(alternatives_data) if alternatives_data else None,
                "time_ms": result.processing_time_ms,
                "cost_usd": result.cost_usd,
            })
            
        except Exception as e:
            print(f"  [ERR] BLAD: {e}")
            results.append({
                "company": company_name,
                "found": False,
                "error": str(e),
            })
    
    # Close finder
    await finder.close()
    
    total_time = time.time() - start_time
    
    # Summary
    print(f"\n{'='*60}")
    print("PODSUMOWANIE")
    print(f"{'='*60}")
    print(f"Znaleziono: {found_count}/{len(companies)} ({100*found_count/len(companies):.0f}%)")
    print(f"Całkowity czas: {total_time:.1f}s")
    print(f"Średni czas na firmę: {total_time/len(companies):.1f}s")
    print(f"Całkowity koszt: ${total_cost:.4f}")
    
    print(f"\nWyniki:")
    for r in results:
        status = "[OK]" if r.get("found") else "[--]"
        nip = r.get("nip_formatted") or "---"
        strategy = r.get("strategy", "---")
        if strategy and "." in strategy:
            strategy = strategy.split(".")[-1]
        print(f"  {status} {r['company'][:40]:<40} | {nip:<15} | {strategy}")
    
    # Save to CSV
    output_path = "nip_finder_v3/test_results.csv"
    pd.DataFrame(results).to_csv(output_path, index=False)
    print(f"\nWyniki zapisane do: {output_path}")
    
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="companies_data_test.xlsx", help="Excel file path")
    parser.add_argument("--num", type=int, default=20, help="Number of records to test")
    parser.add_argument("--offset", type=int, default=0, help="Offset (skip first N records)")
    parser.add_argument("--skip-cache", action="store_true", help="Skip cache for fresh results")
    args = parser.parse_args()
    
    asyncio.run(run_test(args.file, args.num, args.skip_cache, args.offset))
