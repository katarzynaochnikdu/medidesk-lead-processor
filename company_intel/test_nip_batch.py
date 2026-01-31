"""
Batch test Company Intelligence Tool - wyszukiwanie po NIP.

Uruchom: python -m company_intel.test_nip_batch
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Fix encoding for Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from company_intel import CompanyIntelOrchestrator
from company_intel.config import get_settings


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
# Reduce noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apify_client").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# NIP-y do przetestowania
TEST_NIPS = [
    "5542485321",
    "5882422041",
    "7831865315",
    "9571061749",
    "1131088680",
    "5842809779",
]


async def analyze_nip(orchestrator: CompanyIntelOrchestrator, nip: str) -> dict:
    """Analizuje pojedynczy NIP."""
    logger.info("=" * 60)
    logger.info("ANALYZING NIP: %s", nip)
    logger.info("=" * 60)
    
    try:
        result = await orchestrator.analyze_by_nip(
            nip=nip,
            skip_social=False,
            skip_ai=False,
        )
        
        # Przygotuj podsumowanie
        summary = {
            "nip": nip,
            "success": True,
            "company_name": result.nazwa_pelna,
            "common_name": result.nazwa_zwyczajowa,
            "website": result.social_media.website if result.social_media else None,
            "activity_score": result.activity_score.total if result.activity_score else 0,
            "recommendation": result.activity_score.recommendation.value if result.activity_score else None,
            "signals": result.activity_score.signals if result.activity_score else [],
            "categorization": {
                "specjalizacja": result.kategoryzacja_ai.specjalizacja if result.kategoryzacja_ai else [],
                "platnik_uslug": result.kategoryzacja_ai.platnik_uslug if result.kategoryzacja_ai else [],
                "confidence": result.kategoryzacja_ai.ai_confidence if result.kategoryzacja_ai else 0,
            },
            "placowki_count": len(result.placowki) if result.placowki else 0,
            "social_profiles": [
                {"platform": p.platform.value, "followers": p.followers}
                for p in (result.social_profiles or [])
            ],
            "processing_time_ms": result.metadata.processing_time_ms if result.metadata else 0,
            "sources_used": result.metadata.sources_used if result.metadata else [],
            "errors": result.metadata.errors if result.metadata else [],
        }
        
        # Zapisz pełny JSON
        nip_clean = nip.replace("-", "")
        output_path = Path(__file__).parent / f"results_nip_{nip_clean}.json"
        result.save_json(str(output_path))
        summary["json_path"] = str(output_path)
        
        return summary
        
    except Exception as e:
        logger.exception("Error analyzing NIP %s: %s", nip, e)
        return {
            "nip": nip,
            "success": False,
            "error": str(e),
        }


def print_summary(results: list[dict]):
    """Wyświetla podsumowanie wyników."""
    print("\n")
    print("=" * 100)
    print("PODSUMOWANIE WYNIKÓW ANALIZY PO NIP")
    print("=" * 100)
    print()
    
    # Tabela wyników
    print(f"{'NIP':<12} {'Firma':<35} {'Score':>6} {'Rekomendacja':<12} {'Źródła':<30}")
    print("-" * 100)
    
    for r in results:
        if not r.get("success"):
            print(f"{r['nip']:<12} {'ERROR: ' + r.get('error', 'Unknown')[:50]}")
            continue
        
        name = (r.get("company_name") or "N/A")[:33]
        score = r.get("activity_score", 0)
        rec = r.get("recommendation") or "-"
        sources = ", ".join(r.get("sources_used", [])[:4])
        
        print(f"{r['nip']:<12} {name:<35} {score:>6} {rec:<12} {sources:<30}")
    
    print("-" * 100)
    print()
    
    # Szczegóły dla każdej firmy
    for r in results:
        if not r.get("success"):
            continue
        
        print(f"\n{'='*60}")
        print(f"NIP: {r['nip']}")
        print(f"{'='*60}")
        print(f"Firma: {r.get('company_name', 'N/A')}")
        print(f"Nazwa zwyczajowa: {r.get('common_name', '-')}")
        print(f"Website: {r.get('website', 'Nie znaleziono')}")
        print(f"Activity Score: {r.get('activity_score', 0)}/100 - {r.get('recommendation', '-')}")
        print(f"Signals: {', '.join(r.get('signals', []))}")
        print()
        
        cat = r.get("categorization", {})
        print("Kategoryzacja AI:")
        print(f"  Specjalizacja: {cat.get('specjalizacja', [])}")
        print(f"  Platnik: {cat.get('platnik_uslug', [])}")
        print(f"  Confidence: {cat.get('confidence', 0):.2f}")
        print()
        
        print(f"Placówki: {r.get('placowki_count', 0)}")
        print(f"Social: {r.get('social_profiles', [])}")
        print(f"Sources: {', '.join(r.get('sources_used', []))}")
        print(f"Time: {r.get('processing_time_ms', 0)}ms")
        if r.get("errors"):
            print(f"Errors: {r['errors']}")
        print(f"JSON: {r.get('json_path', '-')}")


async def main():
    """Główna funkcja."""
    print("=" * 80)
    print("COMPANY INTELLIGENCE TOOL - NIP BATCH TEST")
    print(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()
    
    settings = get_settings()
    print(f"GUS API key: {'OK' if settings.gus_api_key else 'MISSING!'}")
    print(f"Apify token: {'OK' if settings.has_apify_credentials else 'MISSING!'}")
    print(f"Vertex AI: {'OK' if settings.has_vertex_ai_credentials else 'MISSING!'}")
    print(f"Testowanie {len(TEST_NIPS)} NIP-ów...")
    print()
    
    orchestrator = CompanyIntelOrchestrator()
    results = []
    
    for nip in TEST_NIPS:
        result = await analyze_nip(orchestrator, nip)
        results.append(result)
        
        # Krótkie podsumowanie
        if result.get("success"):
            name = result.get('company_name') or 'N/A'
            print(f"\n>>> NIP {nip}: {name[:40]} | Score: {result.get('activity_score', 0)}/100")
        else:
            print(f"\n>>> NIP {nip}: ERROR - {result.get('error', 'Unknown')}")
        print()
    
    await orchestrator.close()
    
    # Podsumowanie
    print_summary(results)
    
    # Zapisz zbiorcze wyniki
    summary_path = Path(__file__).parent / "nip_batch_results_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nZbiorcze wyniki zapisane: {summary_path}")
    
    # Statystyki
    successful = [r for r in results if r.get("success")]
    print(f"\n{'='*60}")
    print(f"STATYSTYKI KOŃCOWE")
    print(f"{'='*60}")
    print(f"Przeanalizowano: {len(successful)}/{len(results)} NIP-ów")
    if successful:
        avg_score = sum(r.get("activity_score", 0) for r in successful) / len(successful)
        print(f"Średni score: {avg_score:.1f}/100")
    print()


if __name__ == "__main__":
    asyncio.run(main())
