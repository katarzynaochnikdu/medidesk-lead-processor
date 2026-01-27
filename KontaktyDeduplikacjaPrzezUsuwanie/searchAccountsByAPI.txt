string standalone.searchAccountsByAPI(String criteria, String accessToken)
{
    try {
        // Sprawdzenie, czy accessToken został przekazany, w przeciwnym razie generujemy nowy token
        if(accessToken == null || accessToken.trim().length() == 0)
        {
            accessToken = standalone.AccessToken();
            if(accessToken.startsWith("Błąd"))
            {
                info "Błąd podczas pobierania tokena: " + accessToken;
                return accessToken.toString();
            }
        }
        
        // Przygotowanie nagłówków
        headers = Map();
        headers.put("Authorization", "Zoho-oauthtoken " + accessToken);
        
        // Przygotowanie URL do API z uniwersalnymi kryteriami - zmienione na Accounts
        apiURL = "https://www.zohoapis.eu/crm/v7/Accounts/search?criteria=(" + encodeUrl(criteria) + ")";
        info "URL do API: " + apiURL;
        
        // Wywołanie API
        response = invokeurl
        [
            url: apiURL
            type: GET
            headers: headers
        ];
        
        info "Odpowiedź z API: " + response;
        
        // Sprawdzenie odpowiedzi
        if(response.get("data") != null)
        {
            records = response.get("data");
            recordIds = List();
            
            // Wyciągnięcie ID znalezionych rekordów
            for each record in records
            {
                recordIds.add(record.get("id"));
            }
            
            info "Znalezione ID przez API: " + recordIds.toString(",");
            // Zabezpieczenie przed null
            result = recordIds.toString(",");
            if(result == null)
            {
                return "";
            }
            return result.toString();
        }
        
        info "Brak wyników z API";
        return "";
    }
    catch (e)
    {
        info "Błąd podczas wyszukiwania przez API: " + e.toString();
        return e.toString();
    }
    return "";
}