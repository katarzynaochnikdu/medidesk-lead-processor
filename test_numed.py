import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

from nip_finder.orchestrator import NIPFinder

async def test():
    finder = NIPFinder()
    
    companies = ['Nu-med Elbląg', 'Nu-med Katowice']
    
    for name in companies:
        result = await finder.find_nip(company_name=name)
        nip = result.nip_formatted if result.nip else "---"
        print(f'{name}: found={result.found}, nip={nip}')
        if result.search_queries_used:
            print(f'  Queries: {result.search_queries_used[:3]}')
    
    await finder.close()

if __name__ == "__main__":
    asyncio.run(test())
