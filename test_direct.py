"""
Test bezpośredni - bez API, używa modułów bezpośrednio.
Dla szybkiego testowania bez uruchamiania serwera.
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


async def main():
    """Główna funkcja testowa."""
    print("==> Wczytuje dane z test data.xlsx...")
    
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
    
    print(f"\n==> Przetwarzam {len(df_input)} leadow...\n")
    
    for idx, row in df_input.iterrows():
        # Mapuj kolumny z Excel na pola API
        raw_phone = row.get("Telefon komórkowy")
        # Konwertuj telefon na string (Excel może go czytać jako int)
        if pd.notna(raw_phone):
            raw_phone = str(int(raw_phone)) if isinstance(raw_phone, (int, float)) else str(raw_phone)
        else:
            raw_phone = None
        
        lead_data = {
            "id": row.get("Id rekordu"),
            "raw_name": row.get("Marketing Lead - nazwa"),
            "email": row.get("Adres Email"),
            "phone": raw_phone,
            "company": row.get("Firma"),
            "first_name": row.get("Imię"),
            "last_name": row.get("Nazwisko"),
            "description": row.get("Treść wiadomości z formularza"),
        }
        # Usuń NaN dla pozostałych
        lead_data = {
            k: (str(v) if pd.notna(v) and v is not None else None) 
            for k, v in lead_data.items()
        }
        
        display_name = lead_data.get("raw_name") or f"{lead_data.get('first_name', '')} {lead_data.get('last_name', '')}".strip() or "N/A"
        print(f"[{idx + 1}/{len(df_input)}] {display_name}")
        
        try:
            # Przetwórz - PEŁNY PIPELINE z AI
            output = await service.process_lead(
                raw_data=lead_data,
                skip_ai=False,  # Z normalizacją AI (Vertex AI/Gemini) - WAŻNE!
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
                    nip_source = "nie znany"
            
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
                "status": "OK",
                
                # Oryginalne
                "orig_raw_name": row.get("raw_name", ""),
                "orig_first_name": row.get("first_name", ""),
                "orig_last_name": row.get("last_name", ""),
                "orig_email": row.get("email", ""),
                "orig_phone": row.get("phone", ""),
                "orig_company": row.get("company", ""),
                "orig_nip": row.get("nip", ""),
                
                # Znormalizowane
                "norm_first_name": normalized.first_name or "",
                "norm_last_name": normalized.last_name or "",
                "norm_email": normalized.email or "",
                "norm_phone": normalized.phone_formatted or "",
                "norm_company_name": normalized.company_name or "",
                "norm_nip": normalized.nip_formatted or "",
                "norm_nip_valid": "TAK" if normalized.nip_valid else "NIE",
                "norm_nip_source": nip_source,
                
                # GUS (mock - zawsze false)
                "gus_found": "TAK" if gus_data.found else "NIE",
                "gus_name": gus_data.full_name or "",
                
                # Kontakt - identyfikacja
                "contact_exists": "TAK" if contact_result.exists else "NIE",
                "contact_id": contact_result.primary_id or "",
                "contact_name": contact_name,
                "contact_tier": f"Tier {contact_tier}" if contact_tier > 0 else "",
                "contact_signals": contact_signals,
                "contact_needs_review": "TAK" if contact_result.needs_review else "NIE",
                
                # Firma - identyfikacja
                "account_exists": "TAK" if account_result.exists else "NIE",
                "account_id": account_result.parent_id or "",
                "account_name": account_name,
                "account_match": account_match_reason,
                
                # Rekomendacja
                "recommendation_action": recommendation.action,
                "recommendation_confidence": f"{recommendation.confidence:.0%}",
                "recommendation_reason": recommendation.reason,
            }
            
            print(f"  OK: {result['norm_first_name']} {result['norm_last_name']}")
            print(f"      Kontakt: {result['contact_exists']} ({result['contact_tier']} {result['contact_signals']})")
            print(f"      Firma: {result['account_exists']}")
            print()
            
        except Exception as e:
            print(f"  ERROR: {e}")
            result = {
                "status": "ERROR",
                "error": str(e),
                "orig_raw_name": lead_data.get("raw_name", ""),
                "orig_first_name": lead_data.get("first_name", ""),
                "orig_last_name": lead_data.get("last_name", ""),
                "orig_email": lead_data.get("email", ""),
                "orig_phone": lead_data.get("phone", ""),
                "orig_company": lead_data.get("company", ""),
            }
        
        results.append(result)
    
    # Zamknij połączenia
    await service.close()
    
    # Zapisz wyniki
    print(f"\n==> Zapisuje wyniki do test_results.xlsx...")
    
    df_results = pd.DataFrame(results)
    
    # Zapisz do Excel
    with pd.ExcelWriter("test_results.xlsx", engine='openpyxl') as writer:
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
            adjusted_width = min(max_length + 2, 50)  # Max 50
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    print(f"OK: Zapisano {len(results)} wynikow\n")
    
    # Podsumowanie
    ok_count = sum(1 for r in results if r.get("status") == "OK")
    error_count = len(results) - ok_count
    
    contact_exists_count = sum(1 for r in results if r.get("contact_exists") == "TAK")
    account_exists_count = sum(1 for r in results if r.get("account_exists") == "TAK")
    
    print(f"=== PODSUMOWANIE ===")
    print(f"  Przetworzono: {ok_count}/{len(results)}")
    print(f"  Bledy: {error_count}/{len(results)}")
    print(f"  Kontakty istniejace (mock): {contact_exists_count}")
    print(f"  Firmy istniejace (mock): {account_exists_count}")
    print(f"\nWyniki zapisane w: test_results.xlsx")


if __name__ == "__main__":
    asyncio.run(main())
