"""Test batch na 10 firmach z comapnies_data_test.xlsx"""
import asyncio
import os
import pandas as pd
import sys

# Ustaw working directory na root projektu
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.stdout.reconfigure(encoding='utf-8')

from nip_finder.orchestrator import NIPFinder
from nip_finder.models import NIPRequest

async def main():
    # Wczytaj Excel
    df = pd.read_excel('comapnies_data_test.xlsx', header=None)
    
    # Pierwsze 10 firm (kolumna 0)
    companies = df.iloc[:10, 0].tolist()
    
    print("="*60)
    print("TEST NIP FINDER - 10 FIRM")
    print("="*60)
    
    for i, name in enumerate(companies, 1):
        print(f"{i:2}. {name}")
    
    print("="*60)
    print()
    
    # Przygotuj requesty
    requests = [NIPRequest(company_name=name) for name in companies]
    
    # NIP Finder
    finder = NIPFinder()
    
    results = []
    for i, req in enumerate(requests, 1):
        print(f"[{i}/10] Szukam: {req.company_name[:50]}...")
        result = await finder.find_nip_from_request(req)
        results.append(result)
        
        if result.found:
            print(f"        -> NIP: {result.nip_formatted} (confidence: {result.confidence:.0%})")
        else:
            print(f"        -> NIE ZNALEZIONO")
        print()
    
    await finder.close()
    
    # Podsumowanie
    found = sum(1 for r in results if r.found)
    
    print("="*60)
    print("PODSUMOWANIE")
    print("="*60)
    print(f"Znaleziono: {found}/10 ({found*10}%)")
    print()
    
    print("WYNIKI:")
    for r in results:
        status = f"NIP: {r.nip_formatted}" if r.found else "---"
        conf = f"{r.confidence:.0%}" if r.found else ""
        print(f"  {r.company_name[:45]:45} | {status:20} | {conf}")
    
    # Zapisz do CSV
    output_data = []
    for r in results:
        output_data.append({
            'company_name': r.company_name,
            'nip': r.nip or '',
            'nip_formatted': r.nip_formatted or '',
            'found': r.found,
            'confidence': r.confidence,
            'strategy': r.strategy_used or '',
            'source_url': r.source.url if r.source else '',
            'checksum_ok': r.validation.valid_checksum if r.validation else None,
            'vat_active': r.validation.vat_active if r.validation else None,
            'time_ms': r.processing_time_ms,
        })
    
    df_out = pd.DataFrame(output_data)
    df_out.to_excel('nip_test_results_10.xlsx', index=False)
    print()
    print("[SAVED] Wyniki zapisane do: nip_test_results_10.xlsx")

if __name__ == "__main__":
    asyncio.run(main())
