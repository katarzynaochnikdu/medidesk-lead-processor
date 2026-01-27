"""
Walidatory i normalizatory danych.
NIP, telefon, email - polskie standardy.
"""

import re
from typing import Optional, Tuple

# Wagi dla sumy kontrolnej NIP
NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def normalize_nip(nip: Optional[str]) -> Optional[str]:
    """
    Normalizuje NIP do postaci 10 cyfr.
    Usuwa wszystkie znaki oprócz cyfr.
    
    Args:
        nip: NIP w dowolnym formacie (np. "123-456-78-90", "PL1234567890")
    
    Returns:
        NIP jako 10 cyfr lub None
    """
    if not nip:
        return None
    
    # Usuń wszystko oprócz cyfr
    digits = "".join(c for c in str(nip) if c.isdigit())
    
    # Polski NIP ma 10 cyfr
    if len(digits) == 10:
        return digits
    
    # Może być z prefiksem kraju (np. PL)
    if len(digits) > 10:
        # Spróbuj ostatnie 10 cyfr
        return digits[-10:]
    
    return None


def is_valid_nip(nip: Optional[str]) -> bool:
    """
    Sprawdza poprawność NIP (suma kontrolna).
    
    Args:
        nip: NIP - 10 cyfr
    
    Returns:
        True jeśli NIP jest poprawny
    """
    normalized = normalize_nip(nip)
    if not normalized or len(normalized) != 10:
        return False
    
    try:
        digits = [int(d) for d in normalized]
        
        # Oblicz sumę kontrolną
        checksum = sum(d * w for d, w in zip(digits[:9], NIP_WEIGHTS)) % 11
        
        # Suma kontrolna nie może być 10
        if checksum == 10:
            return False
        
        return checksum == digits[9]
    except (ValueError, IndexError):
        return False


def format_nip(nip: Optional[str]) -> Optional[str]:
    """
    Formatuje NIP do postaci XXX-XXX-XX-XX.
    
    Args:
        nip: NIP - 10 cyfr
    
    Returns:
        Sformatowany NIP lub None
    """
    normalized = normalize_nip(nip)
    if not normalized or len(normalized) != 10:
        return None
    
    return f"{normalized[:3]}-{normalized[3:6]}-{normalized[6:8]}-{normalized[8:10]}"


def normalize_phone(phone: Optional[str], default_country: str = "PL") -> Optional[str]:
    """
    Normalizuje numer telefonu do formatu E.164 (+XXXXXXXXXXXX bez spacji).
    Używa phonenumbers library dla prawidłowego parsowania wszystkich krajów.
    
    Args:
        phone: Telefon w dowolnym formacie
        default_country: Domyślny kraj jako ISO kod (PL, US, FR, etc.)
    
    Returns:
        Telefon w formacie E.164: +48XXXXXXXXX lub None
    """
    if not phone:
        return None
    
    try:
        import phonenumbers
        
        phone_str = str(phone).strip()
        
        # Parsuj z domyślnym krajem
        parsed = phonenumbers.parse(phone_str, default_country)
        
        # Waliduj
        if not phonenumbers.is_valid_number(parsed):
            return None
        
        # Zwróć w formacie E.164 (bez spacji)
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        
    except Exception:
        # Fallback jeśli phonenumbers nie zadziała
        return None


def capitalize_name(name: Optional[str]) -> Optional[str]:
    """
    Kapitalizuje imię lub nazwisko - pierwsza litera każdego słowa WIELKA, reszta małe.
    Obsługuje nazwiska dwuczłonowe ze spacjami i myślnikami.
    
    Args:
        name: Imię lub nazwisko
    
    Returns:
        Skapitalizowane imię/nazwisko
    
    Examples:
        "jan kowalski" -> "Jan Kowalski"
        "MARIA NOWAK-KOWALSKA" -> "Maria Nowak-Kowalska"
        "anne-marie" -> "Anne-Marie"
    """
    if not name:
        return None
    
    name = name.strip()
    
    # Podziel na słowa (spacje) i części z myślnikami
    words = []
    for word in name.split():
        # Dla każdego słowa: obsłuż myślniki
        parts = word.split("-")
        capitalized_parts = [p.capitalize() for p in parts if p]
        words.append("-".join(capitalized_parts))
    
    return " ".join(words)


def format_phone(phone: Optional[str]) -> Optional[str]:
    """
    Formatuje telefon do czytelnej postaci z spacjami.
    - Polski: +48 XXX XXX XXX
    - Zagraniczny: +XX XXX XXX XXX (format międzynarodowy)
    
    Args:
        phone: Telefon w dowolnym formacie
    
    Returns:
        Sformatowany telefon ze spacjami lub None
    """
    if not phone:
        return None
    
    try:
        import phonenumbers
        
        phone_str = str(phone).strip()
        
        # Jeśli już znormalizowany (E.164)
        if phone_str.startswith("+"):
            parsed = phonenumbers.parse(phone_str, None)
        else:
            # Spróbuj sparsować z domyślnym krajem PL
            parsed = phonenumbers.parse(phone_str, "PL")
        
        # Waliduj
        if not phonenumbers.is_valid_number(parsed):
            return None
        
        # Formatuj z spacjami (INTERNATIONAL format)
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        
    except Exception:
        # Fallback - prosty format dla polskich
        normalized = normalize_phone(phone)
        if not normalized:
            return None
        
        if normalized.startswith("+48") and len(normalized) == 12:
            digits = normalized[3:]
            return f"+48 {digits[:3]} {digits[3:6]} {digits[6:]}"
        
        return normalized


def is_valid_email(email: Optional[str]) -> bool:
    """
    Podstawowa walidacja adresu email.
    
    Args:
        email: Adres email
    
    Returns:
        True jeśli email wygląda na poprawny
    """
    if not email:
        return False
    
    # Prosty regex - nie próbujemy być zbyt restrykcyjni
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email.strip()))


def extract_email_domain(email: Optional[str]) -> Optional[str]:
    """
    Wyciąga domenę z adresu email.
    
    Args:
        email: Adres email
    
    Returns:
        Domena (np. "medidesk.pl") lub None
    """
    if not email or "@" not in email:
        return None
    
    try:
        domain = email.split("@")[-1].strip().lower()
        return domain if domain else None
    except Exception:
        return None


def is_public_email_domain(domain: Optional[str]) -> bool:
    """
    Sprawdza czy domena to publiczny dostawca email.
    
    Args:
        domain: Domena email
    
    Returns:
        True jeśli to domena publiczna (gmail, wp, etc.)
    """
    if not domain:
        return True  # Brak domeny = traktuj jak publiczną
    
    PUBLIC_DOMAINS = {
        # Google
        "gmail.com", "googlemail.com",
        # Microsoft
        "outlook.com", "hotmail.com", "live.com", "msn.com",
        # Yahoo
        "yahoo.com", "yahoo.pl", "ymail.com",
        # Polskie
        "wp.pl", "o2.pl", "onet.pl", "onet.eu", "interia.pl", "interia.eu",
        "poczta.fm", "tlen.pl", "op.pl", "spoko.pl", "vp.pl",
        "gazeta.pl", "prokonto.pl",
        # Inne
        "aol.com", "icloud.com", "mail.com", "protonmail.com",
        "zoho.com", "yandex.com", "gmx.com", "gmx.net",
    }
    
    return domain.lower() in PUBLIC_DOMAINS


def parse_full_name(full_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Próbuje rozdzielić pełne imię i nazwisko.
    Prosta heurystyka - dla złożonych przypadków użyj AI.
    
    Args:
        full_name: Pełne imię i nazwisko
    
    Returns:
        Tuple (imię, nazwisko)
    """
    if not full_name:
        return None, None
    
    parts = full_name.strip().split()
    
    if len(parts) == 0:
        return None, None
    elif len(parts) == 1:
        # Tylko jedno słowo - trudno powiedzieć
        return None, parts[0]
    elif len(parts) == 2:
        # Klasyczny przypadek: Imię Nazwisko
        return parts[0], parts[1]
    else:
        # Więcej słów - pierwsze to imię, reszta to nazwisko
        return parts[0], " ".join(parts[1:])
