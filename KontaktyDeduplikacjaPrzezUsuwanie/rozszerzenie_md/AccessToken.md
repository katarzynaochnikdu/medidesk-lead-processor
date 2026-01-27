string standalone.AccessToken()
{
    // 1. Najpierw próbujemy pobrać istniejący access token
    current_access_token = zoho.crm.getOrgVariable("ZOHO_ACCESS_TOKEN");
    
    // Jeśli token istnieje, sprawdzamy czy jest ważny
    if(current_access_token != null && current_access_token != "")
    {
        try 
        {
            // Próba użycia tokenu do prostego zapytania
            headers = Map();
            headers.put("Authorization", "Zoho-oauthtoken " + current_access_token);
            test_response = invokeurl
            [
                url: "https://www.zohoapis.eu/crm/v2/settings/modules"
                type: GET
                headers: headers
            ];
            
            // Jeśli nie wyrzuciło błędu, token jest ważny
            return current_access_token;
        }
        catch (e)
        {
            info "Token wygasł lub jest nieprawidłowy, generuję nowy...";
        }
    }

    // 2. Jeśli token nie istnieje lub jest nieważny, generujemy nowy
    client_id = zoho.crm.getOrgVariable("ZOHO_CLIENT_ID");
    client_secret = zoho.crm.getOrgVariable("ZOHO_CLIENT_SECRET");
    refresh_token = zoho.crm.getOrgVariable("ZOHO_REFRESH_TOKEN");

    paramMap = Map();
    paramMap.put("refresh_token", refresh_token);
    paramMap.put("client_id", client_id);
    paramMap.put("client_secret", client_secret);
    paramMap.put("grant_type", "refresh_token");

    token_url = "https://accounts.zoho.eu/oauth/v2/token";
    response = postUrl(token_url, paramMap);
    info "Odpowiedź z token endpointu: " + response;

    responseMap = response.toMap();

    if(responseMap.containsKey("access_token"))
    {
        new_access_token = responseMap.get("access_token").toString();
        
        // Wysyłamy email z nowym tokenem używając zoho.adminuserid
        sendmail
        [
            from: zoho.adminuserid
            to: "adminzoho@medidesk.com"
            subject: "Nowy Access Token Zoho CRM"
            message: "Wygenerowano nowy access token dla Zoho CRM.<br><br>" + 
                    "Token: " + new_access_token + "<br><br>" + 
                    "Należy go zaktualizować w zmiennych organizacji (ZOHO_ACCESS_TOKEN)."
        ]
        
        info "Wygenerowano nowy access token. Wysłano powiadomienie email.";
        return new_access_token;
    }
    else
    {
        // Wysyłamy email o błędzie
        sendmail
        [
            from: zoho.adminuserid
            to: "adminzoho@medidesk.com"
            subject: "❌ Błąd generowania Access Token Zoho CRM"
            message: "Wystąpił błąd podczas generowania access tokena.<br><br>" + 
                    "Szczegóły błędu: " + response
        ]
        
        return "Błąd: Nie udało się pobrać access tokena. Szczegóły: " + response;
    }
}
