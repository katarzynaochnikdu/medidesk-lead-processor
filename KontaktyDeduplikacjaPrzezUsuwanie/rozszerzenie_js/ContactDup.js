string standalone.ContactDup(String warunki)
{
    try {
        // Wyszukiwanie rekordów w module Contacts na podstawie warunków
        info "Wyszukiwanie rekordów w Contacts z warunkami: " + warunki;
        records = zoho.crm.searchRecords("Contacts", warunki);
        info "Wyniki wyszukiwania dla warunków [" + warunki + "]: " + records;
        
        // Sprawdzenie, czy znaleziono jakieś rekordy
        if (records != null && records.size() > 0)
        {
            // Pobranie numerów rekordów (ID)
            record_ids = list();
            for each record in records
            {
                record_ids.add(record.get("id"));
            }
            info "Znaleziono rekordy: " + record_ids.toString();
            // Zwrócenie listy ID jako string (połączone przecinkami)
            return record_ids.toString(", ");
        }
        else
        {
            // Jeśli brak wyników, zwróć pusty string
            info "Brak znalezionych rekordów dla warunków: " + warunki;
            return "";
        }
    } catch (e) {
        return "Błąd podczas wyszukiwania rekordów: " + e.toString();
    }
}

// Nowa funkcja do wyszukiwania przez API
searchContactsByAPI(criteria)
{
    try {
        // Przygotowanie nagłówków
        headers = Map();
        headers.put("Authorization", "Zoho-oauthtoken " + zoho.getCurrentUserAccessToken());
        
        // Przygotowanie URL do API
        apiURL = "https://www.zohoapis.com/crm/v7/Contacts/search?criteria=" + encodeUrl(criteria);
        
        // Wywołanie API
        response = invokeurl
        [
            url: apiURL
            type: GET
            headers: headers
        ];
        
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
            
            return recordIds.toString(",");
        }
        
        return "";
    }
    catch (e)
    {
        info "Błąd podczas wyszukiwania przez API: " + e;
        return "";
    }
} 