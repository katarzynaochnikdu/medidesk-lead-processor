string standalone.FirmaUsunNiskiScoring(string accountId)
{
    info "=== SPRAWDZANIE MOŻLIWOŚCI USUNIĘCIA FIRMY O NISKIM SCORINGU ===";
    info "Sprawdzanie możliwości usunięcia firmy o ID: " + accountId;
    info "Szczegóły firmy: " + zoho.crm.getRecordById("Accounts", accountId).get("Account_Name");
    
    responseMap = Map();
    
    // 1. Oblicz scoring firmy
    scoringStr = standalone.CalculateAccountScore(accountId);
    if(scoringStr == null || scoringStr == "")
    {
        responseMap.put("status", "error");
        responseMap.put("message", "Nie udało się obliczyć scoringu firmy");
        return responseMap.toString();
    }
    
    scoringMap = scoringStr.toMap();
    totalScore = scoringMap.get("AccountScoreDetale") + 
                scoringMap.get("AccountScorePowiazaniaModuly") + 
                scoringMap.get("AccountScorePowiazaniaRekordyModulow") +
                scoringMap.get("AccountScoreFirmyPowiazane") +
                scoringMap.get("AccountScoreKlienci");
    
    info "Scoring firmy: " + totalScore;
    info "Szczegółowe dane scoringu: " + scoringMap;
    
    // 2. Sprawdź powiązane kontakty
    accessToken = standalone.AccessToken();
    if(accessToken.startsWith("Błąd"))
    {
        responseMap.put("status", "error");
        responseMap.put("message", "Nie udało się pobrać tokenu dostępu");
        return responseMap.toString();
    }
    
    hasPowiazania = false;
    searchCriteria = "Account_Name:equals:" + accountId;
    powiazaneKontakty = standalone.searchContactsByAPI(searchCriteria, accessToken);
    if(powiazaneKontakty != null && powiazaneKontakty.size() > 0)
    {
        hasPowiazania = true;
        info "Znaleziono powiązane kontakty: " + powiazaneKontakty.size();
    }
    
    // 3. Usuń firmę jeśli spełnione warunki
    if(!hasPowiazania && totalScore < 5)
    {
        info "Próba usunięcia firmy o niskim scoringu...";
        deleteResult = standalone.AccountRecordDeleteInvokeConnector(accountId);
        
        if(deleteResult.containsKey("status") && deleteResult.get("status") == "success")
        {
            info "✅ Firma została pomyślnie usunięta";
            responseMap.put("status", "success");
            responseMap.put("usunietoFirme", true);
        }
        else 
        {
            info "❌ Błąd podczas usuwania firmy: " + deleteResult;
            responseMap.put("status", "error");
            responseMap.put("message", "Błąd podczas usuwania firmy");
            responseMap.put("bladUsuwania", deleteResult.toString());
        }
    }
    else
    {
        info "Firma nie może zostać usunięta:";
        if(hasPowiazania)
        {
            info "- Posiada powiązane kontakty";
        }
        if(totalScore >= 5)
        {
            info "- Scoring firmy (" + totalScore + ") jest >= 5";
        }
        responseMap.put("status", "success");
        responseMap.put("usunietoFirme", false);
        responseMap.put("powod", "Powiązane kontakty: " + hasPowiazania + ", Scoring: " + totalScore);
    }
    
    info "=== KONIEC SPRAWDZANIA ===";
    return responseMap.toString();
}