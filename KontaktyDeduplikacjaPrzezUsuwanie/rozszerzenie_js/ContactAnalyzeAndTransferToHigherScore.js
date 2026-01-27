string standalone.ContactAnalyzeAndTransferToHigherScore(string recordId, map duplicateIdsMap)
{
    // Funkcja analizuje i przenosi dane między duplikatami kontaktów, zostawiając rekord o wyższym scoringu
    info "=== ANALIZA I PRZENOSZENIE KONTAKTU DO REKORDU O WYŻSZYM SCORINGU ===";
    info "ID analizowanego rekordu: " + recordId;
    info "Lista przekazanych duplikatów: " + duplicateIdsMap.toString();
    
    // 1. Pobiera rekord wejściowy do analizy
    contact = zoho.crm.getRecordById("Contacts", recordId);
    if(contact == null)
    {
        return "❌ Błąd: Kontakt o ID " + recordId + " nie istnieje";
    }
    info "Pobrano kontakt wejściowy: " + contact.toString();
    
    // Lista pól które są analizowane podczas przenoszenia danych
    importantFields = {"First_Name","Last_Name","Stanowisko","Title","Email","Secondary_Email","Email_3",
                        "Home_Phone","Mobile","Telefon_komorkowy_3","Phone","Other_Phone","Telefon_stacjonarny_3","Kontakty_wplyw_na_zakupy"};
    
    // 2. Oblicza scoring (punktację) rekordu wejściowego na podstawie kompletności danych
    // Scoring określa jak kompletne są dane w rekordzie
    scoringResultStr = standalone.calculateContactScore(recordId);
    incomingScore = 0;

    if(scoringResultStr != null && scoringResultStr != "")
    {
        try
        {
            scoringMap = scoringResultStr.toMap();
            if(scoringMap != null && scoringMap.containsKey("OverallScore"))
            {
                incomingScore = scoringMap.get("OverallScore");
            }
            else
            {
                info "Brak klucza 'OverallScore' w wyniku calculateContactScore: " + scoringResultStr;
            }
        }
        catch(e)
        {
            info "Błąd podczas przetwarzania wyniku calculateContactScore: " + e;
        }
    }
    else
    {
        info "Funkcja calculateContactScore zwróciła pustą wartość dla rekordu: " + recordId;
    }

    info "Scoring rekordu wejściowego: " + incomingScore + " (szczegóły: " + scoringResultStr + ")";
    
    // 3. Znajduje wśród duplikatów rekord z najwyższym scoringiem
    // Przechodzi przez wszystkie duplikaty i porównuje ich scoring
    bestDupId = "";
    bestDupScore = -1;
    for each dupIdKey in duplicateIdsMap.keys()
    {
        dupId = duplicateIdsMap.get(dupIdKey);
        if(dupId == recordId)
        {
            continue;
        }
        dupContact = zoho.crm.getRecordById("Contacts", dupId);
        if(dupContact != null)
        {
            info "Analizuję duplikat: " + dupContact.toString();
            dupScoreResultStr = standalone.calculateContactScore(dupId);
            dupScore = 0;

            try
            {
                dupScoreMap = dupScoreResultStr.toMap();
                if(dupScoreMap != null && dupScoreMap.containsKey("OverallScore"))
                {
                    dupScore = dupScoreMap.get("OverallScore");
                }
                else
                {
                    info "Brak klucza 'OverallScore' w wyniku calculateContactScore dla duplikatu: " + dupScoreResultStr;
                }
            }
            catch(e)
            {
                info "Błąd podczas przetwarzania wyniku calculateContactScore dla duplikatu: " + e;
            }

            info "Scoring duplikatu " + dupId + ": " + dupScore + " (szczegóły: " + dupScoreResultStr + ")";
            
            if(dupScore != null && (bestDupScore == -1 || dupScore > bestDupScore))
            {
                bestDupScore = dupScore;
                bestDupId = dupId;
                info "Znaleziono nowy najlepszy duplikat: ID=" + bestDupId + " ze scoringiem: " + bestDupScore;
            }
        }
    }
    
    if(bestDupId == "")
    {
        info "Nie znaleziono żadnego duplikatu z wyższym scoringiem.";
        return "⚠️ Brak duplikatów dla kontaktu o ID " + recordId;
    }
    info "Najlepszy duplikat: " + bestDupId + " ze scoringiem: " + bestDupScore;
    
    // 4. Ustala który rekord będzie docelowy (target) a który źródłowy (source)
    // Rekord z wyższym scoringiem zostaje targetem
    targetId = "";
    sourceId = "";
    if(incomingScore >= bestDupScore)
    {
        targetId = recordId;
        sourceId = bestDupId;
        info "Rekord wejściowy ma wyższy scoring (" + incomingScore + ") niż najlepszy duplikat (" + bestDupScore + ") - będzie rekordem docelowym";
    }
    else
    {
        targetId = bestDupId;
        sourceId = recordId;
        info "Najlepszy duplikat ma wyższy scoring (" + bestDupScore + ") niż rekord wejściowy (" + incomingScore + ") - będzie rekordem docelowym";
    }
    info "Rekord docelowy (target): " + targetId + ", Rekord źródłowy (source) do przeniesienia: " + sourceId;
    
    // 5. Pobiera pełne dane obu rekordów do dalszej analizy
    targetContact = zoho.crm.getRecordById("Contacts", targetId);
    sourceContact = zoho.crm.getRecordById("Contacts", sourceId);
    if(targetContact == null || sourceContact == null)
    {
        return "❌ Błąd: Nie udało się pobrać rekordu docelowego lub źródłowego.";
    }
    
    // Dodaj nową zmienną do przechowywania oryginalnego ID firmy
    sourceAccountId = null;
    try
    {
        if(sourceContact.get("Account_Name") != null)
        {
            sourceAccountId = sourceContact.get("Account_Name").get("id");
        }
    }
    catch(e)
    {
        info "Błąd podczas pobierania ID firmy z rekordu źródłowego: " + e;
    }
    
    // 6. Przygotowuje mapę aktualizacji - przenosi dane z rekordu źródłowego do docelowego
    // Wypełnia tylko puste pola w rekordzie docelowym
    updateMap = Map();
    for each field in importantFields
    {
        sourceValue = sourceContact.get(field);
        destValue = targetContact.get(field);
        if((destValue == null || destValue == "") && (sourceValue != null && sourceValue != ""))
        {
            updateMap.put(field, sourceValue);
        }
    }
    
    // 7. Specjalna obsługa emaili oraz numerów telefonów
    // Przenosi unikalne emaile do wolnych pól
    // Przenosi unikalne numery telefonów do wolnych pól
    // Zachowuje flagi marketingowe i RODO

    // ----- Przeniesienie adresów email -----
    targetEmailFields = {"Email", "Secondary_Email", "Email_3"};
    sourceEmails = { sourceContact.get("Email"), sourceContact.get("Secondary_Email"), sourceContact.get("Email_3") };
    commonEmail = null;

    for each sEmail in sourceEmails
    {
        if(sEmail != null && sEmail != "")
        {
            info "Analizuję email: " + sEmail + " z rekordu źródłowego";
            duplicateFound = false;
            // Sprawdzenie, czy email już istnieje w rekordzie docelowym lub jest zaplanowany w updateMap
            for each field in targetEmailFields
            {
                if(updateMap.containsKey(field))
                {
                    tEmail = updateMap.get(field);
                }
                else
                {
                    tEmail = targetContact.get(field);
                }
                if(tEmail == sEmail)
                {
                    commonEmail = sEmail;
                    duplicateFound = true;
                    break;
                }
            }
            if(!duplicateFound)
            {
                info "Email " + sEmail + " nie występuje w rekordzie docelowym - szukam wolnego pola";
                // Znajdź pierwsze wolne pole docelowe
                for each field in targetEmailFields
                {
                    if(updateMap.containsKey(field))
                    {
                        tEmail = updateMap.get(field);
                    }
                    else
                    {
                        tEmail = targetContact.get(field);
                    }
                    if(tEmail == null || tEmail == "")
                    {
                        updateMap.put(field, sEmail);
                        info "Przeniesiono email " + sEmail + " do pola " + field;
                        break;
                    }
                }
            }
            else
            {
                info "Email " + sEmail + " już występuje w rekordzie docelowym";
            }
        }
    }

    if(commonEmail != null)
    {
        sourceOptOut = sourceContact.get("Email_Opt_Out");
        sourceMarketingOptOut = sourceContact.get("Email_marketingowy_odsubskrybuj");
        targetRodoField = "";
        for each field in targetEmailFields
        {
            if(updateMap.containsKey(field))
            {
                tEmail = updateMap.get(field);
            }
            else
            {
                tEmail = targetContact.get(field);
            }
            if(tEmail == commonEmail)
            {
                if(field == "Email")
                {
                    targetRodoField = "EMail1_RODO_wyrazona_niezgoda";
                }
                else if(field == "Secondary_Email")
                {
                    targetRodoField = "EMail2_RODO_wyrazona_niezgoda";
                }
                else if(field == "Email_3")
                {
                    targetRodoField = "EMail3_RODO_wyrazona_niezgoda";
                }
                break;
            }
        }
        if(targetRodoField != "" && (sourceOptOut == true || sourceMarketingOptOut == true))
        {
            updateMap.put(targetRodoField, true);
            info "Ustawiono flagę " + targetRodoField + " na true w rekordzie docelowym.";
        }
    }

    // ----- Przeniesienie numerów telefonów komórkowych -----
    targetMobileFields = {"Mobile", "Mobile_2", "Mobile_3"};
    sourceMobilePhones = { sourceContact.get("Mobile"), sourceContact.get("Mobile_2"), sourceContact.get("Mobile_3") };

    for each sMobile in sourceMobilePhones
    {
        if(sMobile != null && sMobile != "")
        {
            info "Analizuję numer komórkowy: " + sMobile + " (po oczyszczeniu: " + sMobile.toString().replaceAll("[^0-9]", "") + ")";
            sMobileClean = sMobile.toString().replaceAll("[^0-9]", "");
            duplicateFound = false;
            for each field in targetMobileFields
            {
                if(updateMap.containsKey(field))
                {
                    tMobile = updateMap.get(field);
                }
                else
                {
                    tMobile = targetContact.get(field);
                }
                if(tMobile != null && tMobile != "")
                {
                    tMobileClean = tMobile.toString().replaceAll("[^0-9]", "");
                    if(tMobileClean == sMobileClean)
                    {
                        duplicateFound = true;
                        break;
                    }
                }
            }
            if(!duplicateFound)
            {
                for each field in targetMobileFields
                {
                    if(updateMap.containsKey(field))
                    {
                        tMobile = updateMap.get(field);
                    }
                    else
                    {
                        tMobile = targetContact.get(field);
                    }
                    if(tMobile == null || tMobile == "")
                    {
                        updateMap.put(field, sMobile);
                        info "Przeniesiono numer komórkowy " + sMobile + " do pola " + field;
                        break;
                    }
                }
            }
        }
    }

    // ----- Przeniesienie numerów telefonów stacjonarnych -----
    targetLandlineFields = {"Phone", "Phone_2", "Phone_3"};
    sourceLandlinePhones = { sourceContact.get("Phone"), sourceContact.get("Phone_2"), sourceContact.get("Phone_3") };

    for each sPhone in sourceLandlinePhones
    {
        if(sPhone != null && sPhone != "")
        {
            info "Analizuję numer stacjonarny: " + sPhone + " (po oczyszczeniu: " + sPhone.toString().replaceAll("[^0-9]", "") + ")";
            sPhoneClean = sPhone.toString().replaceAll("[^0-9]", "");
            duplicateFound = false;
            for each field in targetLandlineFields
            {
                if(updateMap.containsKey(field))
                {
                    tPhone = updateMap.get(field);
                }
                else
                {
                    tPhone = targetContact.get(field);
                }
                if(tPhone != null && tPhone != "")
                {
                    tPhoneClean = tPhone.toString().replaceAll("[^0-9]", "");
                    if(tPhoneClean == sPhoneClean)
                    {
                        duplicateFound = true;
                        break;
                    }
                }
            }
            if(!duplicateFound)
            {
                for each field in targetLandlineFields
                {
                    if(updateMap.containsKey(field))
                    {
                        tPhone = updateMap.get(field);
                    }
                    else
                    {
                        tPhone = targetContact.get(field);
                    }
                    if(tPhone == null || tPhone == "")
                    {
                        updateMap.put(field, sPhone);
                        info "Przeniesiono numer stacjonarny " + sPhone + " do pola " + field;
                        break;
                    }
                }
            }
        }
    }
    
    if(!updateMap.isEmpty())
    {
        info "=== MAPA AKTUALIZACJI REKORDU DOCELOWEGO ===";
        info updateMap.toString();
        info "============================================";
        updateResp = zoho.crm.updateRecord("Contacts", targetId, updateMap);
        info "Zaktualizowano rekord docelowy: " + updateResp.toString();
    }
    else
    {
        info "Brak danych do aktualizacji w rekordzie docelowym";
    }
    
    // 8. Aktualizuje flagi RODO w rekordzie docelowym
    // Zapewnia poprawne ustawienia marketingowe
    rodoUpdateResult = standalone.ContactEmailMarketingowy(targetId);
    info "Zaktualizowano flagi RODO na rekordzie docelowym: " + rodoUpdateResult;
    
    // 9. Przenosi wszystkie powiązania z innych modułów
    // Zapewnia zachowanie relacji biznesowych
    connectionsTransferResult = standalone.ContactModulesConnectionTransfer(sourceId, targetId);
    info "Wynik przenoszenia powiązań: " + connectionsTransferResult;
    
    // 10. Sprawdza i optymalizuje powiązanie z firmą
    // Weryfikuje czy firma ma NIP
    // Szuka lepszej firmy jeśli obecna nie ma NIPu
    // Przenosi kontakt do lepszej firmy jeśli taka istnieje
    // Usuwa starą firmę jeśli ma niski scoring
    info "=== SPRAWDZANIE NIP FIRMY W REKORDZIE DOCELOWYM ===";
    targetContact = zoho.crm.getRecordById("Contacts", targetId);

    // Dodane zabezpieczenie i sprawdzenie NIP firmy
    if(targetContact != null && targetContact.get("Account_Name") != null)
    {
        try
        {
            oldAccountId = targetContact.get("Account_Name").get("id");
            info "Pobieranie danych firmy o ID: " + oldAccountId;
            
            // Pobierz dane firmy, aby sprawdzić pole Firma_NIP
            accountRecord = zoho.crm.getRecordById("Accounts", oldAccountId);
            
            // Sprawdź, czy Firma_NIP jest puste
            if(accountRecord != null && (accountRecord.get("Firma_NIP") == null || accountRecord.get("Firma_NIP") == ""))
            {
                info "Firma nie ma numeru NIP - sprawdzam czy istnieje lepsza firma...";
                
                resultStr = standalone.AccountsSprawdzCzyJestLepsza(oldAccountId);
                resultMap = null;
                najlepszyScoring = 0;
                aktualnyScoring = 0;
                
                try
                {
                    resultMap = resultStr.toMap();
                    info "Wynik sprawdzania lepszej firmy: " + resultStr;
                    
                    if(resultMap != null && resultMap.get("status") == "success")
                    {
                        najlepszyScoring = resultMap.get("najlepszyScoring").toNumber();
                        aktualnyScoring = resultMap.get("aktualnyScoring").toNumber();
                        info "Porównuję scoring - najlepszy: " + najlepszyScoring + " vs aktualny: " + aktualnyScoring;
                        
                        if(aktualnyScoring < 5)
                        {
                            if(najlepszyScoring > aktualnyScoring)
                            {
                                // Jest lepsza firma - przenosimy i usuwamy starą
                                najlepszaFirmaId = resultMap.get("najlepszaFirmaId");
                                info "Znaleziono lepszą firmę: " + najlepszaFirmaId + " (scoring: " + najlepszyScoring + " vs " + aktualnyScoring + ")";
                                
                                // Aktualizuj powiązanie z firmą
                                updateMap = Map();
                                updateMap.put("Account_Name", najlepszaFirmaId);
                                updateResp = zoho.crm.updateRecord("Contacts", targetId, updateMap);
                                info "Zaktualizowano powiązanie firmy w kontakcie: " + updateResp;
                                
                                // Usuń starą firmę o niskim scoringu
                                info "Scoring starej firmy jest poniżej 5 - firma zostanie usunięta";
                                deleteResp = standalone.AccountRecordDeleteInvokeConnector(oldAccountId);
                                info "Wynik usuwania starej firmy: " + deleteResp;
                            }
                            else
                            {
                                info "Firma ma niski scoring (" + aktualnyScoring + "), ale nie znaleziono lepszej firmy - pozostawiam aktualną";
                            }
                        }
                        else if(najlepszyScoring > aktualnyScoring)
                        {
                            // Scoring obecnej firmy jest OK, ale znaleziono lepszą
                            najlepszaFirmaId = resultMap.get("najlepszaFirmaId");
                            info "Znaleziono lepszą firmę: " + najlepszaFirmaId + " (scoring: " + najlepszyScoring + " vs " + aktualnyScoring + ")";
                            
                            // Aktualizuj powiązanie z firmą
                            updateMap = Map();
                            updateMap.put("Account_Name", najlepszaFirmaId);
                            updateResp = zoho.crm.updateRecord("Contacts", targetId, updateMap);
                            info "Zaktualizowano powiązanie firmy w kontakcie: " + updateResp;
                        }
                        else
                        {
                            info "Nie znaleziono firmy o lepszym scoringu - pozostawiam aktualną (najlepszy: " + najlepszyScoring + " vs aktualny: " + aktualnyScoring + ")";
                        }
                    }
                    else if(resultMap != null)
                    {
                        info "Błąd podczas sprawdzania lepszej firmy: " + resultMap.get("message");
                    }
                    else
                    {
                        info "Błąd: Odpowiedź z AccountsSprawdzCzyJestLepsza nie jest poprawną mapą";
                    }
                }
                catch(e)
                {
                    info "Błąd podczas przetwarzania wyniku AccountsSprawdzCzyJestLepsza: " + e;
                }
            }
            else
            {
                info "Firma ma uzupełniony numer NIP: " + accountRecord.get("Firma_NIP") + " - pomijam sprawdzanie lepszej firmy";
            }
        }
        catch(e)
        {
            info "Błąd podczas pobierania danych firmy: " + e;
        }
    }
    else
    {
        info "Rekord docelowy nie ma przypisanej firmy - pomijam sprawdzanie lepszej firmy";
    }

    // 11. Czyści i usuwa rekord źródłowy
    // Usuwa zbędny duplikat po przeniesieniu wszystkich danych
    info "=== DANE REKORDU ŹRÓDŁOWEGO PRZED USUNIĘCIEM ===";
    sourceContactFinal = zoho.crm.getRecordById("Contacts", sourceId);
    info sourceContactFinal.toString();
    info "============================================";
    cleanDeleteResult = standalone.ContactCleanAndDelete(sourceId);
    info "Wynik czyszczenia i usuwania rekordu źródłowego: " + cleanDeleteResult;
    
    // Przygotuj informację o usunięciu firmy
    firmaInfo = "";
    if(resultMap != null && resultMap.get("status") == "success" && aktualnyScoring < 5 && najlepszyScoring > aktualnyScoring)
    {
        firmaInfo = " Stara firma (ID: " + oldAccountId + ") została usunięta ze względu na niski scoring.";
    }
    
    if(sourceAccountId != null)
    {
        info "Sprawdzam możliwość usunięcia starej firmy...";
        info "ID starej firmy (źródłowej): " + sourceAccountId;
        firmaUsunResult = standalone.FirmaUsunNiskiScoring(sourceAccountId);
        info "Wynik sprawdzania starej firmy: " + firmaUsunResult;
    }
    
    return "✅ Przeniesienie zakończone sukcesem. Rekord " + sourceId + " został przeniesiony do " + targetId + " i usunięty." + firmaInfo;
}