"""Quick test single NIP for registry data."""
import asyncio
import json
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from .orchestrator import CompanyIntelOrchestrator


async def test():
    orch = CompanyIntelOrchestrator()
    try:
        # Test AWODENT - NIP 1131088680
        result = await orch.analyze_by_nip('1131088680', skip_social=True)
        
        print('=== DANE REJESTROWE ===')
        print(f'NIP: {result.nip}')
        print(f'REGON: {result.regon}')
        print(f'KRS: {result.krs}')
        print(f'Nazwa pelna: {result.nazwa_pelna}')
        print(f'Nazwa zwyczajowa: {result.nazwa_zwyczajowa}')
        
        if result.adres_siedziby:
            a = result.adres_siedziby
            print(f'Adres siedziby: {a.ulica}, {a.kod} {a.miasto}')
        else:
            print('Adres siedziby: brak')
        
        print()
        print('=== PLACOWKI ===')
        for i, p in enumerate(result.placowki, 1):
            a = p.adres
            print(f'{i}. {a.miasto}, {a.ulica}')
            for k in p.kontakty:
                print(f'   {k.typ}: {k.wartosc}')
        
        # Zapisz JSON
        with open('results_test_nip.json', 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        print()
        print('Zapisano: results_test_nip.json')
        
    finally:
        await orch.close()


if __name__ == '__main__':
    asyncio.run(test())
