string standalone.formatPhoneNumber(String phone, String rodzaj)
{
    if(phone == null || phone == "") {
        return "";
    }
    
    // Usunięcie wszystkich nie-cyfr
    cleanPhone = phone.replaceAll("[^0-9]","");
    
    // Usunięcie prefiksu kraju jeśli istnieje
    if(cleanPhone.startsWith("48") && cleanPhone.length() == 11) {
        cleanPhone = cleanPhone.substring(2);
    }
    // Jeśli numer zaczyna się od +48 to już zostało usunięte przez replaceAll
    
    // Sprawdzenie czy mamy dokładnie 9 cyfr
    if(cleanPhone.length() != 9) {
        return "";
    }
    
    if(rodzaj == "mobile") {
        // Format XXX XXX XXX dla komórkowych
        return cleanPhone.substring(0,3) + " " + cleanPhone.substring(3,6) + " " + cleanPhone.substring(6);
    } else if(rodzaj == "stacjonarny") {
        // Format XX XXX XX XX dla stacjonarnych
        return cleanPhone.substring(0,2) + " " + cleanPhone.substring(2,5) + " " + cleanPhone.substring(5,7) + " " + cleanPhone.substring(7);
    } else {
        return cleanPhone; // Format XXXXXXXXX
    }
}