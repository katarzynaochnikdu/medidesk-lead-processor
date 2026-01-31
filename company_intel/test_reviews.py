"""Test analizy recenzji."""
import asyncio
import json
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from .orchestrator import CompanyIntelOrchestrator


async def test():
    orch = CompanyIntelOrchestrator()
    try:
        # Test na Aldent Wrocław - ma dużo opinii
        result = await orch.analyze(
            company_name='Aldent',
            website='https://aldent.wroclaw.pl',
            city='Wrocław',
            skip_social=True,
            skip_ai=True,
        )
        
        print('\n=== WYNIKI ANALIZY RECENZJI ===\n')
        
        for i, p in enumerate(result.placowki, 1):
            print(f'{i}. {p.adres.ulica}, {p.adres.miasto}')
            print(f'   Google Rating: {p.google_rating}, Recenzje: {p.google_reviews_count}')
            
            if p.reviews_insights:
                ins = p.reviews_insights
                print(f'\n   📊 INSIGHTS ({ins.total_reviews_analyzed} recenzji):')
                print(f'   Średnia: {ins.avg_rating:.1f}★')
                
                if ins.top_praises:
                    print(f'\n   ✅ POCHWAŁY:')
                    for praise in ins.top_praises:
                        print(f'      • {praise}')
                
                if ins.top_complaints:
                    print(f'\n   ⚠️  SKARGI:')
                    for complaint in ins.top_complaints:
                        print(f'      • {complaint}')
                
                if ins.common_themes:
                    print(f'\n   🏷️  TEMATY: {", ".join(ins.common_themes)}')
                
                if ins.summary:
                    print(f'\n   📝 PODSUMOWANIE:')
                    print(f'      {ins.summary}')
            else:
                print('   ⚠️  Brak insights')
            
            print()
        
        # Zapisz JSON
        with open('company_intel/test_reviews_result.json', 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        print('✅ Zapisano: company_intel/test_reviews_result.json')
        
    finally:
        await orch.close()


if __name__ == '__main__':
    asyncio.run(test())
