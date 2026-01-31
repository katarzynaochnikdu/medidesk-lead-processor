"""
Batch test Company Intelligence Tool na wielu placówkach.

Uruchom: python -m company_intel.test_batch
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
# Reduce noise from httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apify_client").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# Placówki do przetestowania
TEST_COMPANIES = [
    {
        "name": "Klinika OT.CO",
        "website": "https://klinikaotco.pl",
        "city": "Warszawa",
    },
    {
        "name": "Klinika Ambroziak",
        "website": "https://klinikaambroziak.pl",
        "city": "Warszawa",
    },
    {
        "name": "FabSkin",
        "website": "https://fabskin.pl",
        "city": None,
    },
    {
        "name": "Voltamed",
        "website": "https://voltamed.pl",
        "city": None,
    },
    {
        "name": "Perspecteeth",
        "website": "https://perspecteeth.pl",
        "city": "Warszawa",
    },
    {
        "name": "Aldent Wroclaw",
        "website": "https://aldent.wroclaw.pl",
        "city": "Wrocław",
    },
]


async def analyze_company(orchestrator: CompanyIntelOrchestrator, company: dict) -> dict:
    """Analizuje pojedynczą firmę."""
    logger.info("=" * 60)
    logger.info("ANALYZING: %s (%s)", company["name"], company["website"])
    logger.info("=" * 60)
    
    try:
        result = await orchestrator.analyze(
            company_name=company["name"],
            city=company.get("city"),
            website=company["website"],
            skip_social=False,
            skip_ai=False,
        )
        
        # Przygotuj podsumowanie
        summary = {
            "name": company["name"],
            "website": company["website"],
            "success": True,
            "activity_score": result.activity_score.total,
            "recommendation": result.activity_score.recommendation.value,
            "signals": result.activity_score.signals,
            "social_media": {
                "facebook": result.social_media.facebook,
                "instagram": result.social_media.instagram,
                "tiktok": result.social_media.tiktok,
                "linkedin": result.social_media.linkedin,
            },
            "social_profiles": [
                {
                    "platform": p.platform.value,
                    "followers": p.followers,
                    "verified": p.is_verified,
                }
                for p in result.social_profiles
            ],
            "categorization": {
                "specjalizacja": result.kategoryzacja_ai.specjalizacja,
                "platnik_uslug": result.kategoryzacja_ai.platnik_uslug,
                "wielospecjalistyczne": result.kategoryzacja_ai.wielospecjalistyczne,
                "typ_wlasnosci": result.kategoryzacja_ai.typ_wlasnosci,
                "confidence": result.kategoryzacja_ai.ai_confidence,
                "reasoning": result.kategoryzacja_ai.ai_reasoning,
            },
            "placowki_count": len(result.placowki),
            "google_best_rating": max(
                (p.google_rating for p in result.placowki if p.google_rating),
                default=None
            ),
            "google_total_reviews": sum(
                p.google_reviews_count or 0 for p in result.placowki
            ),
            "kontakty": [
                {"typ": k.typ, "wartosc": k.wartosc}
                for p in result.placowki[:1]  # Tylko z pierwszej placówki
                for k in p.kontakty[:5]
            ],
            "processing_time_ms": result.metadata.processing_time_ms,
            "cost_usd": result.metadata.cost_usd,
            "sources_used": result.metadata.sources_used,
            "warnings": result.metadata.warnings,
            "errors": result.metadata.errors,
        }
        
        # Zapisz pełny JSON
        output_path = Path(__file__).parent / f"results_{company['name'].lower().replace(' ', '_').replace('.', '')}.json"
        result.save_json(str(output_path))
        summary["json_path"] = str(output_path)
        
        return summary
        
    except Exception as e:
        logger.exception("Error analyzing %s: %s", company["name"], e)
        return {
            "name": company["name"],
            "website": company["website"],
            "success": False,
            "error": str(e),
        }


def print_summary(results: list[dict]):
    """Wyświetla podsumowanie wyników."""
    print("\n")
    print("=" * 80)
    print("PODSUMOWANIE WYNIKÓW ANALIZY")
    print("=" * 80)
    print()
    
    # Tabela wyników
    print(f"{'Firma':<25} {'Score':>6} {'Rekomendacja':<12} {'FB':>8} {'IG':>8} {'TikTok':>8} {'Google':>6} {'Czas':>8}")
    print("-" * 90)
    
    for r in results:
        if not r.get("success"):
            print(f"{r['name']:<25} {'ERROR':>6} {r.get('error', 'Unknown')[:50]}")
            continue
        
        # Followers
        fb = next((p["followers"] for p in r.get("social_profiles", []) if p["platform"] == "facebook"), None)
        ig = next((p["followers"] for p in r.get("social_profiles", []) if p["platform"] == "instagram"), None)
        tt = next((p["followers"] for p in r.get("social_profiles", []) if p["platform"] == "tiktok"), None)
        
        fb_str = f"{fb/1000:.1f}K" if fb and fb >= 1000 else str(fb or "-")
        ig_str = f"{ig/1000:.1f}K" if ig and ig >= 1000 else str(ig or "-")
        tt_str = f"{tt/1000:.1f}K" if tt and tt >= 1000 else str(tt or "-")
        
        rating = r.get("google_best_rating")
        rating_str = f"{rating:.1f}" if rating else "-"
        
        time_str = f"{r['processing_time_ms']/1000:.0f}s"
        
        print(f"{r['name']:<25} {r['activity_score']:>6} {r['recommendation']:<12} {fb_str:>8} {ig_str:>8} {tt_str:>8} {rating_str:>6} {time_str:>8}")
    
    print("-" * 90)
    print()
    
    # Szczegóły dla każdej firmy
    for r in results:
        if not r.get("success"):
            continue
        
        print(f"\n{'='*60}")
        print(f"SZCZEGÓŁY: {r['name']}")
        print(f"{'='*60}")
        print(f"Website: {r['website']}")
        print(f"Activity Score: {r['activity_score']}/100 - {r['recommendation']}")
        print(f"Signals: {', '.join(r.get('signals', []))}")
        print()
        
        print("Social Media:")
        for sm in r.get("social_profiles", []):
            print(f"  {sm['platform']}: {sm['followers']} followers")
        print()
        
        cat = r.get("categorization", {})
        print("Kategoryzacja AI:")
        print(f"  Specjalizacja: {cat.get('specjalizacja', [])}")
        print(f"  Platnik: {cat.get('platnik_uslug', [])}")
        print(f"  Wielospecjalistyczne: {cat.get('wielospecjalistyczne', [])}")
        print(f"  Typ wlasnosci: {cat.get('typ_wlasnosci')}")
        print(f"  Confidence: {cat.get('confidence', 0):.2f}")
        print(f"  Reasoning: {cat.get('reasoning', '-')}")
        print()
        
        print(f"Google Maps: {r.get('placowki_count', 0)} placówek, rating: {r.get('google_best_rating', '-')}, {r.get('google_total_reviews', 0)} recenzji")
        print()
        
        kontakty = r.get("kontakty", [])
        if kontakty:
            print("Kontakty:")
            for k in kontakty[:5]:
                print(f"  {k['typ']}: {k['wartosc']}")
        print()
        
        print(f"Sources: {', '.join(r.get('sources_used', []))}")
        print(f"Time: {r['processing_time_ms']}ms, Cost: ${r['cost_usd']:.4f}")
        if r.get("warnings"):
            print(f"Warnings: {r['warnings']}")
        print(f"JSON saved: {r.get('json_path', '-')}")


async def main():
    """Główna funkcja."""
    print("=" * 80)
    print("COMPANY INTELLIGENCE TOOL - BATCH TEST")
    print(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()
    
    settings = get_settings()
    print(f"Apify token: {'OK' if settings.has_apify_credentials else 'MISSING!'}")
    print(f"Vertex AI: {'OK' if settings.has_vertex_ai_credentials else 'MISSING!'}")
    print(f"Testowanie {len(TEST_COMPANIES)} placówek...")
    print()
    
    orchestrator = CompanyIntelOrchestrator()
    results = []
    
    for company in TEST_COMPANIES:
        result = await analyze_company(orchestrator, company)
        results.append(result)
        
        # Krótkie podsumowanie po każdej firmie
        if result.get("success"):
            print(f"\n>>> {company['name']}: Score {result['activity_score']}/100 ({result['recommendation']})")
        else:
            print(f"\n>>> {company['name']}: ERROR - {result.get('error', 'Unknown')}")
        print()
    
    await orchestrator.close()
    
    # Podsumowanie
    print_summary(results)
    
    # Zapisz zbiorcze wyniki
    summary_path = Path(__file__).parent / "batch_results_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nZbiorcze wyniki zapisane: {summary_path}")
    
    # Statystyki końcowe
    successful = [r for r in results if r.get("success")]
    print(f"\n{'='*60}")
    print(f"STATYSTYKI KOŃCOWE")
    print(f"{'='*60}")
    print(f"Przeanalizowano: {len(successful)}/{len(results)} firm")
    if successful:
        avg_score = sum(r["activity_score"] for r in successful) / len(successful)
        total_cost = sum(r["cost_usd"] for r in successful)
        total_time = sum(r["processing_time_ms"] for r in successful) / 1000
        
        hot = len([r for r in successful if r["recommendation"] == "HOT_LEAD"])
        lukewarm = len([r for r in successful if r["recommendation"] == "LUKEWARM"])
        cold = len([r for r in successful if r["recommendation"] == "COLD"])
        
        print(f"Średni score: {avg_score:.1f}/100")
        print(f"HOT_LEAD: {hot}, LUKEWARM: {lukewarm}, COLD: {cold}")
        print(f"Łączny koszt: ${total_cost:.4f}")
        print(f"Łączny czas: {total_time:.1f}s")
    print()


if __name__ == "__main__":
    asyncio.run(main())
