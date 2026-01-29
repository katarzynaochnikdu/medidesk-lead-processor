"""
Manualny test NIP Finder z przykładowymi danymi.

Uruchom: python -m nip_finder.tests.run_manual_test
"""

import asyncio
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)


async def test_single_companies():
    """Test pojedynczych firm."""
    from nip_finder.orchestrator import NIPFinder
    
    logger.info("="*80)
    logger.info("TEST 1: Pojedyncze wyszukiwania")
    logger.info("="*80)
    
    finder = NIPFinder(use_cache=False)  # Bez cache dla czystego testu
    
    test_cases = [
        ("Medidesk sp. z o.o.", "Wrocław", None),
        ("Kamsoft", "Katowice", None),
        ("VITA MEDICA", "Siedlce", None),
        ("Centrum medyczne kropka", "Warszawa", None),
        ("Luxmed", "Warszawa", None),
    ]
    
    results = []
    
    for company_name, city, email in test_cases:
        logger.info("\n" + "-"*80)
        logger.info(f"Szukam: {company_name} ({city})")
        logger.info("-"*80)
        
        result = await finder.find_nip(
            company_name=company_name,
            city=city,
            email=email,
        )
        
        results.append(result)
        
        # Wyświetl wynik
        if result.found:
            logger.info(f"✅ ZNALEZIONO: {result.nip_formatted or result.nip}")
            logger.info(f"   Confidence: {result.confidence:.2%}")
            logger.info(f"   Strategy: {result.strategy_used}")
            if result.validation:
                logger.info(f"   Validated: {'✅' if result.validation.validated else '❌'}")
                if result.validation.gus_name:
                    logger.info(f"   GUS: {result.validation.gus_name}")
        else:
            logger.info(f"❌ NIE ZNALEZIONO")
            if result.errors:
                for error in result.errors:
                    logger.info(f"   Error: {error}")
        
        logger.info(f"   Time: {result.processing_time_ms}ms")
    
    await finder.close()
    
    # Podsumowanie
    logger.info("\n" + "="*80)
    logger.info("PODSUMOWANIE TEST 1")
    logger.info("="*80)
    successful = sum(1 for r in results if r.found)
    logger.info(f"Znaleziono: {successful}/{len(results)} ({successful/len(results)*100:.1f}%)")
    
    return results


async def test_batch_from_csv():
    """Test batch processing z CSV."""
    from nip_finder.orchestrator import NIPFinder
    from nip_finder.models import NIPRequest
    from nip_finder.output_handler import OutputHandler
    import pandas as pd
    
    logger.info("\n" + "="*80)
    logger.info("TEST 2: Batch processing z CSV")
    logger.info("="*80)
    
    # Sprawdź czy plik istnieje
    csv_path = Path(__file__).parent / "test_sample_data.csv"
    if not csv_path.exists():
        logger.error(f"Brak pliku: {csv_path}")
        return []
    
    # Wczytaj CSV
    df = pd.read_csv(csv_path)
    logger.info(f"Wczytano {len(df)} firm z CSV")
    
    # Przygotuj requests
    requests = []
    for _, row in df.iterrows():
        req = NIPRequest(
            company_name=row["company_name"],
            city=row.get("city"),
            email=row.get("email"),
        )
        requests.append(req)
    
    # Batch processing
    finder = NIPFinder(use_cache=False)
    
    logger.info(f"\n🚀 Start batch processing ({len(requests)} firm)...")
    
    results = await finder.batch_find_nip(requests, max_concurrent=3)
    
    await finder.close()
    
    # Statystyki
    successful = sum(1 for r in results if r.found)
    logger.info("\n" + "-"*80)
    logger.info(f"✅ Zakończono: {successful}/{len(results)} znalezionych")
    logger.info("-"*80)
    
    # Zapisz wyniki
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    
    csv_output = output_dir / "test_results.csv"
    json_output = output_dir / "test_results.json"
    report_output = output_dir / "test_report.md"
    
    OutputHandler.generate_csv(results, str(csv_output))
    OutputHandler.generate_json(results, str(json_output))
    OutputHandler.generate_detailed_report(results, str(report_output))
    
    logger.info(f"\n💾 Wyniki zapisane:")
    logger.info(f"   CSV: {csv_output}")
    logger.info(f"   JSON: {json_output}")
    logger.info(f"   Report: {report_output}")
    
    return results


async def main():
    """Główna funkcja testowa."""
    logger.info("🚀 NIP Finder - Manual Test")
    logger.info("="*80)
    
    # Test 1: Pojedyncze wyszukiwania
    results1 = await test_single_companies()
    
    # Test 2: Batch processing
    results2 = await test_batch_from_csv()
    
    # Finalne podsumowanie
    logger.info("\n" + "="*80)
    logger.info("FINALNE PODSUMOWANIE")
    logger.info("="*80)
    
    all_results = results1 + results2
    total = len(all_results)
    successful = sum(1 for r in all_results if r.found)
    
    logger.info(f"Total tests: {total}")
    logger.info(f"Successful: {successful} ({successful/total*100:.1f}%)")
    logger.info(f"Failed: {total-successful} ({(total-successful)/total*100:.1f}%)")
    
    if successful > 0:
        avg_confidence = sum(r.confidence for r in all_results if r.found) / successful
        logger.info(f"Avg confidence: {avg_confidence:.2%}")
    
    logger.info("\n✅ Test zakończony!")


if __name__ == "__main__":
    asyncio.run(main())
