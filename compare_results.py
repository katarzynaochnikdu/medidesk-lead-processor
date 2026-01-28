"""Porównanie wyników testu z referencją."""

import pandas as pd

# Wczytaj oba pliki
df_ref = pd.read_excel("test data reference result.xlsx")
df_test = pd.read_excel("test_results.xlsx")

print("=" * 80)
print("POROWNANIE WYNIKOW TESTU Z REFERENCJA")
print("=" * 80)

# Mapuj kolumny (polskie znaki są źle kodowane, używam indeksów)
contact_id_ref_col = df_ref.columns[7]  # 'Powiązanie Kontaktu z bazy.id'
contact_name_ref_col = df_ref.columns[8]  # 'Powiązanie Kontaktu z bazy'
account_id_ref_col = df_ref.columns[9]  # 'Powiązanie Firmy z bazy.id'
account_name_ref_col = df_ref.columns[10]  # 'Powiązanie Firmy z bazy'

print(f"\nKolumny referencji:")
print(f"  Kontakt ID: '{contact_id_ref_col}'")
print(f"  Kontakt nazwa: '{contact_name_ref_col}'")
print(f"  Firma ID: '{account_id_ref_col}'")
print(f"  Firma nazwa: '{account_name_ref_col}'")

# Porównaj wiersz po wierszu
matches = {"kontakt": 0, "firma": 0, "total": len(df_ref)}
mismatches = []

for idx in range(len(df_ref)):
    ref_contact_id = df_ref.iloc[idx][contact_id_ref_col]
    ref_account_id = df_ref.iloc[idx][account_id_ref_col]
    
    test_contact_id = df_test.iloc[idx]["contact_id"]
    test_account_id = df_test.iloc[idx]["account_id"]
    
    test_contact_exists = df_test.iloc[idx]["contact_exists"]
    test_account_exists = df_test.iloc[idx]["account_exists"]
    
    # Kontakt
    ref_contact_exists = pd.notna(ref_contact_id) and ref_contact_id != "nowy"
    test_contact_match = (ref_contact_exists and test_contact_exists == "TAK") or (not ref_contact_exists and test_contact_exists == "NIE")
    
    if test_contact_match:
        matches["kontakt"] += 1
    else:
        mismatches.append({
            "row": idx + 1,
            "type": "kontakt",
            "ref": ref_contact_id if ref_contact_exists else "nowy",
            "test": f"{test_contact_exists} (ID: {test_contact_id})",
        })
    
    # Firma
    ref_account_exists = pd.notna(ref_account_id)
    test_account_match = (ref_account_exists and test_account_exists == "TAK") or (not ref_account_exists and test_account_exists == "NIE")
    
    if test_account_match:
        matches["firma"] += 1
    else:
        mismatches.append({
            "row": idx + 1,
            "type": "firma",
            "ref": ref_account_id if ref_account_exists else "brak",
            "test": f"{test_account_exists} (ID: {test_account_id})",
        })

print("\n" + "=" * 80)
print("WYNIKI")
print("=" * 80)
print(f"\nKontakty: {matches['kontakt']}/{matches['total']} dopasowanych ({100*matches['kontakt']/matches['total']:.0f}%)")
print(f"Firmy: {matches['firma']}/{matches['total']} dopasowanych ({100*matches['firma']/matches['total']:.0f}%)")

if mismatches:
    print(f"\n=== ROZNICE ({len(mismatches)}) ===")
    for mm in mismatches[:10]:  # Pokaż pierwsze 10
        print(f"  Wiersz {mm['row']} ({mm['type']}): REF={mm['ref']}, TEST={mm['test']}")

# Pokaż szczegóły znalezionych kontaktów
print("\n" + "=" * 80)
print("ZNALEZIONE KONTAKTY (TEST)")
print("=" * 80)

found_contacts = df_test[df_test['contact_exists'] == 'TAK']
print(f"\nZnaleziono {len(found_contacts)} kontaktow:")
for idx in found_contacts.index:
    print(f"  [{idx+1}] {df_test.iloc[idx]['norm_first_name']} {df_test.iloc[idx]['norm_last_name']}")
    print(f"      Tier: {df_test.iloc[idx]['contact_tier']}, Sygnaly: {df_test.iloc[idx]['contact_signals']}")
    print(f"      ID: {df_test.iloc[idx]['contact_id']}")

# Pokaż szczegóły walidacji firm
print("\n" + "=" * 80)
print("WALIDACJA FIRM (odrzucone)")
print("=" * 80)

print("\nFirmy odrzucone jako nierelewantne:")
for idx in [3, 10, 11]:
    orig_company = df_ref.iloc[idx]['Firma'] if pd.notna(df_ref.iloc[idx]['Firma']) else 'brak'
    test_company = df_test.iloc[idx]['norm_company_name'] if pd.notna(df_test.iloc[idx]['norm_company_name']) else 'null (odrzucona)'
    print(f"  [{idx+1}] Oryginalna: '{orig_company}' -> Znormalizowana: '{test_company}'")

print("\n" + "=" * 80)
