"""
Narzędzia do pracy z domenami email.
"""

import re
from typing import Optional

from ..config import get_settings


def extract_email_domain(email: str) -> Optional[str]:
    """
    Wyciąga domenę z adresu email.

    Przykład:
        "jan.kowalski@przychodnia-abc.pl" → "przychodnia-abc.pl"

    Args:
        email: Adres email

    Returns:
        Domena lub None
    """
    if not email:
        return None

    # Regex dla email
    email_pattern = r'^[^@]+@([^@]+)$'
    match = re.match(email_pattern, email.strip())

    if match:
        domain = match.group(1).lower()
        return domain

    return None


def is_public_email_domain(domain: Optional[str]) -> bool:
    """
    Sprawdza czy domena to publiczny dostawca email (gmail, outlook, etc.).

    Args:
        domain: Domena

    Returns:
        True jeśli publiczna domena
    """
    if not domain:
        return False

    settings = get_settings()
    public_domains = settings.public_email_domains

    # Normalizuj domenę
    domain = domain.lower().strip()

    # Sprawdź czy domena jest na liście
    return domain in public_domains


def get_company_domain_from_email(email: str) -> Optional[str]:
    """
    Wyciąga domenę firmową z emaila (filtrując publiczne domeny).

    Przykład:
        "jan@przychodnia-abc.pl" → "przychodnia-abc.pl"
        "jan@gmail.com" → None (publiczna domena)

    Args:
        email: Adres email

    Returns:
        Domena firmowa lub None
    """
    if not email:
        return None

    domain = extract_email_domain(email)

    if domain and not is_public_email_domain(domain):
        return domain

    return None


def normalize_domain(domain: str) -> str:
    """
    Normalizuje domenę (lowercase, trim, usuń www).

    Args:
        domain: Domena

    Returns:
        Znormalizowana domena
    """
    if not domain:
        return ""

    # Lowercase i trim
    normalized = domain.lower().strip()

    # Usuń protocol (http://, https://)
    normalized = re.sub(r'^https?://', '', normalized)

    # Usuń www.
    normalized = re.sub(r'^www\.', '', normalized)

    # Usuń trailing slash
    normalized = normalized.rstrip('/')

    return normalized
