"""
Formatowanie i czyszczenie numerów telefonów.
Obsługuje różne formaty używane w Zoho CRM.
"""

import re
from typing import Optional, Dict


class PhoneFormatter:
    """
    Formatuje telefony do różnych postaci używanych w Zoho CRM.
    
    Formaty:
    - clean: 123456789 (9 cyfr bez spacji)
    - mobile: 123 456 789 (format komórkowy)
    - stacjonarny: 12 345 67 89 (format stacjonarny)
    - e164: +48123456789 (format międzynarodowy)
    """

    def format_phone(self, phone: Optional[str], format_type: str = "clean") -> str:
        """
        Czyści i formatuje numer telefonu.

        Args:
            phone: Surowy numer telefonu (może zawierać spacje, +48 itp.)
            format_type: Jeden z "clean", "mobile", "stacjonarny", "e164".

        Returns:
            Sformatowany numer telefonu lub pusty string jeśli niepoprawny.
        """
        if not phone:
            return ""

        phone_str = str(phone).strip()
        if not phone_str:
            return ""

        # Usuń wszystko oprócz cyfr
        clean_phone = re.sub(r"[^0-9]", "", phone_str)

        # Usuń prefix kraju +48
        if clean_phone.startswith("48") and len(clean_phone) == 11:
            clean_phone = clean_phone[2:]
        
        # Usuń prefix 0048
        if clean_phone.startswith("0048") and len(clean_phone) == 13:
            clean_phone = clean_phone[4:]

        # Polski numer ma 9 cyfr
        if len(clean_phone) != 9:
            return ""

        if format_type == "mobile":
            # XXX XXX XXX
            return f"{clean_phone[0:3]} {clean_phone[3:6]} {clean_phone[6:9]}"

        if format_type == "stacjonarny":
            # XX XXX XX XX
            return f"{clean_phone[0:2]} {clean_phone[2:5]} {clean_phone[5:7]} {clean_phone[7:9]}"
        
        if format_type == "e164":
            # +48XXXXXXXXX
            return f"+48{clean_phone}"

        # clean - domyślnie
        return clean_phone

    def get_all_formats(self, phone: Optional[str]) -> Dict[str, str]:
        """
        Zwraca wszystkie obsługiwane formaty telefonu.
        
        Args:
            phone: Numer telefonu w dowolnym formacie
            
        Returns:
            Słownik z wszystkimi formatami
        """
        clean = self.format_phone(phone, "clean")
        if not clean:
            return {"clean": "", "mobile": "", "stacjonarny": "", "e164": ""}

        return {
            "clean": clean,
            "mobile": self.format_phone(phone, "mobile"),
            "stacjonarny": self.format_phone(phone, "stacjonarny"),
            "e164": self.format_phone(phone, "e164"),
        }
    
    def normalize_for_comparison(self, phone: Optional[str]) -> str:
        """
        Normalizuje telefon do postaci porównawczej (9 cyfr).
        
        Args:
            phone: Numer telefonu w dowolnym formacie
            
        Returns:
            9 cyfr lub pusty string
        """
        return self.format_phone(phone, "clean")


def format_phone_number(phone: Optional[str], format_type: str = "clean") -> str:
    """Funkcja pomocnicza - skrót do PhoneFormatter.format_phone."""
    return PhoneFormatter().format_phone(phone, format_type)
