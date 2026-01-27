string standalone.ContactNewDedup(String recordid)
{
    try {
        // Pobierz dane kontaktu na podstawie przekazanego recordid
        contact = zoho.crm.getRecordById("Contacts", recordid);
        info "Pobrano dane kontaktu dla ID: " + recordid;
        if (contact == null)
        {
            return "Nie znaleziono kontaktu o podanym ID.";
        }

        // Pobierz adresy e-mail kontaktu
        email1 = contact.get("Email");
        email2 = contact.get("Secondary_Email");
        email3 = contact.get("Email_3");
        info "Adresy e-mail: " + email1 + ", " + email2 + ", " + email3;

        // Pobierz wartości RODO dla każdego pola e-mail
        rodoEmail1 = contact.get("EMail1_RODO_wyrazona_niezgoda");
        rodoEmail2 = contact.get("EMail2_RODO_wyrazona_niezgoda");
        rodoEmail3 = contact.get("EMail3_RODO_wyrazona_niezgoda");
        info "Wartości RODO: " + rodoEmail1 + ", " + rodoEmail2 + ", " + rodoEmail3;

        // Pobierz pole Email_marketingowy_odsubskrybuj
        emailMarketingUnsub = contact.get("Email_marketingowy_odsubskrybuj");
        info "Email_marketingowy_odsubskrybuj: " + emailMarketingUnsub;

        // Lista do przechowywania wyników
        result = list();

        // Sprawdź, czy w rekordzie jest tylko jeden adres e-mail
        emailCount = 0;
        if (email1 != null && !email1.isEmpty()) { emailCount = emailCount + 1; }
        if (email2 != null && !email2.isEmpty()) { emailCount = emailCount + 1; }
        if (email3 != null && !email3.isEmpty()) { emailCount = emailCount + 1; }
        info "Liczba adresów e-mail: " + emailCount;

        // Jeśli Email_marketingowy_odsubskrybuj jest true i jest tylko jeden adres e-mail
        if (emailMarketingUnsub == true && emailCount == 1)
        {
            updateMap = Map();
            if (email1 != null && !email1.isEmpty())
            {
                updateMap.put("EMail1_RODO_wyrazona_niezgoda", emailMarketingUnsub);
            }
            else if (email2 != null && !email2.isEmpty())
            {
                updateMap.put("EMail2_RODO_wyrazona_niezgoda", emailMarketingUnsub);
            }
            else if (email3 != null && !email3.isEmpty())
            {
                updateMap.put("EMail3_RODO_wyrazona_niezgoda", emailMarketingUnsub);
            }

            // Zaktualizuj rekord kontaktu
            updateResponse = zoho.crm.updateRecord("Contacts", recordid, updateMap);
            if (updateResponse != null && updateResponse.get("code") == "SUCCESS")
            {
                result.add("Pole Email_marketingowy_odsubskrybuj zostało przepisane do odpowiedniego pola RODO.");
                info "Zaktualizowano pole RODO na podstawie Email_marketingowy_odsubskrybuj.";
            }
            else
            {
                result.add("Nie udało się zaktualizować pola RODO na podstawie Email_marketingowy_odsubskrybuj.");
                info "Błąd aktualizacji pola RODO.";
            }

            // Pobierz ponownie rekord po aktualizacji
            contact = zoho.crm.getRecordById("Contacts", recordid);
            info "Pobrano ponownie dane kontaktu po aktualizacji.";
        }

        // Pobierz adresy e-mail kontaktu (ponownie, po ewentualnej aktualizacji)
        email1 = contact.get("Email");
        email2 = contact.get("Secondary_Email");
        email3 = contact.get("Email_3");

        // Pobierz wartości RODO dla każdego pola e-mail
        rodoEmail1 = contact.get("EMail1_RODO_wyrazona_niezgoda");
        rodoEmail2 = contact.get("EMail2_RODO_wyrazona_niezgoda");
        rodoEmail3 = contact.get("EMail3_RODO_wyrazona_niezgoda");

        // Obsługa duplikatów dla każdego pola email
        if (email1 != null && !email1.isEmpty())
        {
            info "Wywołanie HandleDuplicates dla email1: " + email1 + " z RODO: " + rodoEmail1;
            handleResult = standalone.HandleDuplicates(email1, rodoEmail1);
            if (handleResult != null)
            {
                result.add(handleResult);
                info "Obsłużono duplikaty dla email1: " + email1;
            }
        }
        if (email2 != null && !email2.isEmpty())
        {
            info "Wywołanie HandleDuplicates dla email2: " + email2 + " z RODO: " + rodoEmail2;
            handleResult = standalone.HandleDuplicates(email2, rodoEmail2);
            if (handleResult != null)
            {
                result.add(handleResult);
                info "Obsłużono duplikaty dla email2: " + email2;
            }
        }
        if (email3 != null && !email3.isEmpty())
        {
            info "Wywołanie HandleDuplicates dla email3: " + email3 + " z RODO: " + rodoEmail3;
            handleResult = standalone.HandleDuplicates(email3, rodoEmail3);
            if (handleResult != null)
            {
                result.add(handleResult);
                info "Obsłużono duplikaty dla email3: " + email3;
            }
        }

        // Nowy fragment kodu
        if (!result.isEmpty())
        {
            // Usunięcie emaila i statusu RODO z rekordu początkowego
            updateClearMap = Map();
            if (email1 != null && !email1.isEmpty())
            {
                updateClearMap.put("Email", null);
                updateClearMap.put("EMail1_RODO_wyrazona_niezgoda", null);
            }
            if (email2 != null && !email2.isEmpty())
            {
                updateClearMap.put("Secondary_Email", null);
                updateClearMap.put("EMail2_RODO_wyrazona_niezgoda", null);
            }
            if (email3 != null && !email3.isEmpty())
            {
                updateClearMap.put("Email_3", null);
                updateClearMap.put("EMail3_RODO_wyrazona_niezgoda", null);
            }
            zoho.crm.updateRecord("Contacts", recordid, updateClearMap);
            info "Usunięto email i status RODO z rekordu początkowego.";

            // Zbieramy listę ID kontaktów z emailem
            info "Wywołanie ContactDup dla email1: " + email1;
            duplicateIds = standalone.ContactDup("(Email:equals:" + email1 + ")");
            duplicateIdsList = list();
            if (duplicateIds != "")
            {
                // Ręczne dzielenie stringa na listę
                for each id in duplicateIds.getSuffix(", ")
                {
                    duplicateIdsList.add(id.trim());
                }
            }
            info "Zebrano listę ID duplikatów: " + duplicateIdsList.toString();

            // Poprawka: konwersja listy na mapę zgodnie z oczekiwaniem AnalyzeAndMergeContact
            duplicateIdsMap = Map();
            for each dupId in duplicateIdsList
            {
                duplicateIdsMap.put(dupId, dupId);
            }
            info "Stworzono mapę duplikatów: " + duplicateIdsMap.toString();

            // Wywołujemy poprawioną funkcję do analizy podobieństwa i ewentualnego scalenia
            info "Wywołanie AnalyzeAndMergeContact dla recordid: " + recordid + " z mapą duplikatów.";
            mergeResult = standalone.AnalyzeAndMergeContact(recordid, duplicateIdsMap);
            result.add(mergeResult);
            info "Wynik scalania: " + mergeResult;

            // Dodajemy podsumowanie scalania
            if (mergeResult.contains("Scalono nowy kontakt"))
            {
                result.add("Podsumowanie: " + mergeResult);
            }
            else
            {
                result.add("Podsumowanie: Nie wykonano scalania kontaktów.");
            }
        }

        // Zwróć wyniki
        if (result.isEmpty())
        {
            return "Brak duplikatów dla podanego kontaktu.";
        }
        else
        {
            return "Wyniki: " + result.toString("\n");
        }
    } catch (e) {
        return "Błąd podczas przetwarzania kontaktu: " + e.toString();
    }
}