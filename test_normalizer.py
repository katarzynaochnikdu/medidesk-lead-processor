"""
Skrypt testowy do przetwarzania danych z test data.xlsx.
Wywołuje API normalizacji i identyfikacji, zapisuje wyniki do pliku.
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd
import httpx

# Konfiguracja
API_URL = "http://localhost:8080"
INPUT_FILE = "test data.xlsx"
OUTPUT_FILE = "test_results.xlsx"


async def process_lead(client: httpx.AsyncClient, lead_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Przetwarza jeden lead przez API.
    
    Args:
        client: Klient HTTP
        lead_data: Dane leada z Excel
    
    Returns:
        Odpowiedź z API
    """
    try:
        response = await client.post(
            f"{API_URL}/process",
            json={"data": lead_data},
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def extract_results(api_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wyciąga kluczowe informacje z odpowiedzi API.
    
    Returns:
        Słownik z wynikami do zapisu w Excel
    """
    if not api_response.get("success"):
        return {
            "status": "ERROR",
            "error": api_response.get("error", "Unknown error"),
        }
    
    normalized = api_response.get("normalized", {})
    gus_data = api_response.get("gus_data", {})
    duplicates = api_response.get("duplicates", {})
    recommendation = api_response.get("recommendation", {})
    
    # Kontakt
    contact_result = duplicates.get("contact", {})
    contact_exists = contact_result.get("exists", False)
    contact_id = contact_result.get("primary_id")
    contact_candidates = contact_result.get("candidates", [])
    
    contact_name = ""
    contact_tier = 0
    contact_signals = ""
    contact_needs_review = contact_result.get("needs_review", False)
    
    if contact_candidates:
        best = contact_candidates[0]
        contact_name = best.get("name", "")
        contact_tier = best.get("tier", 0)
        signals = best.get("signals", {})
        signal_str = []
        if signals.get("E"):
            signal_str.append("E")
        if signals.get("P"):
            signal_str.append("P")
        if signals.get("L"):
            signal_str.append("L")
        if signals.get("F"):
            signal_str.append("F")
        if signals.get("A"):
            signal_str.append("A")
        contact_signals = "+".join(signal_str)
    
    # Firma
    account_result = duplicates.get("account", {})
    account_exists = account_result.get("exists", False)
    account_id = account_result.get("parent_id")
    account_candidates = account_result.get("candidates", [])
    
    account_name = ""
    account_reason = ""
    if account_candidates:
        best_acc = account_candidates[0]
        account_name = best_acc.get("name", "")
        account_reason = best_acc.get("match_reason", "")
    
    # GUS
    gus_found = gus_data.get("found", False)
    gus_name = gus_data.get("full_name", "") if gus_found else ""
    gus_regon = gus_data.get("regon", "") if gus_found else ""
    gus_city = gus_data.get("city", "") if gus_found else ""
    
    return {
        # Status
        "status": "OK",
        
        # Normalizacja
        "norm_first_name": normalized.get("first_name", ""),
        "norm_last_name": normalized.get("last_name", ""),
        "norm_email": normalized.get("email", ""),
        "norm_phone": normalized.get("phone_formatted", ""),
        "norm_company_name": normalized.get("company_name", ""),
        "norm_nip": normalized.get("nip_formatted", ""),
        "norm_nip_valid": "TAK" if normalized.get("nip_valid") else "NIE",
        
        # GUS
        "gus_found": "TAK" if gus_found else "NIE",
        "gus_name": gus_name,
        "gus_regon": gus_regon,
        "gus_city": gus_city,
        
        # Kontakt - identyfikacja
        "contact_exists": "TAK" if contact_exists else "NIE",
        "contact_id": contact_id or "",
        "contact_name": contact_name,
        "contact_tier": f"Tier {contact_tier}" if contact_tier > 0 else "",
        "contact_signals": contact_signals,
        "contact_needs_review": "TAK" if contact_needs_review else "NIE",
        
        # Firma - identyfikacja
        "account_exists": "TAK" if account_exists else "NIE",
        "account_id": account_id or "",
        "account_name": account_name,
        "account_match": account_reason,
        
        # Rekomendacja
        "recommendation_action": recommendation.get("action", ""),
        "recommendation_confidence": f"{recommendation.get('confidence', 0):.0%}",
        "recommendation_reason": recommendation.get("reason", ""),
    }


async def main():
    """Główna funkcja testowa."""
    print(f"🔍 Wczytuję dane z {INPUT_FILE}...")
    
    # Wczytaj dane testowe
    try:
        df_input = pd.read_excel(INPUT_FILE)
    except Exception as e:
        print(f"❌ Błąd wczytywania pliku: {e}")
        return
    
    print(f"✅ Wczytano {len(df_input)} wierszy")
    print(f"\n📋 Kolumny w pliku: {list(df_input.columns)}")
    
    # Przygotuj wyniki
    results = []
    
    async with httpx.AsyncClient() as client:
        # Sprawdź czy API działa
        try:
            health = await client.get(f"{API_URL}/health", timeout=5.0)
            health.raise_for_status()
            print(f"✅ API działa: {health.json()}")
        except Exception as e:
            print(f"❌ API nie odpowiada: {e}")
            print(f"💡 Upewnij się że serwer jest uruchomiony: python -m uvicorn src.main:app --port 8080")
            return
        
        print(f"\n🚀 Przetwarzam {len(df_input)} leadów...")
        
        for idx, row in df_input.iterrows():
            print(f"\n[{idx + 1}/{len(df_input)}] Przetwarzam: {row.get('raw_name', 'N/A')}")
            
            # Przygotuj dane dla API (przekształć wiersz DataFrame na dict)
            lead_data = row.to_dict()
            
            # Usuń NaN (pandas wypełnia brakujące wartości jako NaN)
            lead_data = {k: (v if pd.notna(v) else None) for k, v in lead_data.items()}
            
            # Wywołaj API
            api_response = await process_lead(client, lead_data)
            
            # Wyciągnij wyniki
            result = extract_results(api_response)
            
            # Dodaj oryginalne dane
            result_row = {
                # Oryginalne dane
                "orig_raw_name": row.get("raw_name", ""),
                "orig_first_name": row.get("first_name", ""),
                "orig_last_name": row.get("last_name", ""),
                "orig_email": row.get("email", ""),
                "orig_phone": row.get("phone", ""),
                "orig_company": row.get("company", ""),
                "orig_nip": row.get("nip", ""),
                
                **result,
            }
            
            results.append(result_row)
            
            # Pokaż wynik
            if result["status"] == "OK":
                print(f"  ✅ {result['norm_first_name']} {result['norm_last_name']}")
                print(f"     Kontakt: {result['contact_exists']} ({result['contact_tier']} {result['contact_signals']})")
                print(f"     Firma: {result['account_exists']} - {result['account_name']}")
            else:
                print(f"  ❌ Błąd: {result.get('error', 'Unknown')}")
    
    # Zapisz wyniki do Excel
    print(f"\n💾 Zapisuję wyniki do {OUTPUT_FILE}...")
    
    df_results = pd.DataFrame(results)
    
    # Uporządkuj kolumny
    column_order = [
        # Status
        "status",
        
        # Oryginalne dane
        "orig_raw_name",
        "orig_first_name",
        "orig_last_name",
        "orig_email",
        "orig_phone",
        "orig_company",
        "orig_nip",
        
        # Znormalizowane dane
        "norm_first_name",
        "norm_last_name",
        "norm_email",
        "norm_phone",
        "norm_company_name",
        "norm_nip",
        "norm_nip_valid",
        
        # GUS
        "gus_found",
        "gus_name",
        "gus_regon",
        "gus_city",
        
        # Kontakt - identyfikacja
        "contact_exists",
        "contact_id",
        "contact_name",
        "contact_tier",
        "contact_signals",
        "contact_needs_review",
        
        # Firma - identyfikacja
        "account_exists",
        "account_id",
        "account_name",
        "account_match",
        
        # Rekomendacja
        "recommendation_action",
        "recommendation_confidence",
        "recommendation_reason",
    ]
    
    # Dodaj brakujące kolumny (jeśli są)
    for col in df_results.columns:
        if col not in column_order:
            column_order.append(col)
    
    df_results = df_results[column_order]
    
    # Zapisz do Excel z formatowaniem
    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        df_results.to_excel(writer, sheet_name='Wyniki', index=False)
        
        # Formatuj
        workbook = writer.book
        worksheet = writer.sheets['Wyniki']
        
        # Szerokość kolumn
        worksheet.column_dimensions['A'].width = 10  # status
        worksheet.column_dimensions['B'].width = 30  # orig_raw_name
        worksheet.column_dimensions['C'].width = 15  # orig_first_name
        worksheet.column_dimensions['D'].width = 15  # orig_last_name
        worksheet.column_dimensions['E'].width = 25  # orig_email
        worksheet.column_dimensions['F'].width = 15  # orig_phone
        worksheet.column_dimensions['G'].width = 30  # orig_company
        worksheet.column_dimensions['H'].width = 15  # orig_nip
        
        # Nagłówki pogrubione
        for cell in worksheet[1]:
            cell.font = cell.font.copy(bold=True)
    
    print(f"✅ Zapisano {len(results)} wyników do {OUTPUT_FILE}")
    print(f"\n📊 Podsumowanie:")
    
    ok_count = sum(1 for r in results if r["status"] == "OK")
    error_count = len(results) - ok_count
    
    contact_exists_count = sum(1 for r in results if r.get("contact_exists") == "TAK")
    account_exists_count = sum(1 for r in results if r.get("account_exists") == "TAK")
    
    print(f"  ✅ Przetworzono: {ok_count}/{len(results)}")
    print(f"  ❌ Błędy: {error_count}/{len(results)}")
    print(f"  👤 Kontakty istniejące: {contact_exists_count}")
    print(f"  🏢 Firmy istniejące: {account_exists_count}")


if __name__ == "__main__":
    asyncio.run(main())
