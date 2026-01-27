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


def normalize_phone(phone: Optional[str], default_country: str = "48") -> Optional[str]:
    """
    Normalizuje numer telefonu do formatu +XXXXXXXXXXXX.
    
    Args:
        phone: Telefon w dowolnym formacie
        default_country: Domyślny prefix kraju (bez +)
    
    Returns:
        Telefon w formacie +48XXXXXXXXX lub None
    """
    if not phone:
        return None
    
    phone_str = str(phone).strip()
    
    # Usuń wszystko oprócz cyfr i +
    cleaned = "".join(c for c in phone_str if c.isdigit() or c == "+")
    
    if not cleaned:
        return None
    
    # Obsługa różnych formatów
    if cleaned.startswith("+"):
        # Już ma prefix międzynarodowy
        digits = cleaned[1:]
        if len(digits) >= 9:
            return f"+{digits}"
    elif cleaned.startswith("00"):
        # Format 0048...
        digits = cleaned[2:]
        if len(digits) >= 9:
            return f"+{digits}"
    elif cleaned.startswith("0"):
        # Format 0601... (stary polski)
        digits = cleaned[1:]
        if len(digits) == 9:
            return f"+{default_country}{digits}"
    else:
        # Bez prefixu
        if len(cleaned) == 9:
            # Polski numer bez prefixu
            return f"+{default_country}{cleaned}"
        elif len(cleaned) > 9:
            # Może już zawiera prefix
            if cleaned.startswith(default_country):
                return f"+{cleaned}"
            return f"+{cleaned}"
    
    return None


def format_phone(phone: Optional[str]) -> Optional[str]:
    """
    Formatuje telefon do czytelnej postaci +48 XXX XXX XXX.
    
    Args:
        phone: Znormalizowany telefon (+48XXXXXXXXX)
    
    Returns:
        Sformatowany telefon lub None
    """
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    
    # Dla polskich numerów
    if normalized.startswith("+48") and len(normalized) == 12:
        digits = normalized[3:]
        return f"+48 {digits[:3]} {digits[3:6]} {digits[6:]}"
    
    # Dla innych - prosty format
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
