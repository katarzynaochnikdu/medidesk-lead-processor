"""
Test Wariant 2: Surowy tekst
Wszystkie dane jako jeden zlepek tekstu w raw_name.
Pozostałe pola puste/null. AI musi sam wyekstrahować wszystko.
"""

import asyncio
import sys
from pathlib import Path

import pandas as pd

# Dodaj src do path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import get_settings
from src.models.lead_input import LeadInputRaw, LeadInput
from src.services.data_normalizer import DataNormalizerService


def build_raw_text(row: pd.Series) -> str:
    """
    Buduje surowy tekst ze wszystkich dostępnych pól.
    Format: "Marketing Lead - nazwa: {value}\nFirma: {value}\n..."
    """
    parts = []
    
    # Marketing Lead - nazwa (jeśli istnieje)
    raw_name = row.get("Marketing Lead - nazwa")
    if pd.notna(raw_name) and raw_name:
        parts.append(f"Marketing Lead - nazwa: {raw_name}")
    
    # Firma
    firma = row.get("Firma")
    if pd.notna(firma) and firma:
        parts.append(f"Firma: {firma}")
    
    # Imię
    imie = row.get("Imię")
    if pd.notna(imie) and imie:
        parts.append(f"Imię: {imie}")
    
    # Nazwisko
    nazwisko = row.get("Nazwisko")
    if pd.notna(nazwisko) and nazwisko:
        parts.append(f"Nazwisko: {nazwisko}")
    
    # Email
    email = row.get("Adres Email")
    if pd.notna(email) and email:
        parts.append(f"Email: {email}")
    
    # Telefon
    telefon = row.get("Telefon komórkowy")
    if pd.notna(telefon) and telefon:
        # Konwertuj na string (Excel może czytać jako int)
        if isinstance(telefon, (int, float)):
            telefon = str(int(telefon))
        parts.append(f"Telefon: {telefon}")
    
    # Treść wiadomości
    tresc = row.get("Treść wiadomości z formularza")
    if pd.notna(tresc) and tresc:
        parts.append(f"Treść: {tresc}")
    
    return "\n".join(parts)


async def main():
    """Główna funkcja testowa - wariant surowy tekst."""
    print("=" * 80)
    print("TEST WARIANT 2: SUROWY TEKST")
    print("=" * 80)
    print("\n==> Wczytuje dane z test data.xlsx...")
    
    # Wczytaj dane testowe
    try:
        df_input = pd.read_excel("test data.xlsx")
    except Exception as e:
        print(f"ERROR: Blad wczytywania pliku: {e}")
        return
    
    print(f"OK: Wczytano {len(df_input)} wierszy")
    print(f"\nKolumny w pliku: {list(df_input.columns)}")
    
    # Inicjalizuj serwis (prawdziwe połączenia z Zoho + GUS)
    print("\n==> Inicjalizuje serwis (PRAWDZIWE polaczenia: Zoho CRM + GUS)...")
    settings = get_settings()
    service = DataNormalizerService(settings=settings, use_mocks=False)
    
    # Przygotuj wyniki
    results = []
    
    print(f"\n==> Przetwarzam {len(df_input)} leadow (SUROWY TEKST)...\n")
    
    for idx, row in df_input.iterrows():
        # WARIANT SUROWY TEKST - wszystko w raw_name, reszta pusta
        raw_text = build_raw_text(row)
        
        lead_data = {
            "id": row.get("Id rekordu"),
            "raw_name": raw_text,  # Cały kontekst jako jeden tekst
            # Pozostałe pola celowo puste - AI musi wyekstrahować
            "email": None,
            "phone": None,
            "company": None,
            "first_name": None,
            "last_name": None,
            "description": None,
        }
        # Usuń NaN dla id
        lead_data = {
            k: (str(v) if pd.notna(v) and v is not None else None) 
            for k, v in lead_data.items()
        }
        
        # Pokaż skrócony raw_text
        display_text = raw_text[:60] + "..." if len(raw_text) > 60 else raw_text
        display_text = display_text.replace("\n", " | ")
        print(f"[{idx + 1}/{len(df_input)}] {display_text}")
        
        try:
            # Przetwórz - PEŁNY PIPELINE z AI
            output = await service.process_lead(
                raw_data=lead_data,
                skip_ai=False,  # Z normalizacją AI (Vertex AI/Gemini)
                skip_gus=False,  # Z GUS - wyszukiwanie po NIP
                skip_duplicates=False,  # Z deduplikacją w Zoho CRM
            )
            
            normalized = output.normalized
            gus_data = output.gus_data
            duplicates = output.duplicates
            recommendation = output.recommendation
            warnings = output.warnings
            
            # Sprawdź czy NIP był znaleziony przez Brave
            nip_source = ""
            if normalized.nip:
                if any("Brave Search" in w for w in warnings):
                    nip_source = "Brave Search"
                elif lead_data.get("nip"):
                    nip_source = "dane wejsciowe"
                else:
                    nip_source = "AI/ekstrakcja"
            
            # Kontakt
            contact_result = duplicates.contact
            contact_candidates = contact_result.candidates
            
            contact_name = ""
            contact_tier = 0
            contact_signals = ""
            
            if contact_candidates:
                best = contact_candidates[0]
                contact_name = best.name
                contact_tier = best.tier
                signals = best.signals
                signal_parts = []
                if signals.E:
                    signal_parts.append("E")
                if signals.P:
                    signal_parts.append("P")
                if signals.L:
                    signal_parts.append("L")
                if signals.F:
                    signal_parts.append("F")
                if signals.A:
                    signal_parts.append("A")
                contact_signals = "+".join(signal_parts)
            
            # Firma
            account_result = duplicates.account
            account_candidates = account_result.candidates
            
            account_name = ""
            account_match_reason = ""
            if account_candidates:
                best_acc = account_candidates[0]
                account_name = best_acc.name
                account_match_reason = best_acc.match_reason
            
            # Zapisz wyniki
            result = {
                "row_num": idx + 1,
                "status": "OK",
                "variant": "RAW_TEXT",
                
                # Oryginalny surowy tekst (skrócony)
                "input_raw_text": raw_text[:200] + "..." if len(raw_text) > 200 else raw_text,
                
                # Znormalizowane (wyekstrahowane przez AI)
                "norm_first_name": normalized.first_name or "",
                "norm_last_name": normalized.last_name or "",
                "norm_email": normalized.email or "",
                "norm_phone": normalized.phone_formatted or "",
                "norm_company_name": normalized.company_name or "",
                "norm_nip": normalized.nip_formatted or "",
                "norm_nip_valid": "TAK" if normalized.nip_valid else "NIE",
                "norm_nip_source": nip_source,
                
                # GUS
                "gus_found": "TAK" if gus_data.found else "NIE",
                "gus_name": gus_data.full_name or "",
                
                # Kontakt - identyfikacja
                "contact_exists": "TAK" if contact_result.exists else "NIE",
                "contact_id": contact_result.primary_id or "",
                "contact_name": contact_name,
                "contact_tier": contact_tier,
                "contact_signals": contact_signals,
                "contact_needs_review": "TAK" if contact_result.needs_review else "NIE",
                "contact_candidates_count": len(contact_candidates),
                
                # Firma - identyfikacja
                "account_exists": "TAK" if account_result.exists else "NIE",
                "account_id": account_result.parent_id or "",
                "account_name": account_name,
                "account_match": account_match_reason,
                "account_candidates_count": len(account_candidates),
                
                # Rekomendacja
                "recommendation_action": recommendation.action,
                "recommendation_confidence": recommendation.confidence,
                "recommendation_reason": recommendation.reason,
                
                # Ostrzeżenia
                "warnings": "; ".join(warnings) if warnings else "",
            }
            
            print(f"  OK: {result['norm_first_name']} {result['norm_last_name']}")
            print(f"      Kontakt: {result['contact_exists']} (Tier {result['contact_tier']} {result['contact_signals']})")
            print(f"      Firma: {result['account_exists']}")
            print()
            
        except Exception as e:
            print(f"  ERROR: {e}")
            result = {
                "row_num": idx + 1,
                "status": "ERROR",
                "variant": "RAW_TEXT",
                "error": str(e),
                "input_raw_text": raw_text[:200] + "..." if len(raw_text) > 200 else raw_text,
            }
        
        results.append(result)
    
    # Zamknij połączenia
    await service.close()
    
    # Zapisz wyniki
    output_file = "test_results_variant2.xlsx"
    print(f"\n==> Zapisuje wyniki do {output_file}...")
    
    df_results = pd.DataFrame(results)
    
    # Zapisz do Excel
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df_results.to_excel(writer, sheet_name='Wyniki', index=False)
        
        # Formatuj
        workbook = writer.book
        worksheet = writer.sheets['Wyniki']
        
        # Nagłówki pogrubione
        for cell in worksheet[1]:
            cell.font = cell.font.copy(bold=True)
        
        # Auto-width dla wszystkich kolumn
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if cell.value and len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    print(f"OK: Zapisano {len(results)} wynikow\n")
    
    # Podsumowanie
    ok_count = sum(1 for r in results if r.get("status") == "OK")
    error_count = len(results) - ok_count
    
    contact_exists_count = sum(1 for r in results if r.get("contact_exists") == "TAK")
    account_exists_count = sum(1 for r in results if r.get("account_exists") == "TAK")
    
    print("=" * 80)
    print("PODSUMOWANIE WARIANT 2 (SUROWY TEKST)")
    print("=" * 80)
    print(f"  Przetworzono: {ok_count}/{len(results)}")
    print(f"  Bledy: {error_count}/{len(results)}")
    print(f"  Kontakty istniejace: {contact_exists_count}")
    print(f"  Firmy istniejace: {account_exists_count}")
    print(f"\nWyniki zapisane w: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
