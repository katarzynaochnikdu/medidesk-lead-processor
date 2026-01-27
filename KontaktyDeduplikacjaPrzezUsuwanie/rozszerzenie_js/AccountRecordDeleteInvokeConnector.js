string standalone.AccountRecordDeleteInvokeConnector(string accountId)
{
    responseMap = Map();
    
    try 
    {
        // Wywołaj API do usunięcia rekordu
        response = invokeurl
        [
            url: "https://www.zohoapis.eu/crm/v2/Accounts/" + accountId
            type: DELETE
            connection: "zoho_crm"
        ];
        
        if(response != null)
        {
            responseMap.put("status", "success");
            responseMap.put("message", "Firma została usunięta");
            responseMap.put("response", response);
        }
        else
        {
            responseMap.put("status", "error");
            responseMap.put("message", "Brak odpowiedzi z API");
        }
    }
    catch (e)
    {
        responseMap.put("status", "error");
        responseMap.put("message", "Błąd podczas usuwania: " + e);
    }
    
    return responseMap.toString();
}