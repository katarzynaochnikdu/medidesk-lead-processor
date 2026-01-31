"""Sprawdza wszystkie pliki wynikowe pod kątem błędów."""
import json
import sys
import os

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Znajdz wszystkie pliki results_*.json
import glob
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = glob.glob(os.path.join(base_dir, 'results_*.json'))
files += glob.glob(os.path.join(base_dir, 'company_intel', 'results_*.json'))

problems = []

print("=" * 100)
print("SPRAWDZENIE WSZYSTKICH PLIKÓW WYNIKOWYCH")
print("=" * 100)
print()

for f in files:
    if not os.path.exists(f):
        print(f"[SKIP] {f} - nie istnieje")
        continue
    
    with open(f, encoding='utf-8') as fp:
        data = json.load(fp)
    
    c = data.get('company', data)
    nazwa = c.get('nazwa_pelna', 'N/A')[:40]
    
    # Zbierz wszystkie telefony
    all_phones = []
    bad_phones = []
    
    for p in c.get('placowki', []):
        for k in p.get('kontakty', []):
            if k.get('typ') == 'telefon':
                phone = k.get('wartosc', '')
                all_phones.append(phone)
                
                # Sprawdz format +48 XXX XXX XXX
                if not phone.startswith('+48 '):
                    bad_phones.append(f'brak formatu +48: {phone}')
                
                # Wyciagnij cyfry
                digits = phone.replace(' ', '').replace('+48', '').replace('+', '')
                
                # Sprawdz fake numery
                if '123456' in digits or '111111' in digits or '000000' in digits:
                    bad_phones.append(f'FAKE numer: {phone}')
                
                # Sprawdz dlugosc (powinno byc 9 cyfr)
                if len(digits) != 9:
                    bad_phones.append(f'zla dlugosc ({len(digits)} cyfr): {phone}')
    
    # Wyswietl wynik
    status = "OK" if not bad_phones else "BLAD"
    print(f"[{status:4}] {os.path.basename(f)[:35]:35} | {nazwa[:35]:35} | tel: {len(all_phones)}")
    
    if all_phones:
        for phone in all_phones:
            print(f"       -> {phone}")
    
    if bad_phones:
        problems.append((f, nazwa, bad_phones))
        for issue in bad_phones:
            print(f"       !! {issue}")
    
    print()

print("=" * 100)
if problems:
    print(f"ZNALEZIONO {len(problems)} PLIKOW Z PROBLEMAMI:")
    print("=" * 100)
    for f, nazwa, issues in problems:
        print(f"\n{f}: {nazwa}")
        for issue in issues:
            print(f"  - {issue}")
else:
    print("WSZYSTKIE PLIKI OK - BRAK PROBLEMOW Z TELEFONAMI!")
print("=" * 100)
