string standalone.ContactsDeduplicateByDelete(string recordId)
{
    info "=== DEDUPLIKACJA KONTAKTU PRZEZ USUNIĘCIE ===";
    info "ID analizowanego rekordu: " + recordId;

    // Pobierz analizowany rekord
    contact = zoho.crm.getRecordById("Contacts", recordId);
    if(contact == null)
    {
        return "❌ Błąd: Kontakt o ID " + recordId + " nie istnieje";
    }

    rodoUpdate = standalone.ContactRODOPropaguj(recordId);
    info "Rekord po aktualizacji RODO: " + rodoUpdate;

    // Zbierz potencjalne duplikaty dla rekordu przy użyciu funkcji RetrieveAllContactDup
    duplicateIdsMap = Map();
    dupIdsString = standalone.RetrieveAllContactDup(recordId);
    info "Lista duplikatów: " + dupIdsString;
    if(dupIdsString.startsWith("Brak") || dupIdsString.startsWith("Nie znaleziono"))
    {
        info "Brak potencjalnych duplikatów.";
    }
    else
    {
        dupIdsList = dupIdsString.toList(",");
        for each dupId in dupIdsList
        {
            dupIdTrimmed = dupId.trim();
            if(dupIdTrimmed != recordId)
            {
                duplicateIdsMap.put(dupIdTrimmed, dupIdTrimmed);
            }
        }
    }

    if(duplicateIdsMap.isEmpty())
    {
        info "Brak potencjalnych duplikatów. Zostawiam rekord bez zmian.";
        return "⚠️ Brak duplikatów dla kontaktu o ID " + recordId;
    }

    // Użyj nowej funkcji ContactAnalyzeAndTransferToHigherScore zamiast AnalyzeAndTransferContact
    analyzeResult = standalone.ContactAnalyzeAndTransferToHigherScore(recordId, duplicateIdsMap);
    info "Wynik analizy i przenoszenia: " + analyzeResult;
    
    // Sprawdź wynik operacji
    if(analyzeResult.contains("✅ Przeniesienie zakończone sukcesem"))
    {
        // Wyciągnij ID docelowego rekordu z wyniku
        if(analyzeResult.contains("został przeniesiony do"))
        {
            bestMatchIdText = analyzeResult.getSuffix("został przeniesiony do").trim();
            if(bestMatchIdText.contains(" "))
            {
                bestMatchId = bestMatchIdText.getPrefix(" ").trim();
                info "Znaleziono ID rekordu docelowego: " + bestMatchId;
                return analyzeResult;  // Zwracamy bezpośrednio wynik z ContactAnalyzeAndTransferToHigherScore
            }
        }
    }
    
    // Jeśli nie udało się znaleźć ID docelowego rekordu lub wystąpił błąd
    info "Nie udało się przeprowadzić deduplikacji.";
    return "⚠️ " + analyzeResult;
}
