"""
Funkcje pomocnicze dla NIP Finder v2.
"""

import re
from typing import Optional


def normalize_company_name(name: str) -> str:
    """
    Normalizuje nazwe firmy do wyszukiwania.
    
    Usuwa:
    - Formy prawne (sp. z o.o., S.A., etc.)
    - Nadmiarowe spacje
    - Znaki specjalne
    """
    if not name:
        return ""
    
    # Usun formy prawne
    legal_forms = [
        r'\s+sp\.?\s*z\s*o\.?\s*o\.?',
        r'\s+sp\.?\s*j\.?',
        r'\s+sp\.?\s*k\.?',
        r'\s+sp\.?\s*p\.?',
        r'\s+s\.?\s*a\.?',
        r'\s+s\.?\s*c\.?',
        r'\s+spolka\s+z\s+ograniczona\s+odpowiedzialnoscia',
        r'\s+spolka\s+akcyjna',
        r'\s+spolka\s+jawna',
        r'\s+spolka\s+komandytowa',
        r'\s+sp\.?\s*k\.?\s*a\.?',  # sp.k.a. / SKA
        r'\s+sp\.?\s*z\.?\s*o\.?\s*o\.?\s*sp\.?\s*k\.?',  # sp. z o.o. sp.k.
    ]
    
    result = name
    for pattern in legal_forms:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)
    
    # Usun nadmiarowe spacje
    result = ' '.join(result.split())
    
    return result.strip()


def normalize_polish_chars(text: str) -> str:
    """Zamienia polskie znaki na ASCII."""
    pl_map = {
        'a': 'a', 'c': 'c', 'e': 'e', 'l': 'l', 'n': 'n',
        'o': 'o', 's': 's', 'z': 'z', 'z': 'z',
        'A': 'A', 'C': 'C', 'E': 'E', 'L': 'L', 'N': 'N',
        'O': 'O', 'S': 'S', 'Z': 'Z', 'Z': 'Z',
    }
    for pl, ascii_char in pl_map.items():
        text = text.replace(pl, ascii_char)
    return text


def calculate_name_similarity(name1: str, name2: str) -> float:
    """
    Oblicza podobienstwo dwoch nazw firm (0-1).
    
    Uzywa uproszczonego algorytmu:
    1. Normalizuj obie nazwy
    2. Porownaj slowa
    """
    if not name1 or not name2:
        return 0.0
    
    # Normalizuj
    n1 = normalize_company_name(name1).lower()
    n2 = normalize_company_name(name2).lower()
    
    # Usun polskie znaki
    n1 = normalize_polish_chars(n1)
    n2 = normalize_polish_chars(n2)
    
    # Podziel na slowa
    words1 = set(n1.split())
    words2 = set(n2.split())
    
    if not words1 or not words2:
        return 0.0
    
    # Oblicz Jaccard similarity
    intersection = words1 & words2
    union = words1 | words2
    
    return len(intersection) / len(union)


def is_valid_nip(nip: str) -> bool:
    """Sprawdza czy NIP ma poprawna sume kontrolna."""
    if not nip or len(nip) != 10:
        return False
    
    if not nip.isdigit():
        return False
    
    # Wagi dla cyfr NIP
    weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    
    # Oblicz sume kontrolna
    checksum = sum(int(nip[i]) * weights[i] for i in range(9))
    checksum = checksum % 11
    
    # Jesli checksum == 10, NIP jest niepoprawny
    if checksum == 10:
        return False
    
    return checksum == int(nip[9])


def normalize_nip(nip: str) -> Optional[str]:
    """Normalizuje NIP do 10 cyfr."""
    if not nip:
        return None
    
    # Usun wszystko poza cyframi
    clean = re.sub(r'[^\d]', '', nip)
    
    if len(clean) == 10:
        return clean
    
    return None


def format_nip(nip: str) -> str:
    """Formatuje NIP do XXX-XXX-XX-XX."""
    if len(nip) != 10:
        return nip
    return f"{nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:10]}"


def extract_nips_from_text(text: str) -> list[str]:
    """
    Wyciaga wszystkie potencjalne NIPy z tekstu.
    
    Zwraca liste NIPow (tylko te z poprawna suma kontrolna).
    """
    if not text:
        return []
    
    # Wzorce NIP
    patterns = [
        r'NIP\s*[:/]?\s*(?:VAT\s*)?(\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2})',
        r'NIP\s*[:/]?\s*(?:VAT\s*)?(\d{10})',
        r'\b(\d{3}-\d{3}-\d{2}-\d{2})\b',
        r'\b(\d{3}\s\d{3}\s\d{2}\s\d{2})\b',
    ]
    
    found_nips = set()
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            nip = normalize_nip(match)
            if nip and is_valid_nip(nip):
                found_nips.add(nip)
    
    return list(found_nips)
