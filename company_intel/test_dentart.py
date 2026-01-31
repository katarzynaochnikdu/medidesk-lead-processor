"""Quick test for dentart.pl"""
import asyncio
import json
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from .orchestrator import CompanyIntelOrchestrator


async def test():
    orch = CompanyIntelOrchestrator()
    try:
        result = await orch.analyze(
            company_name='DENTART',
            website='https://dentart.pl/',
        )
        
        print('=== DENTART.PL WYNIKI ===')
        print()
        
        print('Nazwa:', result.nazwa_zwyczajowa)
        
        print()
        print('KONTAKTY:')
        for p in result.placowki:
            miasto = p.adres.miasto if p.adres else '?'
            ulica = p.adres.ulica if p.adres else '?'
            print(f"  Placowka: {miasto}, {ulica}")
            for k in p.kontakty:
                print(f"    {k.typ}: {k.wartosc}")
        
        print()
        print('SOCIAL MEDIA:')
        sm = result.social_media
        if sm:
            for platform in ['facebook', 'instagram', 'linkedin']:
                val = getattr(sm, platform, None)
                if val:
                    print(f'  {platform}: {val}')
        
        print()
        print('GODZINY:')
        for p in result.placowki:
            if p.godziny_otwarcia:
                print(f"  {p.godziny_otwarcia}")
        
        # Zapisz pełny JSON
        with open('results_dentart.json', 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        print()
        print('Zapisano: results_dentart.json')
        
    finally:
        await orch.close()


if __name__ == '__main__':
    asyncio.run(test())
