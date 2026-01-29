# Plan Testow Porownawczych AI - Test Set 2

## Przeglad

- **Zrodlo danych**: test set 2.xlsx (294 rekordy)
- **Referencja**: test set reference 2.xlsx
- **Data rozpoczecia**: 2026-01-28
- **Cel**: Iteracyjne ulepszanie algorytmu normalizacji i matchingu

## Struktura testow

### Paczki testowe

| Paczka | Zakres wierszy | Liczba rekordow | Cel |
|--------|----------------|-----------------|-----|
| Batch 1 | 1-100 | 100 | Baseline + pierwsze poprawki |
| Batch 2 | 101-200 | 100 | Walidacja poprawek + kolejne ulepszenia |
| Batch 3 | 201-294 | 94 | Finalny test calego algorytmu |
| FULL | 1-294 | 294 | Pelny test po wszystkich poprawkach |

### Cykl dla kazdej paczki

1. **TEST** - Uruchomienie obu wariantow (V1 strukturalny, V2 surowy tekst)
2. **ANALIZA** - Obliczenie metryk, identyfikacja bledow
3. **DIAGNOZA** - Analiza przyczyn bledow
4. **POPRAWA** - Implementacja ulepszenia
5. **RE-TEST** - Weryfikacja poprawki
6. **DOKUMENTACJA** - Zapis wynikow i wnioskow

### Metryki do sledzenia

#### Kontakty
- True Positive (TP) - poprawnie znaleziony kontakt
- False Negative (FN) - kontakt istnieje, nie znaleziony
- False Positive (FP) - kontakt "znaleziony" blednie
- Tier distribution (4/3/2/0)
- Sygnaly (E/P/L/F/A)

#### Firmy
- True Positive (TP)
- False Negative (FN)
- False Positive (FP)
- Parent vs Child (poprawnosc wyboru siedziby)

#### Normalizacja
- Imiona/nazwiska - poprawnosc
- Email - lowercase, poprawnosc
- Telefon - format +48 XXX XXX XXX
- NIP - walidacja, zrodlo (Brave/dane/GUS)

#### Rekomendacje
- create_new
- link_to_existing
- review_required
- Avg confidence

## Pliki wynikowe

Kazdy cykl generuje:
- `batch_X_results_v1.xlsx` - wyniki V1
- `batch_X_results_v2.xlsx` - wyniki V2
- `batch_X_comparison.xlsx` - porownanie
- `batch_X_analysis.md` - analiza i wnioski
- `batch_X_fixes.md` - opis poprawek

## Historia zmian algorytmu

| Data | Wersja | Opis zmiany | Batch | Efekt |
|------|--------|-------------|-------|-------|
| 2026-01-28 | 1.0 | Baseline przed testami | - | - |
| | | | | |

## Status

- [ ] Batch 1 - baseline
- [ ] Batch 1 - analiza
- [ ] Batch 1 - poprawki
- [ ] Batch 1 - re-test
- [ ] Batch 2 - test
- [ ] Batch 2 - analiza
- [ ] Batch 2 - poprawki
- [ ] Batch 2 - re-test
- [ ] Batch 3 - test
- [ ] Batch 3 - analiza
- [ ] Batch 3 - poprawki
- [ ] Batch 3 - re-test
- [ ] FULL - finalny test
- [ ] Raport koncowy
