string standalone.CalculateAccountScore(String recordId)
{
    info "=== START: Scoring firmy dla ID: " + recordId + " ===";

    // Pobranie rekordu firmy
    info "Pobieranie danych firmy...";
    account = zoho.crm.getRecordById("Accounts", recordId);
    if(account == null)
    {
        info "BŁĄD: Nie znaleziono firmy o ID: " + recordId;
        return "Nie znaleziono rekordu firmy o ID: " + recordId;
    }
    info "Znaleziono firmę: " + account.get("Account_Name");

    // Definicja ważnych pól
    importantFields = List();
    mp = Map();

    // Podstawowe dane identyfikacyjne
    for each field in {"Account_Name", "Adres_w_rekordzie", "Nazwa_zwyczajowa", "Nazwa_handlowa_szyld", "Firma_NIP", "Firma_REGON", "Firma_KRS", "Status_REGON"}
    {
        mp = Map();
        mp.put("name", field);
        mp.put("label", field);
        importantFields.add(mp);
    }

    // Dane adresowe siedziby
    for each field in {"Billing_Street", "Billing_Code", "Billing_City", "Billing_Gmina", "Billing_Powiat", "Billing_State", "Billing_Country"}
    {
        mp = Map();
        mp.put("name", field);
        mp.put("label", field + " (siedziba)");
        importantFields.add(mp);
    }

    // Dane adresowe filii
    for each field in {"Shipping_Street", "Shipping_Code", "Shipping_City", "Shipping_Gmina", "Shipping_Powiat", "Shipping_State", "Shipping_Country"}
    {
        mp = Map();
        mp.put("name", field);
        mp.put("label", field + " (filia)");
        importantFields.add(mp);
    }

    // Telefony komórkowe i zakresy
    for each field in {
        {"Mobile_phone_1", "Telefon komórkowy 1"},
        {"Medical_service_mobile_phone_1", "Zakres usług TKom1"},
        {"Mobile_phone_2", "Telefon komórkowy 2"},
        {"Medical_service_mobile_phone_2", "Zakres usług TKom2"},
        {"Mobile_phone_3", "Telefon komórkowy 3"},
        {"Medical_service_mobile_phone_3", "Zakres usług TKom3"}
    }
    {
        mp = Map();
        mp.put("name", field.get(0));
        mp.put("label", field.get(1));
        importantFields.add(mp);
    }

    // Telefony stacjonarne i zakresy
    for each field in {
        {"Phone", "Telefon stacjonarny 1"},
        {"Medical_service_phone_1", "Zakres usług TStac1"},
        {"Phone_2", "Telefon stacjonarny 2"},
        {"Medical_service_phone_2", "Zakres usług TStac2"},
        {"Phone_3", "Telefon stacjonarny 3"},
        {"Medical_service_phone_3", "Zakres usług TStac3"}
    }
    {
        mp = Map();
        mp.put("name", field.get(0));
        mp.put("label", field.get(1));
        importantFields.add(mp);
    }

    // E-maile i zakresy
    for each field in {
        {"Firma_EMAIL1", "Email 1"},
        {"Medical_service_email_1", "Zakres usług Email1"},
        {"Firma_EMAIL2", "Email 2"},
        {"Medical_service_email_2", "Zakres usług Email2"},
        {"Firma_EMAIL3", "Email 3"},
        {"Medical_service_email_3", "Zakres usług Email3"}
    }
    {
        mp = Map();
        mp.put("name", field.get(0));
        mp.put("label", field.get(1));
        importantFields.add(mp);
    }

    // Internet
    mp = Map();
    mp.put("name", "Website");
    mp.put("label", "Strona internetowa");
    importantFields.add(mp);

    // Relacje
    mp = Map();
    mp.put("name", "Parent_Account");
    mp.put("label", "Firma nadrzędna");
    importantFields.add(mp);

    // Grupy
    for each field in {"GROUP_1", "GROUP_2", "GROUP_3"}
    {
        mp = Map();
        mp.put("name", field);
        mp.put("label", field);
        importantFields.add(mp);
    }

    // Inicjalizacja scoringu
    info "Rozpoczynam analizę wypełnionych pól...";
    AccountScoreDetale = 0;
    AccountWypelnionePola = List();

    // Dodajemy inicjalizację tych zmiennych TUTAJ
    AccountScorePowiazaniaModuly = 0;
    AccountScorePowiazaniaRekordyModulow = 0;

    adresTyp = account.get("Adres_w_rekordzie");

    for each field in importantFields
    {
        fieldName = field.get("name");
        fieldLabel = field.get("label");
        fieldValue = account.get(fieldName);

        // Pomijanie adresu siedziby jeśli nie dotyczy
        if(fieldName.startsWith("Billing_"))
        {
            if(adresTyp == "Siedziba" || adresTyp == "Siedziba i Filia")
            {
                // OK – zliczamy
            }
            else
            {
                info "Pomijam pole " + fieldLabel + " – Adres_w_rekordzie nie zawiera siedziby.";
                continue;
            }
        }

        // Pomijanie adresu filii jeśli nie dotyczy
        if(fieldName.startsWith("Shipping_"))
        {
            if(adresTyp == "Filia")
            {
                // OK – zliczamy
            }
            else
            {
                info "Pomijam pole " + fieldLabel + " – Adres_w_rekordzie nie zawiera filii.";
                continue;
            }
        }

        // Sprawdzenie, czy to pole zakresu usług i czy ma odpowiadające pole główne
        if(
            (fieldName == "Medical_service_mobile_phone_1" && (account.get("Mobile_phone_1") == null || account.get("Mobile_phone_1") == "")) ||
            (fieldName == "Medical_service_mobile_phone_2" && (account.get("Mobile_phone_2") == null || account.get("Mobile_phone_2") == "")) ||
            (fieldName == "Medical_service_mobile_phone_3" && (account.get("Mobile_phone_3") == null || account.get("Mobile_phone_3") == "")) ||
            (fieldName == "Medical_service_phone_1" && (account.get("Phone") == null || account.get("Phone") == "")) ||
            (fieldName == "Medical_service_phone_2" && (account.get("Phone_2") == null || account.get("Phone_2") == "")) ||
            (fieldName == "Medical_service_phone_3" && (account.get("Phone_3") == null || account.get("Phone_3") == "")) ||
            (fieldName == "Medical_service_email_1" && (account.get("Firma_EMAIL1") == null || account.get("Firma_EMAIL1") == "")) ||
            (fieldName == "Medical_service_email_2" && (account.get("Firma_EMAIL2") == null || account.get("Firma_EMAIL2") == "")) ||
            (fieldName == "Medical_service_email_3" && (account.get("Firma_EMAIL3") == null || account.get("Firma_EMAIL3") == ""))
        )
        {
            info "Pomijam pole zakresu usług " + fieldLabel + " – brak odpowiadającego pola głównego.";
            continue;
        }

        if(fieldName.startsWith("Obszar_placowki"))
        {
            info "Pomijam pole " + fieldLabel + " – obszar placówki nie jest brany pod uwagę w scoringu.";
            continue;
        }

        if(
            fieldName == "Medical_service_email_1" ||
            fieldName == "Medical_service_email_2" ||
            fieldName == "Medical_service_email_3" ||
            fieldName == "Medical_service_mobile_phone_1" ||
            fieldName == "Medical_service_mobile_phone_2" ||
            fieldName == "Medical_service_mobile_phone_3" ||
            fieldName == "Medical_service_phone_1" ||
            fieldName == "Medical_service_phone_2" ||
            fieldName == "Medical_service_phone_3"
        )
        {
            info "Pomijam pole " + fieldLabel + " – obszar placówki nie jest brany pod uwagę w scoringu.";
            continue;
        }

        if(fieldValue != null && fieldValue != "")
        {
            AccountScoreDetale = AccountScoreDetale + 1;
            AccountWypelnionePola.add(fieldLabel);
            info "Znaleziono wypełnione pole: " + fieldLabel + " = " + fieldValue;
        }
    }

    // Przygotowanie wyniku
    result = Map();
    result.put("AccountScoreDetale", AccountScoreDetale);
    result.put("AccountWypelnionePola", AccountWypelnionePola);
    result.put("AccountScorePowiazaniaModuly", AccountScorePowiazaniaModuly);
    result.put("AccountScorePowiazaniaRekordyModulow", AccountScorePowiazaniaRekordyModulow);

    // Analiza powiązań z modułami
    info "Rozpoczynam analizę powiązań z modułami...";
    AccountPowiazania = List();

    // Leads
    info "Sprawdzam powiązania z Leads (pole Firma_w_bazie)...";
    leads = zoho.crm.searchRecords("Leads", "(Firma_w_bazie:equals:" + recordId.toLong() + ")");
    if(leads != null && leads.size() > 0)
    {
        AccountScorePowiazaniaModuly = AccountScorePowiazaniaModuly + 1;
        AccountPowiazania.add("Leads");
        AccountScorePowiazaniaRekordyModulow = AccountScorePowiazaniaRekordyModulow + leads.size();
        info "Znaleziono " + leads.size() + " powiązanych Leadów";
    }
    else
    {
        info "Brak powiązanych Leadów";
    }

    // Marketing_Leads
    info "Sprawdzam powiązania z Marketing_Leads (pole Firma_w_bazie)...";
    marketingLeads = zoho.crm.searchRecords("Marketing_Leads", "(Firma_w_bazie:equals:" + recordId.toLong() + ")");
    if(marketingLeads != null && marketingLeads.size() > 0)
    {
        AccountScorePowiazaniaModuly = AccountScorePowiazaniaModuly + 1;
        AccountPowiazania.add("Marketing_Leads");
        AccountScorePowiazaniaRekordyModulow = AccountScorePowiazaniaRekordyModulow + marketingLeads.size();
        info "Znaleziono " + marketingLeads.size() + " powiązanych rekordów w Marketing_Leads";
    }
    else
    {
        info "Brak powiązanych rekordów w Marketing_Leads";
    }

    // EDU_Leads
    info "Sprawdzam powiązania z EDU_Leads (pole Firma_w_bazie)...";
    eduLeads = zoho.crm.searchRecords("EDU_Leads", "(Firma_w_bazie:equals:" + recordId.toLong() + ")");
    if(eduLeads != null && eduLeads.size() > 0)
    {
        AccountScorePowiazaniaModuly = AccountScorePowiazaniaModuly + 1;
        AccountPowiazania.add("EDU_Leads");
        AccountScorePowiazaniaRekordyModulow = AccountScorePowiazaniaRekordyModulow + eduLeads.size();
        info "Znaleziono " + eduLeads.size() + " powiązanych rekordów w EDU_Leads";
    }
    else
    {
        info "Brak powiązanych rekordów w EDU_Leads";
    }

    // Kontakty powiązane z firmą
    info "Sprawdzam powiązane kontakty (pole Account_Name)...";
    contacts = zoho.crm.searchRecords("Contacts", "(Account_Name:equals:" + recordId.toLong() + ")");
    if(contacts != null && contacts.size() > 0)
    {
        AccountScorePowiazaniaModuly = AccountScorePowiazaniaModuly + 1;
        AccountPowiazania.add("Contacts");
        AccountScorePowiazaniaRekordyModulow = AccountScorePowiazaniaRekordyModulow + contacts.size();
        info "Znaleziono " + contacts.size() + " powiązanych kontaktów";
    }
    else
    {
        info "Brak powiązanych kontaktów";
    }

    // Moduły standardowe powiązane z kontem
    relatedModules = List();
    relatedModules.add("Deals");
    relatedModules.add("Notes");
    relatedModules.add("Tasks");
    relatedModules.add("Calls");
    relatedModules.add("Events");

    for each module in relatedModules
    {
        info "Sprawdzam powiązania z modułem: " + module;
        relatedRecords = zoho.crm.getRelatedRecords(module, "Accounts", recordId);
        if(relatedRecords != null && relatedRecords.size() > 0)
        {
            AccountScorePowiazaniaModuly = AccountScorePowiazaniaModuly + 1;
            AccountScorePowiazaniaRekordyModulow = AccountScorePowiazaniaRekordyModulow + relatedRecords.size();
            AccountPowiazania.add(module);
            info "Znaleziono " + relatedRecords.size() + " powiązanych rekordów w module " + module;
        }
        else
        {
            info "Brak powiązanych rekordów w module " + module;
        }
    }

    // Sprawdzenie, czy firma jest rodzicem dla innych firm
    info "Sprawdzam, czy firma jest nadrzędna dla innych firm...";
    childAccounts = zoho.crm.searchRecords("Accounts", "(Parent_Account:equals:" + recordId.toLong() + ")");
    if(childAccounts != null && childAccounts.size() > 0)
    {
        AccountScorePowiazaniaModuly = AccountScorePowiazaniaModuly + 1;
        AccountPowiazania.add("Child_Accounts");
        AccountScorePowiazaniaRekordyModulow = AccountScorePowiazaniaRekordyModulow + childAccounts.size();
        info "Znaleziono " + childAccounts.size() + " powiązanych firm potomnych";
    }
    else
    {
        info "Brak firm potomnych";
    }

    result.put("AccountScorePowiazaniaModuly", AccountScorePowiazaniaModuly);
    result.put("AccountScorePowiazaniaRekordyModulow", AccountScorePowiazaniaRekordyModulow);
    result.put("AccountPowiazania", AccountPowiazania);

    // Scoring powiązań z innymi firmami
    info "Analiza powiązań z innymi firmami (rodzic/potomkowie)...";
    AccountScoreFirmyPowiazane = 0;
    AccountFirmyPowiazane = List();

    // Sprawdzenie, czy firma ma rodzica
    parentId = account.get("Parent_Account");
    if(parentId != null && parentId != "")
    {
        AccountScoreFirmyPowiazane = AccountScoreFirmyPowiazane + 1;
        AccountFirmyPowiazane.add("Rodzic");
        info "Firma ma firmę nadrzędną (Parent_Account)";
    }
    else
    {
        info "Brak firmy nadrzędnej";
    }

    // Sprawdzenie, czy firma ma potomków
    childAccounts = zoho.crm.searchRecords("Accounts", "(Parent_Account:equals:" + recordId.toLong() + ")");
    if(childAccounts != null && childAccounts.size() > 0)
    {
        AccountScoreFirmyPowiazane = AccountScoreFirmyPowiazane + childAccounts.size();
        AccountFirmyPowiazane.add("Potomkowie");
        info "Znaleziono " + childAccounts.size() + " firm potomnych";
    }
    else
    {
        info "Brak firm potomnych";
    }

    result.put("AccountScoreFirmyPowiazane", AccountScoreFirmyPowiazane);
    result.put("AccountFirmyPowiazane", AccountFirmyPowiazane);

    // Sprawdzenie powiązań w module Klienci (Firma_ASU, Firma_Platnik)
    info "Sprawdzam powiązania w module Klienci (pola Firma_ASU, Firma_Platnik)...";
    klientAsu = zoho.crm.searchRecords("Klienci", "(Firma_ASU:equals:" + recordId.toLong() + ")");
    klientPlatnik = zoho.crm.searchRecords("Klienci", "(Firma_Platnik:equals:" + recordId.toLong() + ")");

    klientIds = List();

    if(klientAsu != null)
    {
        for each k in klientAsu
        {
            klientIds.add(k.get("id"));
        }
    }

    if(klientPlatnik != null)
    {
        for each k in klientPlatnik
        {
            klientIds.add(k.get("id"));
        }
    }

    // Usunięcie duplikatów ręcznie
    unikalneKlientIds = List();
    unikalneMap = Map();

    for each id in klientIds
    {
        if(unikalneMap.get(id.toString()) == null)
        {
            unikalneMap.put(id.toString(), true);
            unikalneKlientIds.add(id);
        }
    }

    liczbaPowiazanKlienci = 0;
    if(klientAsu != null)
    {
        liczbaPowiazanKlienci = liczbaPowiazanKlienci + klientAsu.size();
    }
    if(klientPlatnik != null)
    {
        liczbaPowiazanKlienci = liczbaPowiazanKlienci + klientPlatnik.size();
    }

    result.put("AccountScoreKlienci", liczbaPowiazanKlienci);
    info "7. Ilość powiązań w module Klienci (ASU/Platnik): " + liczbaPowiazanKlienci;

    info "=== PODSUMOWANIE SCORINGU FIRMY ===";
    info "1. Ilość wypełnionych pól: " + AccountScoreDetale;
    info "2. Wypełnione pola: " + AccountWypelnionePola.toString();
    info "3. Ilość powiązanych modułów: " + AccountScorePowiazaniaModuly;
    info "4. Powiązane moduły: " + AccountPowiazania.toString();
    info "5. Ilość powiązań z innymi firmami: " + AccountScoreFirmyPowiazane;
    info "6. Typy powiązań: " + AccountFirmyPowiazane.toString();
    info "7. Ilość powiązań w module Klienci (ASU/Platnik): " + liczbaPowiazanKlienci;
    info "3. Liczba modułów z powiązaniami: " + AccountScorePowiazaniaModuly;
    info "4. Liczba rekordów powiązanych w modułach: " + AccountScorePowiazaniaRekordyModulow;
    info "5. Liczba powiązanych firm (rodzic/potomkowie): " + AccountScoreFirmyPowiazane;
    info "6. Liczba powiązań w module Klienci (ASU/Platnik): " + liczbaPowiazanKlienci;
    info "=== KONIEC SCORINGU FIRMY ===";

    info "=== WYNIK SCORINGU (czytelny) ===";
    for each entry in result.toList()
    {
        info entry.get("key") + ": " + entry.get("value");
    }
    info "=== KONIEC WYNIKU ===";

    return result.toString();
} 