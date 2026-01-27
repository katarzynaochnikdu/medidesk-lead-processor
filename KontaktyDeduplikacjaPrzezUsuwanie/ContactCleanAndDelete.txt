string standalone.ContactCleanAndDelete(string recordId)
{
    info "=== CZYSZCZENIE I USUWANIE KONTAKTU ===";
    info "ID rekordu: " + recordId;

    // Pobierz rekord
    contact = zoho.crm.getRecordById("Contacts", recordId);
    if(contact == null)
    {
        return "❌ Błąd: Kontakt o ID " + recordId + " nie istnieje";
    }

        // Użyj metody invokeConnector do usunięcia rekordu
        deleteRecordMap = map();
        deleteRecordMap.put("module", "Contacts");
        deleteRecordMap.put("id", recordId);
        
        try
        {
            deleteResp = zoho.crm.invokeConnector("crm.delete", deleteRecordMap);
            info "Odpowiedź z invokeConnector: " + deleteResp.toString();
            
            if(deleteResp.get("status_code") == 200)
            {
                return "✅ Kontakt o ID " + recordId + " został pomyślnie usunięty";
            }
            else
            {
                return "❌ Błąd przy usuwaniu rekordu: " + deleteResp.toString();
            }
        }
        catch (e)
        {
            info "Błąd przy wywołaniu invokeConnector: " + e;
            return "❌ Błąd przy wywołaniu invokeConnector: " + e;
        }
    
    return "⚠️ Operacja zakończona bez określonego statusu";
}
