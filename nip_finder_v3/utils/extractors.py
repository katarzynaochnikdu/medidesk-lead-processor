"""
Ekstrakcja NIP z tekstu - 6 różnych wzorców regex.
"""

import re
from typing import Optional


def extract_nip_from_text(text: str) -> Optional[str]:
    """
    Wyciąga NIP z tekstu używając wielu wzorców regex.

    Args:
        text: Tekst do przeszukania

    Returns:
        NIP (10 cyfr) lub None
    """
    if not text:
        return None

    # Wzorce dla NIP (w kolejności od najbardziej precyzyjnych)
    patterns = [
        # "NIP: 123-456-78-90" lub "NIP 1234567890"
        r'NIP\s*:?\s*(\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2})',
        r'NIP\s*:?\s*(\d{10})',

        # "numer identyfikacji podatkowej: ..."
        r'numer\s+identyfikacji\s+podatkowej\s*:?\s*(\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2})',

        # "podatnik VAT o numerze: ..."
        r'podatnik\s+VAT\s+o\s+numerze\s*:?\s*(\d{10})',

        # Sam format (najbardziej ryzykowny - może złapać inne numery)
        r'\b(\d{3}[-\s]\d{3}[-\s]\d{2}[-\s]\d{2})\b',

        # "NIP-1234567890" lub "NIP:1234567890"
        r'\bNIP[-:\s]*(\d{10})\b',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # Usuń separatory (myślniki i spacje)
            nip = re.sub(r'[-\s]', '', match)

            # Walidacja długości
            if len(nip) == 10 and nip.isdigit():
                # Dodatkowa walidacja: checksum
                if validate_nip_checksum(nip):
                    return nip

    return None


def validate_nip_checksum(nip: str) -> bool:
    """
    Waliduje checksum NIP.

    Algorytm:
    1. Wagi: [6, 5, 7, 2, 3, 4, 5, 6, 7]
    2. Suma = sum(cyfra[i] * waga[i] for i in 0..8)
    3. Checksum = Suma % 11
    4. Checksum nie może być 10
    5. Checksum musi być równy 10-tej cyfrze

    Args:
        nip: NIP (10 cyfr)

    Returns:
        True jeśli checksum poprawny
    """
    if not nip or len(nip) != 10 or not nip.isdigit():
        return False

    # Wagi dla checksum
    weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]

    # Suma ważona
    checksum = sum(int(nip[i]) * weights[i] for i in range(9)) % 11

    # Checksum nie może być 10 (NIP nieprawidłowy)
    if checksum == 10:
        return False

    # Checksum musi być równy 10-tej cyfrze
    return checksum == int(nip[9])


def format_nip(nip: str) -> str:
    """
    Formatuje NIP do postaci XXX-XXX-XX-XX.

    Args:
        nip: NIP (10 cyfr)

    Returns:
        NIP sformatowany
    """
    if not nip or len(nip) != 10:
        return nip

    return f"{nip[0:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:10]}"
