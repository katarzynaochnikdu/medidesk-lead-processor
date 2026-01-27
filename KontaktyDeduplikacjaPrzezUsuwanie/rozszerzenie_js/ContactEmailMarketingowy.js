string standalone.ContactEmailMarketingowy(String recordId)
{
    // Pobierz rekord kontaktu na podstawie recordId
    contact = zoho.crm.getRecordById("Contacts", recordId);
    
    // Sprawdź Email 1
    if(contact.get("EMail1_RODO_wyrazona_niezgoda") == false && contact.get("Email") != null)
    {
        contact.put("Email_marketingowy", contact.get("Email"));
        contact.put("Email_marketingowy_odsubskrybuj", false);
    }
    // Sprawdź Email 2
    else if(contact.get("EMail2_RODO_wyrazona_niezgoda") == false && contact.get("Secondary_Email") != null)
    {
        contact.put("Email_marketingowy", contact.get("Secondary_Email"));
        contact.put("Email_marketingowy_odsubskrybuj", false);
    }
    // Sprawdź Email 3
    else if(contact.get("EMail3_RODO_wyrazona_niezgoda") == false && contact.get("Email_3") != null)
    {
        contact.put("Email_marketingowy", contact.get("Email_3"));
        contact.put("Email_marketingowy_odsubskrybuj", false);
    }
    // Jeśli żaden email nie jest dostępny do subskrypcji
    else
    {
        contact.put("Email_marketingowy", "");
        contact.put("Email_marketingowy_odsubskrybuj", true);
    }
    
    // Zaktualizuj rekord kontaktu
    updateResponse = zoho.crm.updateRecord("Contacts", recordId, contact);
    return updateResponse.toString();
}