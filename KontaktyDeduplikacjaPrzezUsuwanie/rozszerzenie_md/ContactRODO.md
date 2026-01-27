string standalone.ContactRODOPropaguj(String recordId)
{
    // Pobierz rekord kontaktu
    contact = zoho.crm.getRecordById("Contacts", recordId);
    
    // Pobierz wszystkie potrzebne pola
    emailMarketingowy = contact.get("Email_marketingowy");
    emailMarketingowyOdsubskrybuj = contact.get("Email_marketingowy_odsubskrybuj");
    
    email1 = contact.get("Email");
    email2 = contact.get("Secondary_Email");
    email3 = contact.get("Email_3");
    
    email1Rodo = contact.get("EMail1_RODO_wyrazona_niezgoda");
    email2Rodo = contact.get("EMail2_RODO_wyrazona_niezgoda");
    email3Rodo = contact.get("EMail3_RODO_wyrazona_niezgoda");
    
    updateMap = Map();
    
    // Przypadek 1: Wiemy który email został odsubskrybowany
    if (emailMarketingowyOdsubskrybuj == true && emailMarketingowy != null && emailMarketingowy != "")
    {
        // Oznacz odpowiednie pole RODO
        if (emailMarketingowy == email1)
        {
            updateMap.put("EMail1_RODO_wyrazona_niezgoda", true);
        }
        else if (emailMarketingowy == email2)
        {
            updateMap.put("EMail2_RODO_wyrazona_niezgoda", true);
        }
        else if (emailMarketingowy == email3)
        {
            updateMap.put("EMail3_RODO_wyrazona_niezgoda", true);
        }
        
        // Sprawdź czy jest dostępny inny email bez flagi RODO
        nowyEmailMarketingowy = "";
        if (email1 != null && email1 != "" && email1Rodo != true && email1 != emailMarketingowy)
        {
            nowyEmailMarketingowy = email1;
        }
        else if (email2 != null && email2 != "" && email2Rodo != true && email2 != emailMarketingowy)
        {
            nowyEmailMarketingowy = email2;
        }
        else if (email3 != null && email3 != "" && email3Rodo != true && email3 != emailMarketingowy)
        {
            nowyEmailMarketingowy = email3;
        }
        
        // Aktualizuj pola marketingowe
        updateMap.put("Email_marketingowy", nowyEmailMarketingowy);
        if (nowyEmailMarketingowy == "")
        {
            updateMap.put("Email_marketingowy_odsubskrybuj", true);
        }
        else
        {
            updateMap.put("Email_marketingowy_odsubskrybuj", false);
        }
    }
    // Przypadek 2: Nie wiemy który email został odsubskrybowany
    else if (emailMarketingowyOdsubskrybuj == true && (emailMarketingowy == null || emailMarketingowy == ""))
    {
        // Oznacz wszystkie niepuste emaile jako RODO
        if (email1 != null && email1 != "")
        {
            updateMap.put("EMail1_RODO_wyrazona_niezgoda", true);
        }
        if (email2 != null && email2 != "")
        {
            updateMap.put("EMail2_RODO_wyrazona_niezgoda", true);
        }
        if (email3 != null && email3 != "")
        {
            updateMap.put("EMail3_RODO_wyrazona_niezgoda", true);
        }
        
        // Pozostaw flagę odsubskrybowania
        updateMap.put("Email_marketingowy_odsubskrybuj", true);
    }
    
    // Zaktualizuj rekord jeśli są jakieś zmiany
    if (updateMap.size() > 0)
    {
        updateResponse = zoho.crm.updateRecord("Contacts", recordId, updateMap);
        return "Zaktualizowano status RODO";
    }
    
    return "Brak zmian w statusie RODO";
}