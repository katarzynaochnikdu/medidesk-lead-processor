"""Test ulepszonego wyszukiwania NIP z polityką prywatności."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config import get_settings
from src.services.brave_search import BraveSearchService


async def test_nip_search():
    """Test różnych strategii wyszukiwania NIP."""
    
    settings = get_settings()
    brave = BraveSearchService(settings)
    
    # Przykładowe firmy do testowania
    test_cases = [
        {
            "name": "Test z domeną firmową",
            "company": "Przychodnia Medica",
            "domain": "przychodnia-medica.pl",  # Przykładowa domena
        },
        {
            "name": "Test bez domeny",
            "company": "NZOZ Vitamed",
            "domain": None,
        },
        {
            "name": "Test z małą firmą",
            "company": "Gabinet Lekarski Anna Kowalska",
            "domain": "gabinet-kowalska.pl",
        },
    ]
    
    print("="*80)
    print("TEST ULEPSZONEGO WYSZUKIWANIA NIP")
    print("="*80)
    print()
    
    for tc in test_cases:
        print(f"\n{'='*80}")
        print(f"TEST: {tc['name']}")
        print(f"Firma: {tc['company']}")
        print(f"Domena: {tc['domain'] or 'brak'}")
        print(f"{'='*80}\n")
        
        try:
            nip = await brave.find_nip(
                company_name=tc['company'],
                email_domain=tc['domain']
            )
            
            if nip:
                print(f"✅ ZNALEZIONO NIP: {nip}")
                
                # Jeśli mamy domenę, sprawdź walidację
                if tc['domain']:
                    validated = await brave.validate_nip_domain(nip, tc['domain'])
                    print(f"   Walidacja z domeną: {'✅ TAK' if validated else '❌ NIE'}")
            else:
                print(f"❌ NIE ZNALEZIONO NIP")
                
        except Exception as e:
            print(f"❌ BŁĄD: {e}")
        
        print()
    
    await brave.close()
    
    print("\n" + "="*80)
    print("TESTY ZAKOŃCZONE")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(test_nip_search())
