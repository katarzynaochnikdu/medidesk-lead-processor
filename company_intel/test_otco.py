"""Quick test for OT.CO deduplication."""
import asyncio
import json
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from .orchestrator import CompanyIntelOrchestrator


async def test():
    orch = CompanyIntelOrchestrator()
    try:
        result = await orch.analyze(
            company_name='Klinika OT.CO',
            website='https://klinikaotco.pl',
            skip_social=True,
            skip_ai=True,
        )
        
        print('=== PLACÓWKI ===')
        for i, p in enumerate(result.placowki, 1):
            a = p.adres
            print(f'{i}. {a.miasto}, {a.ulica} ({a.kod})')
            print(f'   Rating: {p.google_rating}, Recenzje: {p.google_reviews_count}')
            print(f'   Place ID: {p.google_maps_place_id}')
            for k in p.kontakty[:2]:  # Pierwsze 2 kontakty
                print(f'   {k.typ}: {k.wartosc}')
        
        print()
        print(f'Łącznie placówek: {len(result.placowki)}')
        
        # Zapisz JSON
        with open('results_otco_dedup.json', 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        print('Zapisano: results_otco_dedup.json')
        
    finally:
        await orch.close()


if __name__ == '__main__':
    asyncio.run(test())
