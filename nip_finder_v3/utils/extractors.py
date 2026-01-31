"""
Ekstrakcja danych z tekstu - NIP, email, telefon, adres, social links.
"""

import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


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


# ============================================
# Email extraction
# ============================================

# Publiczne domeny email do odfiltrowania
PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "yahoo.pl", "icloud.com", "me.com", "aol.com",
    "wp.pl", "onet.pl", "interia.pl", "o2.pl", "poczta.pl", "gazeta.pl",
    "op.pl", "tlen.pl", "buziaczek.pl", "vp.pl", "go2.pl",
    "protonmail.com", "tutanota.com", "zoho.com",
}


def extract_emails_from_text(text: str, exclude_public: bool = True) -> list[str]:
    """
    Wyciąga adresy email z tekstu.

    Args:
        text: Tekst do przeszukania
        exclude_public: Czy pomijać publiczne domeny (gmail, wp.pl, etc.)

    Returns:
        Lista unikalnych adresów email (lowercase)
    """
    if not text:
        return []

    # RFC 5322 simplified email pattern
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    
    matches = re.findall(pattern, text, re.IGNORECASE)
    
    emails = []
    seen = set()
    
    for email in matches:
        email_lower = email.lower().strip()
        
        # Skip duplicates
        if email_lower in seen:
            continue
        seen.add(email_lower)
        
        # Skip public domains if requested
        if exclude_public:
            domain = email_lower.split("@")[-1]
            if domain in PUBLIC_EMAIL_DOMAINS:
                continue
        
        # Skip common false positives
        if any(fp in email_lower for fp in ["example.com", "test.com", "localhost", "@2x.", "@3x."]):
            continue
        
        emails.append(email_lower)
    
    return emails


# ============================================
# Phone extraction
# ============================================

def extract_phones_from_text(text: str) -> list[str]:
    """
    Wyciąga polskie numery telefonów z tekstu.

    Args:
        text: Tekst do przeszukania

    Returns:
        Lista unikalnych numerów telefonów w formacie +48XXXXXXXXX
    """
    if not text:
        return []

    # Wzorce dla polskich numerów telefonów
    patterns = [
        # +48 123 456 789 lub +48123456789
        r'\+48\s*(\d{3})\s*(\d{3})\s*(\d{3})',
        # 0048 123 456 789
        r'0048\s*(\d{3})\s*(\d{3})\s*(\d{3})',
        # (48) 123 456 789
        r'\(48\)\s*(\d{3})\s*(\d{3})\s*(\d{3})',
        # 123-456-789 lub 123 456 789 (9 cyfr bez prefiksu)
        r'(?<![0-9])(\d{3})[-\s]?(\d{3})[-\s]?(\d{3})(?![0-9])',
        # (12) 345-67-89 (numer stacjonarny z kierunkowym)
        r'\((\d{2})\)\s*(\d{3})[-\s]?(\d{2})[-\s]?(\d{2})',
        # 12 345 67 89 (numer stacjonarny)
        r'(?<![0-9])(\d{2})\s+(\d{3})[-\s]?(\d{2})[-\s]?(\d{2})(?![0-9])',
    ]
    
    phones = []
    seen = set()
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            # Połącz grupy w jeden numer
            if isinstance(match, tuple):
                digits = "".join(match)
            else:
                digits = match
            
            # Usuń wszystkie nie-cyfry
            digits = re.sub(r'\D', '', digits)
            
            # Walidacja długości (9 cyfr dla PL)
            if len(digits) == 9:
                # Format: +48XXXXXXXXX
                phone = f"+48{digits}"
                
                # Skip duplicates
                if phone in seen:
                    continue
                seen.add(phone)
                
                # Skip obvious false positives (all same digit, sequential)
                if len(set(digits)) <= 2:
                    continue
                
                phones.append(phone)
    
    return phones


# ============================================
# Address extraction
# ============================================

def extract_addresses_from_text(text: str) -> list[str]:
    """
    Wyciąga polskie adresy z tekstu (heurystyka).

    Szuka wzorców typu:
    - ul. Marszałkowska 1/2
    - al. Jana Pawła II 15
    - 00-001 Warszawa

    Args:
        text: Tekst do przeszukania

    Returns:
        Lista znalezionych adresów
    """
    if not text:
        return []
    
    addresses = []
    seen = set()
    
    # Wzorzec 1: ul./al./pl. + nazwa + numer
    street_pattern = r'(?:ul\.|ulica|al\.|aleja|pl\.|plac|os\.|osiedle)\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż\s\-\.]+\s*\d+[a-zA-Z]?(?:\s*/\s*\d+[a-zA-Z]?)?'
    
    for match in re.findall(street_pattern, text, re.IGNORECASE):
        addr = match.strip()
        addr_lower = addr.lower()
        if addr_lower not in seen and len(addr) > 5:
            seen.add(addr_lower)
            addresses.append(addr)
    
    # Wzorzec 2: kod pocztowy + miasto
    zip_city_pattern = r'\d{2}[-\s]?\d{3}\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźżA-ZĄĆĘŁŃÓŚŹŻ\s\-]+'
    
    for match in re.findall(zip_city_pattern, text):
        addr = match.strip()
        # Ogranicz do rozsądnej długości (miasto + ewentualnie dzielnica)
        if len(addr) > 50:
            addr = addr[:50].rsplit(" ", 1)[0]
        addr_lower = addr.lower()
        if addr_lower not in seen and len(addr) > 5:
            seen.add(addr_lower)
            addresses.append(addr)
    
    return addresses[:5]  # Max 5 adresów


# ============================================
# Social links extraction
# ============================================

SOCIAL_PATTERNS = {
    "facebook": r'(?:https?://)?(?:www\.)?facebook\.com/[a-zA-Z0-9._-]+/?',
    "linkedin": r'(?:https?://)?(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9._-]+/?',
    "instagram": r'(?:https?://)?(?:www\.)?instagram\.com/[a-zA-Z0-9._-]+/?',
    "twitter": r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9._-]+/?',
    "youtube": r'(?:https?://)?(?:www\.)?youtube\.com/(?:channel|c|user)/[a-zA-Z0-9._-]+/?',
    "tiktok": r'(?:https?://)?(?:www\.)?tiktok\.com/@[a-zA-Z0-9._-]+/?',
}


def extract_social_links_from_text(text: str) -> dict[str, str]:
    """
    Wyciąga linki do social media z tekstu.

    Args:
        text: Tekst (lub HTML) do przeszukania

    Returns:
        Dict {platform: url}
    """
    if not text:
        return {}
    
    social_links = {}
    
    for platform, pattern in SOCIAL_PATTERNS.items():
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            url = matches[0]
            # Ensure https://
            if not url.startswith("http"):
                url = "https://" + url
            # Skip share/sharer links
            if "/sharer" in url or "/share" in url:
                continue
            social_links[platform] = url
    
    return social_links


def extract_social_links(soup: "BeautifulSoup") -> dict[str, str]:
    """
    Wyciąga linki do social media z BeautifulSoup.

    Szuka w:
    - atrybutach href linków
    - tekście strony (fallback)

    Args:
        soup: BeautifulSoup object

    Returns:
        Dict {platform: url}
    """
    social_links = {}
    
    # Szukaj w linkach
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "")
        if not href:
            continue
        
        for platform, pattern in SOCIAL_PATTERNS.items():
            if platform in social_links:
                continue  # Already found
            if re.match(pattern, href, re.IGNORECASE):
                url = href
                if not url.startswith("http"):
                    url = "https://" + url
                # Skip share/sharer links
                if "/sharer" in url or "/share" in url:
                    continue
                social_links[platform] = url
    
    # Fallback: szukaj w tekście
    if not social_links:
        full_text = soup.get_text()
        social_links = extract_social_links_from_text(full_text)
    
    return social_links
