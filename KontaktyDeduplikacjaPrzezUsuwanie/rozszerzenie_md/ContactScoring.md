string standalone.calculateContactScore(String recordId)
{
    // Funkcja oblicza scoring (punktację) kontaktu na podstawie kompletności danych i powiązań
    // Scoring określa "wartość" kontaktu w systemie CRM
    
    /*
    | Klucz w mapie result                     | Typ danych | Opis                                                                 |
    |------------------------------------------|------------|----------------------------------------------------------------------|
    | ContactScoreDetale                       | int        | Liczba wypełnionych ważnych pól kontaktu (w tym firma, jeśli przypisana) |
    | ContactWypelnionePola                    | List       | Lista etykiet (label) wypełnionych pól                               |
    | ContactScorePowiazania                   | int        | Liczba modułów, z którymi kontakt ma co najmniej jeden powiązany rekord |
    | ContactPowiazania                        | List       | Lista nazw modułów, z którymi kontakt ma powiązania                 |
    | ContactScorePowiazaniaRekordyModulow     | int        | Łączna liczba rekordów powiązanych z kontaktem we wszystkich modułach |
    | ContactHasAccount                        | bool       | Czy kontakt ma przypisaną firmę (true/false)                         |
    */
    
    // Inicjalizuje zmienne do przechowywania wyników scoringu
    result = Map();
    ContactScoreDetale = 0;
    ContactWypelnionePola = List();
    ContactPowiazania = List();
    ContactScorePowiazania = 0;
    ContactScorePowiazaniaRekordyModulow = 0;
    ContactHasAccount = false;
    
    try
    {
        info "=== START: Scoring kontaktu dla ID: " + recordId + " ===";
        
        // Pobiera dane kontaktu z CRM
        info "Pobieranie danych kontaktu...";
        contact = zoho.crm.getRecordById("Contacts", recordId);
        if(contact == null)
        {
            info "BŁĄD: Nie znaleziono kontaktu o ID: " + recordId;
            result.put("error", "Nie znaleziono rekordu kontaktu o ID: " + recordId);
            result.put("OverallScore", 0);
            return result.toString();
        }
        info "Znaleziono kontakt: " + contact.get("First_Name") + " " + contact.get("Last_Name");

        // Definiuje listę ważnych pól kontaktu, które będą sprawdzane
        // Każde pole ma swoją nazwę systemową (name) i etykietę (label)
        importantFields = List();
        mp = Map();
        mp.put("name","First_Name");
        mp.put("label","Imię");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Last_Name");
        mp.put("label","Nazwisko");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Stanowisko");
        mp.put("label","Stanowisko");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Title");
        mp.put("label","Tytuł");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Email");
        mp.put("label","Email 1");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Secondary_Email");
        mp.put("label","Email 2");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Email_3");
        mp.put("label","Email 3");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Home_Phone");
        mp.put("label","Telefon komórkowy 1");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Mobile");
        mp.put("label","Telefon komórkowy 2");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Telefon_komorkowy_3");
        mp.put("label","Telefon komórkowy 3");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Phone");
        mp.put("label","Telefon stacjonarny 1");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Other_Phone");
        mp.put("label","Telefon stacjonarny 2");
        importantFields.add(mp);
        
        mp = Map();
        mp.put("name","Telefon_stacjonarny_3");
        mp.put("label","Telefon stacjonarny 3");
        importantFields.add(mp);

        mp = Map();
        mp.put("name","Kontakty_wplyw_na_zakupy");
        mp.put("label","Wpływ na zakupy");
        importantFields.add(mp);

        // Analizuje wypełnienie ważnych pól kontaktu
        // Każde wypełnione pole zwiększa scoring o 1 punkt
        info "Rozpoczynam analizę wypełnionych pól...";
        for each field in importantFields
        {
            try
            {
                fieldValue = contact.get(field.get("name"));
                if(fieldValue != null && fieldValue != "")
                {
                    ContactScoreDetale = ContactScoreDetale + 1;
                    ContactWypelnionePola.add(field.get("label"));
                    info "Znaleziono wypełnione pole: " + field.get("label") + " = " + fieldValue;
                }
            }
            catch(e)
            {
                info "Błąd podczas analizy pola " + field.get("name") + ": " + e;
            }
        }
        info "Zakończono analizę pól. Wypełnione pola: " + ContactScoreDetale;

        // Sprawdza czy kontakt ma przypisaną firmę
        // Przypisana firma zwiększa scoring o 1 punkt
        try
        {
            accountMap = contact.get("Account_Name");
            if(accountMap != null && accountMap.get("id") != null)
            {
                ContactHasAccount = true;
                accountId = accountMap.get("id");
                info "Kontakt ma przypisaną firmę. AccountId: " + accountId;
                ContactScoreDetale = ContactScoreDetale + 1;
                ContactWypelnionePola.add("Firma (Account_Name)");
            }
            else
            {
                info "Kontakt nie ma przypisanej firmy (AccountId: brak)";
            }
        }
        catch(e)
        {
            info "Błąd podczas sprawdzania przypisanej firmy: " + e;
        }

        // Sprawdza czy kontakt ma zapisany adres z firmy
        // Wypełniony adres zwiększa scoring o 1 punkt
        try
        {
            if(contact.get("Adres_zapisany_z_rodzajem_z_firmy") != null && contact.get("Adres_zapisany_z_rodzajem_z_firmy") != "")
            {
                ContactScoreDetale = ContactScoreDetale + 1;
                ContactWypelnionePola.add("Adres zapisany z rodzajem z firmy");
                info "Dodano punkt za wypełnione pole Adres_zapisany_z_rodzajem_z_firmy";
            }
        }
        catch(e)
        {
            info "Błąd podczas sprawdzania pola Adres_zapisany_z_rodzajem_z_firmy: " + e;
        }

        // Zapisuje wyniki analizy pól w mapie wynikowej
        result.put("ContactScoreDetale", ContactScoreDetale);
        result.put("ContactWypelnionePola", ContactWypelnionePola);

        // Sprawdza powiązania kontaktu z innymi modułami
        info "Rozpoczynam sprawdzanie powiązań z modułami...";
        
        // Lista modułów do sprawdzenia powiązań
        relatedModules = List();
        relatedModules.add("Deals");
        relatedModules.add("Notes");
        relatedModules.add("Tasks");
        relatedModules.add("Calls");
        relatedModules.add("Events");
        relatedModules.add("Campaigns");
        
        // Sprawdza powiązania ze standardowymi modułami
        // Każdy moduł z powiązaniami zwiększa scoring o 1 punkt
        // Dodatkowo zlicza wszystkie powiązane rekordy
        for each module in relatedModules
        {
            try
            {
                info "Sprawdzam powiązania z modułem: " + module;
                relatedRecords = zoho.crm.getRelatedRecords(module, "Contacts", recordId);
                if(relatedRecords != null && relatedRecords.size() > 0)
                {
                    ContactScorePowiazania = ContactScorePowiazania + 1;
                    ContactScorePowiazaniaRekordyModulow = ContactScorePowiazaniaRekordyModulow + relatedRecords.size();
                    ContactPowiazania.add(module);
                    info "Znaleziono " + relatedRecords.size() + " powiązanych rekordów w module " + module;
                }
                else
                {
                    info "Brak powiązanych rekordów w module " + module;
                }
            }
            catch(e)
            {
                info "Błąd podczas sprawdzania powiązań z modułem " + module + ": " + e;
            }
        }

        // Specjalne sprawdzenie powiązań z modułem Leads
        // Sprawdza pole Kontakt_w_bazie w Leads
        try
        {
            info "Sprawdzam powiązania z Leads (pole Kontakt_w_bazie)...";
            searchLeads = zoho.crm.searchRecords("Leads", "(Kontakt_w_bazie:equals:" + recordId + ")");
            if(searchLeads != null && searchLeads.size() > 0)
            {
                ContactScorePowiazania = ContactScorePowiazania + 1;
                ContactPowiazania.add("Leads");
                info "Znaleziono " + searchLeads.size() + " powiązanych Leadów";
            }
            else
            {
                info "Brak powiązanych Leadów";
            }
        }
        catch(e)
        {
            info "Błąd podczas sprawdzania powiązań z Leads: " + e;
        }

        // Specjalne sprawdzenie powiązań z modułem Marketing_Leads
        // Sprawdza pole Kontakt_w_bazie w Marketing_Leads
        try
        {
            info "Sprawdzam powiązania z Marketing_Leads (pole Kontakt_w_bazie)...";
            searchMarketingLeads = zoho.crm.searchRecords("Marketing_Leads", "(Kontakt_w_bazie:equals:" + recordId + ")");
            if(searchMarketingLeads != null && searchMarketingLeads.size() > 0)
            {
                ContactScorePowiazania = ContactScorePowiazania + 1;
                ContactPowiazania.add("Marketing_Leads");
                info "Znaleziono " + searchMarketingLeads.size() + " powiązanych rekordów w Marketing_Leads";
            }
            else
            {
                info "Brak powiązanych rekordów w Marketing_Leads";
            }
        }
        catch(e)
        {
            info "Błąd podczas sprawdzania powiązań z Marketing_Leads: " + e;
        }

        // Specjalne sprawdzenie powiązań z modułem EDU_Leads
        // Sprawdza pole Kontakt_w_bazie w EDU_Leads
        try
        {
            info "Sprawdzam powiązania z EDU_Leads (pole Kontakt_w_bazie)...";
            searchEDULeads = zoho.crm.searchRecords("EDU_Leads", "(Kontakt_w_bazie:equals:" + recordId + ")");
            if(searchEDULeads != null && searchEDULeads.size() > 0)
            {
                ContactScorePowiazania = ContactScorePowiazania + 1;
                ContactPowiazania.add("EDU_Leads");
                info "Znaleziono " + searchEDULeads.size() + " powiązanych rekordów w EDU_Leads";
            }
            else
            {
                info "Brak powiązanych rekordów w EDU_Leads";
            }
        }
        catch(e)
        {
            info "Błąd podczas sprawdzania powiązań z EDU_Leads: " + e;
        }
    }
    catch(e)
    {
        // Obsługa błędów globalnych
        info "Globalny błąd podczas wykonywania funkcji calculateContactScore: " + e;
        result.put("error", "Wystąpił błąd podczas obliczania scoringu: " + e);
        result.put("OverallScore", 0);
        return result.toString();
    }

    // Zapisuje wyniki analizy powiązań w mapie wynikowej
    result.put("ContactScorePowiazania", ContactScorePowiazania);
    result.put("ContactPowiazania", ContactPowiazania);
    result.put("ContactScorePowiazaniaRekordyModulow", ContactScorePowiazaniaRekordyModulow);
    result.put("ContactHasAccount", ContactHasAccount);

    // Generuje podsumowanie scoringu
    info "=== PODSUMOWANIE SCORINGU ===";
    info "1. Wypełnione pola (" + ContactScoreDetale + "): " + ContactWypelnionePola.toString();
    info "2. Powiązane moduły (" + ContactScorePowiazania + "): " + ContactPowiazania.toString();
    info "3. Łączna liczba powiązanych rekordów: " + ContactScorePowiazaniaRekordyModulow;
    info "4. Czy kontakt ma przypisaną firmę: " + if(ContactHasAccount, "TAK", "NIE");
    
    // Oblicza końcowy scoring kontaktu
    overallScore = 0;
    
    // Dodaje punkty za wypełnione pola (waga: 1)
    overallScore = overallScore + ContactScoreDetale;
    
    // Dodaje punkty za powiązane moduły (waga: 1)
    overallScore = overallScore + ContactScorePowiazania;
    
    // Dodaje punkty za liczbę powiązanych rekordów (waga: 1)
    overallScore = overallScore + ContactScorePowiazaniaRekordyModulow;
    
    // Dodaje bonus za przypisaną firmę (3 punkty)
    if(ContactHasAccount)
    {
        overallScore = overallScore + 3;
    }
    
    // Zapisuje końcowy scoring w mapie wynikowej
    result.put("OverallScore", overallScore);
    info "5. Całkowity scoring: " + overallScore;
    info "=== KONIEC SCORINGU ===";

    return result.toString();
} 