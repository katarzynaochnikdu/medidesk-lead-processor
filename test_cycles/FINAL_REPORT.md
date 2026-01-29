# Raport Koncowy - Testy Porownawcze AI

## Data: 2026-01-28
## Autor: AI Test Runner
## Zestaw testowy: test set 2.xlsx (294 rekordy)

---

## 1. Podsumowanie Wykonawcze

### Testowane warianty

| Wariant | Opis |
|---------|------|
| **V1 - Structural** | Dane mapowane do oddzielnych pol (first_name, last_name, email, phone, company) |
| **V2 - Raw Text** | Wszystkie dane sklejone w jeden tekst raw_name, AI ekstrahuje wszystko |

### Wynik koncowy

| Metryka | V1 (Structural) | V2 (Raw Text) | Zwyciezca |
|---------|-----------------|---------------|-----------|
| **Precision** | 68.1% | **71.8%** | **V2** |
| **Recall** | **88.7%** | 87.9% | **V1** |
| **F1 Score** | 76.9% | **79.0%** | **V2** |

**REKOMENDACJA: V2 (Raw Text) jest lepszy** - wyzsza Precision przy nieznacznie nizszym Recall.

---

## 2. Szczegolowe wyniki po batchach

### Kontakty

| Batch | Rekordow | V1 TP | V1 FP | V1 FN | V2 TP | V2 FP | V2 FN |
|-------|----------|-------|-------|-------|-------|-------|-------|
| 1 | 100 | 55 | 13 | 8 | 56 | 11 | 8 |
| 2 | 100 | 23 | 18 | 4 | 23 | 13 | 4 |
| 3 | 94 | 16 | 13 | 0 | 15 | 13 | 1 |
| **SUMA** | **294** | **94** | **44** | **12** | **94** | **37** | **13** |

### Firmy

| Batch | V1 TP | V1 FP | V1 FN | V2 TP | V2 FP | V2 FN |
|-------|-------|-------|-------|-------|-------|-------|
| 1 | 14 | 3 | 19 | 14 | 3 | 19 |
| 2 | 11 | 2 | 16 | 11 | 2 | 16 |
| 3 | 9 | 7 | 5 | 9 | 6 | 5 |
| **SUMA** | **34** | **12** | **40** | **34** | **11** | **40** |

### Account Recall

| Batch | V1 Recall | V2 Recall |
|-------|-----------|-----------|
| 1 | 42.4% | 42.4% |
| 2 | 40.7% | 40.7% |
| 3 | 64.3% | 64.3% |
| **Srednia** | **45.9%** | **45.9%** |

**UWAGA:** Account Recall jest niski (45.9%). Wymaga poprawy!

---

## 3. Analiza bledow

### 3.1 False Negatives (nie znaleziono kontaktu)

| Przyczyna | Liczba | Przyklad |
|-----------|--------|----------|
| Zdrobnienia | 3 | Asia Adam vs Anna Adam |
| Polskie znaki | 2 | Michal Dab vs Michał Dąb |
| Literowki | 1 | Melnichuk vs Melnychuk |
| Zla ekstrakcja | 2 | "Nowowiejska 11 Jasiewicz" |
| **SUMA** | **12-13** | |

### 3.2 False Positives (znaleziono blednie)

| Przyczyna | Liczba | Opis |
|-----------|--------|------|
| Dopasowanie do innego kontaktu | ~20 | Znaleziono kontakt ale inny niz w referencji |
| Znaleziono gdy powinno byc NOWY | ~17 | Ref=NOWY ale system znalazl istniejacy |
| Tier 2 bez primary_id | ~10 | Slabe dopasowanie zaraportowane jako znalezione |

### 3.3 Account False Negatives (firma nie znaleziona)

**Glowna przyczyna:** Brak NIP w danych wejsciowych
- Matching po nazwie firmy jest mniej precyzyjny
- Wiele firm ma podobne nazwy
- NIP jest kluczowy dla pewnego dopasowania

---

## 4. Wdrozone poprawki

### 4.1 Naprawa formatu ID (Batch 1)

**Problem:** TP=0 mimo ze system znajdowal kontakty
**Przyczyna:** Format ID roznil sie (zcrm_ prefix, notacja naukowa)
**Rozwiazanie:** Funkcja `normalize_id()` - usuwanie prefixu, konwersja float->int

### 4.2 Rozszerzenie zdrobnien

**Dodano:**
- Asia -> Anna (wczesniej Joanna - blednie)
- Ela -> Elzbieta (juz bylo)

---

## 5. Rekomendacje do dalszego rozwoju

### Priorytet 1: Poprawa Account Recall

1. **Wyciaganie NIP z danych** - jesli firma w raw_name zawiera NIP, ekstrakcja i walidacja
2. **Brave Search dla firm bez NIP** - wyszukiwanie NIP po nazwie firmy
3. **Fuzzy matching nazw firm** - Levenshtein distance dla podobnych nazw

### Priorytet 2: Normalizacja polskich znakow

1. Dodac normalizacje diakrytykow przed porownaniem
2. a = ą, e = ę, c = ć, itd.
3. Michal = Michał

### Priorytet 3: Lepsza ekstrakcja z raw_name

1. Rozpoznawanie adresow (ulica, nr) vs nazwiska
2. "Nowowiejska 11 Jasiewicz" -> last_name="Jasiewicz", address="Nowowiejska 11"

### Priorytet 4: Analiza Tier 2

1. Tier 2 (slabe dopasowanie) nie powinno automatycznie linkowac
2. Dodac review_required dla Tier 2

---

## 6. Pliki wygenerowane

| Plik | Opis |
|------|------|
| batch_1_structural_*.xlsx | Wyniki V1 dla Batch 1 |
| batch_1_raw_text_*.xlsx | Wyniki V2 dla Batch 1 |
| batch_1_analysis.md | Analiza Batch 1 |
| batch_1_metrics.json | Metryki JSON Batch 1 |
| batch_1_fixes.md | Dokumentacja poprawek |
| batch_2_*.xlsx | Wyniki Batch 2 |
| batch_2_analysis.md | Analiza Batch 2 |
| batch_3_*.xlsx | Wyniki Batch 3 |
| batch_3_analysis.md | Analiza Batch 3 |
| FINAL_REPORT.md | Ten raport |

---

## 7. Wnioski

1. **V2 (Raw Text) jest lepszy** - wyzsza Precision (71.8% vs 68.1%)
2. **Recall jest dobry** - 87-89% kontaktow jest poprawnie znajdowanych
3. **Account matching wymaga poprawy** - tylko 46% firm jest znajdowanych
4. **Zdrobnienia i polskie znaki** - glowne przyczyny FN
5. **Format ID** - wymagal normalizacji (zcrm_ prefix)

---

## 8. Nastepne kroki

- [ ] Wdrozyc poprawe Account Recall (NIP extraction)
- [ ] Dodac normalizacje polskich znakow
- [ ] Poprawic ekstrakcje adresow z raw_name
- [ ] Dodac review_required dla Tier 2
- [ ] Przetestowac na wiekszym zbiorze (500+ rekordow)
