# Batch 1 - Poprawki

## Data: 2026-01-28

## Problem 1: Niezgodnosc formatu ID

### Opis
W pierwszym tescie wszystkie True Positive = 0, mimo ze system znajdowal kontakty.

### Przyczyna
Format ID roznil sie miedzy wynikami testu a referencja:
- **Test ID**: `7.51364e+17` (float, notacja naukowa)
- **Ref ID**: `zcrm_751364000033659036` (string z prefixem `zcrm_`)

### Rozwiazanie
Dodano funkcje `normalize_id()` w `run_batch_test.py`:
1. Usuwanie prefixu `zcrm_`
2. Konwersja notacji naukowej do pelnego int
3. Porownanie jako stringi

### Kod
```python
def normalize_id(id_val):
    if pd.isna(id_val) or id_val is None:
        return None
    s = str(id_val)
    # Usun prefix zcrm_
    if s.startswith("zcrm_"):
        s = s[5:]
    # Konwertuj notacje naukowa do int
    try:
        if 'e' in s.lower() or '.' in s:
            s = str(int(float(s)))
    except:
        pass
    return s
```

### Status
- [x] Zaimplementowano
- [ ] Przetestowano (re-test w toku)

## Nastepne kroki

Po zakonczeniu re-testu:
1. Sprawdzic czy TP > 0
2. Przeanalizowac pozostale bledy
3. Zidentyfikowac wzorce w FP/FN
