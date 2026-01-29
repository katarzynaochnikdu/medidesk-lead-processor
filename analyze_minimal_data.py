"""Analiza przypadków ze skromnymi danymi."""

import pandas as pd

df = pd.read_excel('test set 2.xlsx')

print('=== PRZYPADKI ZE SKROMNYMI DANYMI (brak domeny firmowej) ===')
print()

# Przypadki bez emaila lub z publicznym emailem (gmail, outlook, wp.pl)
minimal_data = df[
    df['Adres Email'].isna() | 
    df['Adres Email'].str.contains('gmail|outlook|wp.pl|o2.pl|interia', case=False, na=False)
]

print(f'Znaleziono: {len(minimal_data)} przypadków\n')

# Pokaż pierwsze 15
for idx, row in minimal_data.head(15).iterrows():
    print(f"Row {idx+1}:")
    print(f"  Marketing Lead: {row['Marketing Lead - nazwa']}")
    print(f"  Firma: {row.get('Firma', 'brak')}")
    print(f"  Email: {row['Adres Email']}")
    print(f"  Imię/Nazwisko: {row.get('Imię', 'brak')} {row.get('Nazwisko', 'brak')}")
    print()
