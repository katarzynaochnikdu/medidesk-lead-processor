string standalone.RetrieveAllContactDup(String recordId)
{
    try {
        // Funkcja pomocnicza do sprawdzania poprawności wartości pól
        isValidValue = "value != null && value != \"\" && value.toString().trim() != \"\"";
        
        // Inicjalizacja listy do przechowywania wszystkich znalezionych duplikatów
        allDuplicates = List();
        // Pobranie tokena dostępu do API, aby zmniejszyć ilość generowania tokena
        accessToken = standalone.AccessToken();
        if(accessToken.startsWith("Błąd"))
        {
            info "Błąd podczas pobierania tokena: " + accessToken;
        }
        
        // Pobranie szczegółów rekordu kontaktu na podstawie ID
        contact = zoho.crm.getRecordById("Contacts", recordId);
        info "Pobrane dane kontaktu: " + contact.toString();
        
        if (contact != null) {
            // Definicja ważnych pól
            importantFields = {"First_Name", "Last_Name", "Stanowisko", "Title", "Email", "Secondary_Email", "Email_3", 
                "Home_Phone", "Mobile", "Telefon_komorkowy_3", "Phone", "Other_Phone", "Telefon_stacjonarny_3", "Account_Name"};
            
            // Pobranie wartości dla każdego ważnego pola
            fieldValues = Map();
            for each fieldName in importantFields {
                if (fieldName == "Account_Name") {
                    // Specjalna obsługa dla pola typu lookup
                    accountValue = contact.get(fieldName);
                    if (accountValue != null) {
                        fieldValues.put(fieldName, accountValue.get("name"));
                        info "Account_Name value: " + fieldValues.get(fieldName);
                    } else {
                        fieldValues.put(fieldName, null);
                    }
                } else {
                    // Standardowa obsługa dla pozostałych pól
                    fieldValues.put(fieldName, contact.get(fieldName));
                    info "Pole " + fieldName + ": " + fieldValues.get(fieldName);
                }
            }

            // Lista warunków do sprawdzenia
            conditions = List();
            
            // Definicja pól email i telefonu
            emailFields = {"Email", "Secondary_Email", "Email_3"};
            phoneFields = {"Home_Phone", "Mobile", "Phone", "Other_Phone", "Telefon_komorkowy_3", "Telefon_stacjonarny_3"};
            
            // Warunek 1: Email + imię i nazwisko
            firstName = fieldValues.get("First_Name");
            lastName = fieldValues.get("Last_Name");
            if(firstName != null && firstName != "" && firstName.toString().trim() != "" && 
               lastName != null && lastName != "" && lastName.toString().trim() != "")
            {
                for each emailField in emailFields
                {
                    emailValue = fieldValues.get(emailField);
                    if(emailValue != null && emailValue != "" && emailValue.toString().trim() != "")
                    {
                        emailCondition = "(First_Name:equals:" + firstName + 
                                    ") and (Last_Name:equals:" + lastName +
                                    ") and (" + emailField + ":equals:" + emailValue + ")";
                        conditions.add(emailCondition);
                    }
                }
            }
            
            // Warunek 2: Telefon + imię i nazwisko
            if(firstName != null && firstName != "" && firstName.toString().trim() != "" && 
               lastName != null && lastName != "" && lastName.toString().trim() != "")
            {
                for each phoneField in phoneFields
                {
                    phoneValue = fieldValues.get(phoneField);
                    if(phoneValue != null && phoneValue != "" && phoneValue.toString().trim() != "")
                    {
                        cleanPhone = phoneValue.toString().replaceAll("[^0-9]","");
                        if(cleanPhone != null && cleanPhone != "" && cleanPhone.toString().trim() != "")
                        {
                            phoneCondition = "(First_Name:equals:" + firstName + 
                                           ") and (Last_Name:equals:" + lastName +
                                           ") and (" + phoneField + ":equals:" + cleanPhone + ")";
                            conditions.add(phoneCondition);
                        }
                    }
                }
            }
            
            // CZĘŚĆ 3: Last_Name + Account_Name + (email lub telefon)
            lastName = fieldValues.get("Last_Name");
            accountName = fieldValues.get("Account_Name");
            if(lastName != null && lastName != "" && lastName.toString().trim() != "" && 
               accountName != null && accountName != "" && accountName.toString().trim() != "")
            {
                companyNameCondition = "(Last_Name:equals:" + lastName + 
                                    ") and (Account_Name:equals:" + accountName + ")";
                
                // Warunki dla emaili z nazwą firmy
                for each sourceField in emailFields
                {
                    emailValue = fieldValues.get(sourceField);
                    if(emailValue != null && emailValue != "" && emailValue.toString().trim() != "")
                    {
                        condition = "(" + companyNameCondition + 
                                  ") and (" + sourceField + ":equals:" + emailValue + ")";
                        conditions.add(condition);
                    }
                }
                
                // Warunki dla telefonów z nazwą firmy
                for each sourceField in phoneFields
                {
                    phoneValue = fieldValues.get(sourceField);
                    if(phoneValue != null && phoneValue != "" && phoneValue.toString().trim() != "")
                    {
                        cleanPhone = phoneValue.toString().replaceAll("[^0-9]","");
                        if(cleanPhone != null && cleanPhone != "" && cleanPhone.toString().trim() != "")
                        {
                            condition = companyNameCondition + 
                                      " and (" + sourceField + ":equals:" + cleanPhone + ")";
                            conditions.add(condition);
                        }
                    }
                }
            }
            
            // CZĘŚĆ 4: First_Name + Account_Name + (email lub telefon)
            if(firstName != null && firstName != "" && firstName.toString().trim() != "" && 
               accountName != null && accountName != "" && accountName.toString().trim() != "")
            {
                companyNameConditionFirstName = "(First_Name:equals:" + firstName + 
                                              ") and (Account_Name.name:equals:\"" + accountName + "\")";
                info "Company name condition first name: " + companyNameConditionFirstName;
                
                // Warunki dla emaili z nazwą firmy
                for each sourceField in emailFields
                {
                    emailValue = fieldValues.get(sourceField);
                    if(emailValue != null && emailValue != "" && emailValue.toString().trim() != "")
                    {
                        for each targetField in emailFields
                        {
                            condition = companyNameConditionFirstName + 
                                      " and " + targetField + ":equals:" + emailValue;
                            conditions.add(condition);
                        }
                    }
                }
                
                // Warunki dla telefonów
                for each sourceField in phoneFields
                {
                    phoneValue = fieldValues.get(sourceField);
                    if(phoneValue != null && phoneValue != "" && phoneValue.toString().trim() != "")
                    {
                        phoneClean = standalone.formatPhoneNumber(phoneValue, "clean");
                        if(phoneClean != null && phoneClean != "" && phoneClean.toString().trim() != "")
                        {
                            phoneMobile = standalone.formatPhoneNumber(phoneValue, "mobile");
                            if(phoneMobile != null && phoneMobile != "" && phoneMobile.toString().trim() != "")
                            {
                                for each targetField in phoneFields
                                {
                                    condition = companyNameConditionFirstName + 
                                              " and (" + targetField + ":equals:" + phoneClean + 
                                              " or " + targetField + ":equals:" + phoneMobile + ")";
                                    conditions.add(condition);
                                }
                            }
                        }
                    }
                }
            }
            
            // Dodanie warunku dla First_Name, Last_Name i Account_Name
            if (fieldValues.get("First_Name") != null && fieldValues.get("Last_Name") != null && fieldValues.get("Account_Name") != null) {
                condition = "(First_Name:equals:" + fieldValues.get("First_Name") + 
                          ") and (Last_Name:equals:" + fieldValues.get("Last_Name") + 
                          ") and (Account_Name.name:equals:\"" + fieldValues.get("Account_Name") + "\")";
                conditions.add(condition);
            }
            
            // Przykład sprawdzania dostępności pola przed użyciem w zapytaniu
            if (fieldValues.get("Email") != null) {
                condition = "(Last_Name:equals:" + fieldValues.get("Last_Name") + 
                          ") and (Account_Name:equals:" + fieldValues.get("Account_Name") + 
                          ") and (Email:equals:" + fieldValues.get("Email") + ")";
                conditions.add(condition);
            }
            
            // Warunki dla ContactDup
            contactDupConditions = List();
            
            // Podstawowe warunki dla imienia i nazwiska
            if(firstName != null && firstName != "" && firstName.toString().trim() != "" && 
               lastName != null && lastName != "" && lastName.toString().trim() != "")
            {
                // 1. Warunek: Imię + Nazwisko + Email
                emailValue = fieldValues.get("Email");
                if(emailValue != null && emailValue != "" && emailValue.toString().trim() != "")
                {
                    // Sprawdzamy czy wszystkie pola potrzebne do warunku są wypełnione
                    if(emailValue != null && emailValue != "" && emailValue.toString().trim() != "")
                    {
                        condition = "(First_Name:equals:" + firstName + 
                                  ") and (Last_Name:equals:" + lastName + 
                                  ") and ((Email:equals:" + emailValue + 
                                  ") or (Secondary_Email:equals:" + emailValue + 
                                  ") or (Email_3:equals:" + emailValue + "))";
                        contactDupConditions.add(condition);
                    }
                }
                
                // 2. Warunek: Imię + Nazwisko + Telefon
                homePhone = fieldValues.get("Home_Phone");
                if(homePhone != null && homePhone != "" && homePhone.toString().trim() != "")
                {
                    phoneClean = standalone.formatPhoneNumber(homePhone, "clean");
                    if(phoneClean != null && phoneClean != "" && phoneClean.toString().trim() != "")
                    {
                        condition = "(First_Name:equals:" + firstName + 
                                  ") and (Last_Name:equals:" + lastName + 
                                  ") and ((Home_Phone:equals:" + phoneClean + 
                                  ") or (Mobile:equals:" + phoneClean + 
                                  ") or (Phone:equals:" + phoneClean + 
                                  ") or (Other_Phone:equals:" + phoneClean + "))";
                        contactDupConditions.add(condition);
                    }
                }
                
                // 3. Warunek: Tylko Imię + Nazwisko (jako ostatnia opcja)
                // Ten warunek dodajemy tylko jeśli nie znaleziono duplikatów przez poprzednie warunki
                if(contactDupConditions.size() == 0)
                {
                    condition = "(First_Name:equals:" + firstName + 
                              ") and (Last_Name:equals:" + lastName + ")";
                    contactDupConditions.add(condition);
                }
            }

            // Dodajemy więcej logowania
            info "Liczba warunków do sprawdzenia w ContactDup: " + contactDupConditions.size();
            info "Warunki do sprawdzenia w ContactDup: " + contactDupConditions.toString();
            
            // Iteracja przez warunki i wyszukiwanie duplikatów przez ContactDup
            for each condition in contactDupConditions {
                info "Warunek wysyłany do ContactDup: " + condition;
                duplicates = standalone.ContactDup(condition);
                info "Odpowiedź z ContactDup: " + duplicates;
                if (duplicates.contains("INVALID_QUERY") || duplicates.contains("Error"))
                {
                    info "Pomijam błędne zapytanie ContactDup i kontynuuję sprawdzanie";
                    continue;
                }
                else if(duplicates != "")
                {
                    duplicateIds = duplicates.toList(", ");
                    info "Znalezione duplikaty przez ContactDup: " + duplicateIds;
                    for each id in duplicateIds
                    {
                        allDuplicates.add(id);
                    }
                }
            }

            // Warunki dla API: sprawdzamy wszystkie pola emailowe
            apiConditions = List();
            if (fieldValues.get("Last_Name") != null && fieldValues.get("Account_Name") != null) {
                for each emailField in emailFields {
                    if (fieldValues.get(emailField) != null) {
                        condition = "(Last_Name:equals:" + fieldValues.get("Last_Name") +
                                  ") and (Account_Name:equals:" + fieldValues.get("Account_Name") +
                                  ") and (Email:equals:" + fieldValues.get(emailField) + ")";
                        apiConditions.add(condition);
                    }
                }
            }
            
            // Iteracja przez warunki i wyszukiwanie duplikatów przez API (email)
            for each condition in apiConditions {
                info "Warunek wysyłany do API: " + condition;
                apiResults = standalone.searchContactsByAPI(condition, accessToken);
                info "Odpowiedź z API: " + apiResults;
                if(apiResults.contains("INVALID_QUERY"))
                {
                    info "Pomijam błędne zapytanie i kontynuuję sprawdzanie pozostałych warunków";
                    continue;
                }
                else if(apiResults != "") {
                    duplicateIds = apiResults.toList(",");
                    info "Znalezione duplikaty przez API: " + duplicateIds;
                    for each id in duplicateIds {
                        allDuplicates.add(id);
                    }
                }
            }
            
            // Warunki dla API: wyszukiwanie po numerach telefonów (każdy z każdym, z uwzględnieniem formatowania pól docelowych)
            apiPhoneConditions = List();
            if (fieldValues.get("Last_Name") != null && fieldValues.get("Account_Name") != null) {
                targetPhoneFields = {"Home_Phone", "Mobile", "Telefon_komorkowy_3", "Phone", "Telefon_stacjonarny_3", "Other_Phone"};
                sourcePhoneFields = List();
                // Dodajemy pola źródłowe z list phoneFields
                for each phoneField in phoneFields {
                    if (fieldValues.get(phoneField) != null) {
                        sourcePhoneFields.add(phoneField);
                    }
                }
                // Iterujemy "każdy z każdym"
                for each srcField in sourcePhoneFields {
                    srcValue = fieldValues.get(srcField);
                    phoneClean = standalone.formatPhoneNumber(srcValue, "clean");
                    if(phoneClean != "") {
                        for each tgtField in targetPhoneFields {
                            // Warunek z oczyszczonym formatem (bez spacji, tylko cyfry)
                            condition = "(Last_Name:equals:" + fieldValues.get("Last_Name") +
                                        ") and (Account_Name:equals:" + fieldValues.get("Account_Name") +
                                        ") and (" + tgtField + ":equals:" + phoneClean + ")";
                            apiPhoneConditions.add(condition);
                            // Warunek z oryginalną wartością (może zawierać spacje)
                            condition = "(Last_Name:equals:" + fieldValues.get("Last_Name") +
                                        ") and (Account_Name:equals:" + fieldValues.get("Account_Name") +
                                        ") and (" + tgtField + ":equals:" + srcValue + ")";
                            apiPhoneConditions.add(condition);
                        }
                    }
                }
            }
            
            // Iteracja przez warunki i wyszukiwanie duplikatów przez API dla numerów telefonów
            for each condition in apiPhoneConditions {
                info "Warunek wysyłany do API dla telefonów: " + condition;
                apiResults = standalone.searchContactsByAPI(condition, accessToken);
                if(apiResults != "") {
                    duplicateIds = apiResults.toList(",");
                    for each id in duplicateIds {
                        allDuplicates.add(id);
                    }
                }
            }
            
            // Deduplikacja listy wyników
            uniqueDuplicates = List();
            for each id in allDuplicates {
                if (!uniqueDuplicates.contains(id)) {
                    uniqueDuplicates.add(id);
                }
            }
            
            // Usunięcie rekordu wejściowego z listy duplikatów
            if (uniqueDuplicates.contains(recordId)) {
                info "Usuwanie rekordu wejściowego " + recordId + " z listy duplikatów";
                uniqueDuplicates.removeElement(recordId);
            }
            
            if (uniqueDuplicates.size() > 0) {
                return uniqueDuplicates.toString(", ");
            } else {
                return "Brak duplikatów dla rekordu o ID: " + recordId;
            }
        } else {
            return "Nie znaleziono rekordu o ID: " + recordId;
        }
    } catch (e) {
        return "Błąd podczas wyszukiwania duplikatów: " + e.toString();
    }
}