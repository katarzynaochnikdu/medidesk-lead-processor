"""
Normalizacja nazw firm.
"""

import re
from typing import Optional


def normalize_company_name(name: str) -> str:
    """
    Normalizuje nazwę firmy do celów wyszukiwania.

    Operacje:
    1. Usunięcie form prawnych (sp. z o.o., S.A., etc.)
    2. Usunięcie znaków specjalnych
    3. Lowercase
    4. Trim

    Args:
        name: Nazwa firmy

    Returns:
        Znormalizowana nazwa
    """
    if not name:
        return ""

    # Kopia do pracy
    normalized = name

    # Usuń formy prawne
    legal_forms = [
        r'\b(spółka\s+z\s+ograniczoną\s+odpowiedzialnością)\b',
        r'\b(sp\.\s*z\s*o\.?\s*o\.?)\b',
        r'\b(s\.?\s*a\.?)\b',
        r'\b(spółka\s+akcyjna)\b',
        r'\b(sp\.\s*j\.?)\b',
        r'\b(spółka\s+jawna)\b',
        r'\b(sp\.\s*c\.?)\b',
        r'\b(spółka\s+cywilna)\b',
        r'\b(sp\.\s*k\.?)\b',
        r'\b(spółka\s+komandytowa)\b',
        r'\b(s\.?\s*k\.?\s*a\.?)\b',
        r'\b(spółka\s+komandytowo-akcyjna)\b',
        r'\b(p\.?\s*p\.?\s*h\.?\s*u\.?)\b',
        r'\b(przedsiębiorstwo\s+prywatne\s+handel\s+usługi)\b',
        r'\b(p\.?\s*h\.?\s*u\.?)\b',
        r'\b(przedsiębiorstwo\s+handel\s+usługi)\b',
        r'\b(ltd\.?)\b',
        r'\b(limited)\b',
        r'\b(inc\.?)\b',
        r'\b(incorporated)\b',
        r'\b(corp\.?)\b',
        r'\b(corporation)\b',
        r'\b(llc\.?)\b',
    ]

    for form in legal_forms:
        normalized = re.sub(form, '', normalized, flags=re.IGNORECASE)

    # Usuń znaki specjalne (zostaw tylko litery, cyfry, spacje, myślniki)
    normalized = re.sub(r'[^\w\s\-ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]', ' ', normalized)

    # Usuń podwójne spacje
    normalized = re.sub(r'\s+', ' ', normalized)

    # Lowercase i trim
    normalized = normalized.strip().lower()

    return normalized


def extract_company_base_name(full_name: str) -> str:
    """
    Wyciąga bazową nazwę firmy (bez form prawnych i dodatkowych oznaczeń).

    Przykład:
        "Medicover Sp. z o.o." → "medicover"
        "Przychodnia VITA MEDICA" → "vita medica"
        "Centrum Medyczne PragaMed" → "pragamed"

    Args:
        full_name: Pełna nazwa firmy

    Returns:
        Bazowa nazwa
    """
    # Najpierw normalizuj
    normalized = normalize_company_name(full_name)

    # Usuń typowe przedrostki i ogólne słowa (wielokrotnie, aż się nie zmienia)
    generic_words = [
        r'\b(przychodnia|poradnia|klinika|centrum|gabinet|praktyka)\b',
        r'\b(firma|przedsiębiorstwo|zakład)\b',
        r'\b(medyczne|medyczny|medyczna|medycznych)\b',
        r'\b(sieć|grupa|grupę)\b',
    ]

    # Usuń wszystkie ogólne słowa (iteracyjnie)
    prev_normalized = ""
    max_iterations = 5  # Zabezpieczenie przed nieskończoną pętlą

    iteration = 0
    while normalized != prev_normalized and iteration < max_iterations:
        prev_normalized = normalized

        for word_pattern in generic_words:
            normalized = re.sub(word_pattern, ' ', normalized, flags=re.IGNORECASE)

        # Usuń podwójne spacje i trim
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        iteration += 1

    return normalized


def fuzzy_match(name1: str, name2: str) -> float:
    """
    Oblicza podobieństwo dwóch nazw firm (0.0-1.0).

    Używa prostego algorytmu:
    1. Normalizuje obie nazwy
    2. Liczy liczbę wspólnych słów
    3. Zwraca stosunek wspólnych słów do wszystkich

    Args:
        name1: Pierwsza nazwa
        name2: Druga nazwa

    Returns:
        Wynik podobieństwa (0.0-1.0)
    """
    if not name1 or not name2:
        return 0.0

    # Normalizuj
    norm1 = normalize_company_name(name1)
    norm2 = normalize_company_name(name2)

    # Podziel na słowa
    words1 = set(norm1.split())
    words2 = set(norm2.split())

    # Usuń puste słowa
    words1 = {w for w in words1 if w}
    words2 = {w for w in words2 if w}

    if not words1 or not words2:
        return 0.0

    # Oblicz przecięcie
    intersection = words1.intersection(words2)

    # Oblicz wynik (Jaccard similarity)
    union = words1.union(words2)
    score = len(intersection) / len(union)

    return score


def calculate_name_match_score(expected: str, found: str) -> float:
    """
    Oblicza jak dobrze znaleziona nazwa pasuje do oczekiwanej (STRICT).

    Ta funkcja jest bardziej restrykcyjna niż fuzzy_match - wymaga aby
    WSZYSTKIE słowa z expected były obecne w found.

    Przykład:
        expected="Centrum Medyczne PragaMed"
        found="PRAGAMED Sp. z o.o." → 0.33 (tylko 1/3 słów)
        found="Centrum Medyczne PragaMed" → 1.0 (wszystkie słowa)

    Args:
        expected: Oczekiwana nazwa firmy
        found: Znaleziona nazwa (np. z Google Search)

    Returns:
        Score 0.0-1.0:
        - 1.0 = exact match lub wszystkie słowa obecne
        - 0.9 = wszystkie istotne słowa obecne
        - 0.7 = większość słów obecna
        - < 0.7 = brak kluczowych słów (REJECT)
    """
    if not expected or not found:
        return 0.0

    # Normalizuj
    expected_norm = normalize_company_name(expected)
    found_norm = normalize_company_name(found)
    
    # Usuń spacje do porównania zawierania (probody vs pro body)
    expected_nospace = expected_norm.replace(" ", "")
    found_nospace = found_norm.replace(" ", "")

    # Exact match bonus
    if expected_norm == found_norm:
        return 1.0
    if expected_norm in found_norm or found_norm in expected_norm:
        return 0.95
    
    # NOWE: Sprawdź zawieranie bez spacji (probody in "probody" lub "pro body")
    # To pozwala na match "ProBody" z "SPA PRO BODY"
    if expected_nospace in found_nospace or found_nospace in expected_nospace:
        return 0.90
    
    # NOWE: Sprawdź czy krótka nazwa (bez spacji) jest zawarta
    # np. "probody" powinno matchować "probodyclinic"
    if len(expected_nospace) >= 4:
        if expected_nospace in found_nospace:
            return 0.85

    # Podziel na słowa
    expected_words = set(expected_norm.split())
    found_words = set(found_norm.split())

    # Usuń puste
    expected_words = {w for w in expected_words if w and len(w) > 1}
    found_words = {w for w in found_words if w and len(w) > 1}

    if not expected_words:
        return 0.0

    # Oblicz ile słów z expected jest w found
    overlap = expected_words & found_words

    # STRICT: wszystkie słowa muszą być obecne
    coverage = len(overlap) / len(expected_words)

    # Penalty za brakujące kluczowe słowa
    missing = expected_words - found_words
    if missing:
        # Sprawdź czy brakujące słowa są kluczowe (np. "centrum", "medyczne")
        # vs. mało istotne (np. "i", "oraz")
        key_words = {w for w in missing if len(w) > 3}  # Długie słowa = ważniejsze
        if key_words:
            # Brakuje kluczowych słów - duża kara
            coverage *= (1.0 - 0.3 * len(key_words) / len(expected_words))

    return min(1.0, coverage)
