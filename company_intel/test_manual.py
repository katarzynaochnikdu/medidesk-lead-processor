"""
Manualny test Company Intelligence Tool.

Uruchom: python -m company_intel.test_manual
"""

import asyncio
import logging
import json
import sys
from pathlib import Path

# Dodaj parent do path
sys.path.insert(0, str(Path(__file__).parent.parent))

from company_intel import CompanyIntelOrchestrator
from company_intel.config import get_settings


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-35s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)


async def test_single_company():
    """Testuje analizę pojedynczej firmy."""
    print("\n" + "="*60)
    print("TEST: Company Intelligence Tool")
    print("="*60 + "\n")
    
    settings = get_settings()
    print(f"Apify token: {'OK' if settings.has_apify_credentials else 'MISSING'}")
    print(f"Vertex AI: {'OK' if settings.has_vertex_ai_credentials else 'MISSING'}")
    print()
    
    orchestrator = CompanyIntelOrchestrator()
    
    # Test 1: Firma z podaną stroną WWW
    print("-" * 40)
    print("Test 1: Analiza firmy z URL strony")
    print("-" * 40)
    
    result = await orchestrator.analyze(
        company_name="VITA MEDICA",
        city="Siedlce",
        website="https://vitamedica.pl",
        skip_social=False,  # Scrapuj social jeśli znajdzie linki
        skip_ai=False,      # Kategoryzacja AI
    )
    
    # Wyświetl wynik
    print("\n--- WYNIK ---")
    print(f"Nazwa: {result.nazwa_pelna}")
    print(f"Nazwa zwyczajowa: {result.nazwa_zwyczajowa}")
    print(f"NIP: {result.nip}")
    print()
    
    print("Social Media:")
    print(f"  Website: {result.social_media.website}")
    print(f"  Facebook: {result.social_media.facebook}")
    print(f"  Instagram: {result.social_media.instagram}")
    print(f"  LinkedIn: {result.social_media.linkedin}")
    print(f"  TikTok: {result.social_media.tiktok}")
    print()
    
    print(f"Placówki: {len(result.placowki)}")
    for i, p in enumerate(result.placowki[:3]):
        print(f"  [{i+1}] {p.adres} | Rating: {p.google_rating} | Reviews: {p.google_reviews_count}")
    print()
    
    print("Activity Score:")
    print(f"  Total: {result.activity_score.total}/100")
    print(f"  Recommendation: {result.activity_score.recommendation.value}")
    print(f"  Signals: {', '.join(result.activity_score.signals[:5])}")
    print()
    
    print("Kategoryzacja AI:")
    print(f"  Specjalizacja: {result.kategoryzacja_ai.specjalizacja}")
    print(f"  Płatnik: {result.kategoryzacja_ai.platnik_uslug}")
    print(f"  Confidence: {result.kategoryzacja_ai.ai_confidence:.2f}")
    print()
    
    print("Metadata:")
    print(f"  Sources: {', '.join(result.metadata.sources_used)}")
    print(f"  Time: {result.metadata.processing_time_ms}ms")
    print(f"  Cost: ${result.metadata.cost_usd:.4f}")
    if result.metadata.warnings:
        print(f"  Warnings: {result.metadata.warnings}")
    if result.metadata.errors:
        print(f"  Errors: {result.metadata.errors}")
    print()
    
    # Zapisz JSON
    output_path = Path(__file__).parent / "test_output.json"
    result.save_json(str(output_path))
    print(f"JSON saved to: {output_path}")
    
    await orchestrator.close()
    
    return result


async def test_website_scraper_only():
    """Testuje tylko scraper WWW (bez Apify)."""
    print("\n" + "="*60)
    print("TEST: Website Scraper Only")
    print("="*60 + "\n")
    
    from company_intel.scrapers import WebsiteScraper
    
    scraper = WebsiteScraper()
    
    result = await scraper.execute(
        url="https://vitamedica.pl",
        max_pages=3,
        extract_text=True,
    )
    
    print(f"Success: {result.success}")
    print(f"Duration: {result.duration_ms}ms")
    
    if result.success:
        data = result.data
        print(f"\nTitle: {data.get('page_title')}")
        print(f"Pages scraped: {len(data.get('pages_scraped', []))}")
        
        social = data.get("social_links")
        if social:
            print(f"\nSocial links found:")
            print(f"  Facebook: {social.facebook}")
            print(f"  Instagram: {social.instagram}")
            print(f"  LinkedIn: {social.linkedin}")
            print(f"  TikTok: {social.tiktok}")
        
        kontakty = data.get("kontakty", [])
        print(f"\nKontakty: {len(kontakty)}")
        for k in kontakty[:5]:
            print(f"  {k.typ}: {k.wartosc}")
        
        print(f"\nPage text length: {len(data.get('page_text', ''))}")
    else:
        print(f"Error: {result.error}")
    
    await scraper.close()


async def main():
    """Główna funkcja testowa."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Company Intelligence Tool")
    parser.add_argument(
        "--mode",
        choices=["full", "website"],
        default="full",
        help="Tryb testu: full (pełna analiza) lub website (tylko scraper WWW)",
    )
    parser.add_argument(
        "--company",
        type=str,
        default="VITA MEDICA",
        help="Nazwa firmy do analizy",
    )
    parser.add_argument(
        "--city",
        type=str,
        default="Siedlce",
        help="Miasto",
    )
    parser.add_argument(
        "--website",
        type=str,
        default=None,
        help="URL strony WWW",
    )
    
    args = parser.parse_args()
    
    if args.mode == "website":
        await test_website_scraper_only()
    else:
        await test_single_company()


if __name__ == "__main__":
    asyncio.run(main())
