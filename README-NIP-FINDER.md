# NIP Finder

**Inteligentny system wyszukiwania NIP firm na podstawie minimalnych danych.**

Wykorzystuje:
- **Apify Actors** - Google Search + Web Scraping
- **Vertex AI (Gemini 2.5 Pro)** - AI query expansion + ekstrakcja NIP
- **Walidacja wielopoziomowa** - Checksum + Biała Lista VAT + GUS
- **Cache SQLite** - szybkie powtarzalne wyszukiwania

---

## 📋 Spis treści

- [Instalacja](#instalacja)
- [Konfiguracja](#konfiguracja)
- [Użycie](#użycie)
  - [CLI](#cli)
  - [API](#api)
  - [Python SDK](#python-sdk)
- [Architektura](#architektura)
- [Strategie wyszukiwania](#strategie-wyszukiwania)
- [Troubleshooting](#troubleshooting)

---

## 🚀 Instalacja

### 1. Zainstaluj dependencies

```bash
# Główne dependencies (jeśli jeszcze nie zainstalowane)
pip install -r requirements.txt

# NIP Finder dependencies
pip install -r requirements-nip-finder.txt
```

### 2. Konfiguracja Apify

**Przeczytaj szczegółowe instrukcje:** [`APIFY_SETUP_INSTRUCTIONS.md`](APIFY_SETUP_INSTRUCTIONS.md)

**Quick start:**

1. Załóż konto na https://apify.com/ (free tier: $5/miesiąc)
2. Pobierz API token: Settings → Integrations → Personal API tokens
3. Deploy Custom Web Scraper Actor (instrukcje w [`nip_finder/actors/web_scraper/README.md`](nip_finder/actors/web_scraper/README.md))

### 3. Konfiguracja zmiennych środowiskowych

Dodaj do `.env`:

```bash
# Apify
APIFY_API_TOKEN=apify_api_xxxxxxxxxx
APIFY_GOOGLE_ACTOR_ID=apify/google-search-scraper
APIFY_SCRAPER_ACTOR_ID=your-username/nip-finder-web-scraper

# Vertex AI (już masz w projekcie)
GCP_PROJECT_ID=your-project
GCP_REGION=europe-central2
VERTEX_AI_MODEL=gemini-2.5-pro

# GUS API (już masz w projekcie)
GUS_API_KEY=your-gus-key

# NIP Finder settings (opcjonalne)
NIP_CACHE_DB=nip_finder/cache.db
NIP_CACHE_TTL_DAYS=30
NIP_CONFIDENCE_THRESHOLD=0.7
```

---

## 🎯 Konfiguracja

Wszystkie ustawienia znajdują się w [`nip_finder/config.py`](nip_finder/config.py).

### Domyślne wartości

```python
apify_api_token: str = ""                    # Token Apify
apify_google_actor_id: str = "apify/google-search-scraper"
apify_scraper_actor_id: str = ""            # ID Custom Actora

nip_cache_db: str = "nip_finder/cache.db"   # Ścieżka do cache
nip_cache_ttl_days: int = 30                 # Czas życia cache (dni)

nip_confidence_threshold: float = 0.7        # Minimalny próg confidence
fuzzy_match_threshold: float = 0.8           # Próg fuzzy match nazw

max_google_results: int = 20                 # Max wyników Google per query
max_urls_to_scrape: int = 10                 # Max URL do scrapowania
max_scrape_text_length: int = 50000         # Max znaków tekstu do AI

apify_actor_timeout_sec: int = 300          # Timeout Actora (sekundy)
```

---

## 📖 Użycie

### CLI

#### Pojedyncze wyszukiwanie

```bash
python -m nip_finder.cli single --name "VITA MEDICA SIEDLCE" --city "Siedlce"
```

**Output:**
```
🔍 Szukam NIP dla: VITA MEDICA SIEDLCE

============================================================
✅ NIP ZNALEZIONY

📍 Firma: VITA MEDICA SIEDLCE
📍 Miasto: Siedlce

💼 NIP: 123-456-78-90
🎯 Confidence: 95%
📊 Strategia: google_search_ai
🌐 Źródło: https://vitamedica.pl/polityka-prywatnosci

✔️ WALIDACJA:
  • Checksum: ✅
  • VAT aktywny: ✅
  • GUS nazwa: VITA MEDICA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ
  • Match score: 92%
  • Zwalidowany: ✅

⏱️ Czas: 8542ms
============================================================
```

**Z opcjami:**

```bash
# Z emailem (dla domeny)
python -m nip_finder.cli single --name "Centrum Medyczne" --email "kontakt@centrum.pl"

# Pomiń cache
python -m nip_finder.cli single --name "VITA MEDICA" --skip-cache

# Zapisz do JSON
python -m nip_finder.cli single --name "VITA MEDICA" --output result.json
```

#### Batch processing

```bash
python -m nip_finder.cli batch input.csv --output results.csv --report report.md
```

**Format input CSV:**

```csv
company_name,city,email
VITA MEDICA SIEDLCE,Siedlce,
Centrum medyczne kropka,Warszawa,kontakt@centrum.pl
NZOZ Przychodnia,Kraków,
```

**Output:**
- `results.csv` - tabelka z wynikami (Excel-ready)
- `report.md` - szczegółowy raport
- `results.json` (opcjonalnie) - JSON z pełnymi danymi

**Opcje:**

```bash
# Więcej równoległych zapytań (default: 5)
python -m nip_finder.cli batch input.csv --max-concurrent 10

# Własne nazwy kolumn
python -m nip_finder.cli batch input.csv \
  --name-column "firma" \
  --city-column "miasto" \
  --email-column "email_firmowy"

# Wszystkie outputy
python -m nip_finder.cli batch input.csv \
  --output results.csv \
  --report report.md \
  --json-output results.json
```

#### Cache management

```bash
# Statystyki cache
python -m nip_finder.cli cache stats

# Wyczyszczenie wygasłych wpisów
python -m nip_finder.cli cache clear
```

---

### API

#### Uruchomienie serwera

```bash
# Development
uvicorn nip_finder.api:app --reload --port 8000

# Production
uvicorn nip_finder.api:app --host 0.0.0.0 --port 8000 --workers 4
```

#### Endpoints

**POST /find-nip** - Pojedyncze wyszukiwanie

```bash
curl -X POST http://localhost:8000/find-nip \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "VITA MEDICA SIEDLCE",
    "city": "Siedlce",
    "email": "kontakt@vitamedica.pl"
  }'
```

**Response:**
```json
{
  "company_name": "VITA MEDICA SIEDLCE",
  "city": "Siedlce",
  "nip": "1234567890",
  "nip_formatted": "123-456-78-90",
  "found": true,
  "confidence": 0.95,
  "strategy_used": "google_search_ai",
  "validation": {
    "valid_checksum": true,
    "vat_active": true,
    "gus_name": "VITA MEDICA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
    "name_match_score": 0.92,
    "validated": true
  },
  "processing_time_ms": 8542
}
```

**POST /batch-find-nip** - Batch processing

```bash
curl -X POST http://localhost:8000/batch-find-nip \
  -H "Content-Type: application/json" \
  -d '{
    "companies": [
      {"company_name": "VITA MEDICA SIEDLCE", "city": "Siedlce"},
      {"company_name": "Centrum Medyczne", "city": "Warszawa"}
    ],
    "max_concurrent": 5
  }'
```

**GET /cache/stats** - Statystyki cache

```bash
curl http://localhost:8000/cache/stats
```

**POST /cache/clear** - Wyczyszczenie cache

```bash
curl -X POST http://localhost:8000/cache/clear
```

---

### Python SDK

```python
import asyncio
from nip_finder import NIPFinder, NIPRequest

async def main():
    # Inicjalizacja
    finder = NIPFinder(use_cache=True)
    
    # Pojedyncze wyszukiwanie
    result = await finder.find_nip(
        company_name="VITA MEDICA SIEDLCE",
        city="Siedlce",
        email="kontakt@vitamedica.pl",
    )
    
    if result.found:
        print(f"✅ NIP: {result.nip_formatted}")
        print(f"   Confidence: {result.confidence:.2%}")
        print(f"   Validated: {result.validation.validated}")
    else:
        print(f"❌ Nie znaleziono NIP")
        print(f"   Errors: {result.errors}")
    
    # Batch processing
    requests = [
        NIPRequest(company_name="Firma A", city="Warszawa"),
        NIPRequest(company_name="Firma B", city="Kraków"),
    ]
    
    results = await finder.batch_find_nip(requests, max_concurrent=5)
    
    print(f"Znaleziono: {sum(1 for r in results if r.found)}/{len(results)}")
    
    # Zamknij połączenia
    await finder.close()

# Uruchom
asyncio.run(main())
```

---

## 🏗️ Architektura

### Flow wyszukiwania (wielopoziomowy)

```
┌─────────────────────────────────────────────────────────┐
│ 1. CACHE LOOKUP (instant)                              │
│    • SQLite local cache                                 │
│    • TTL: 30 dni                                        │
└─────────────┬───────────────────────────────────────────┘
              │ Cache MISS ↓
┌─────────────▼───────────────────────────────────────────┐
│ 2. AI QUERY EXPANSION (Vertex AI)                      │
│    • Generuje 3-5 optymalnych queries Google           │
│    • Uwzględnia miasto, domenę email                    │
└─────────────┬───────────────────────────────────────────┘
              ↓
┌─────────────▼───────────────────────────────────────────┐
│ 3. GOOGLE SEARCH (Apify Actor)                         │
│    • apify/google-search-scraper                       │
│    • Top 20 URL per query                              │
│    • Filtrowanie po keywords (polityka, kontakt, etc.) │
└─────────────┬───────────────────────────────────────────┘
              ↓
┌─────────────▼───────────────────────────────────────────┐
│ 4. DEEP SCRAPING (Custom Apify Actor)                  │
│    • Playwright + priorytetyzacja (footer, RODO)       │
│    • Max 10 URL                                         │
│    • Wyciąga tekst (max 10k znaków per strona)         │
└─────────────┬───────────────────────────────────────────┘
              ↓
┌─────────────▼───────────────────────────────────────────┐
│ 5. AI EXTRACTION (Vertex AI)                           │
│    • Gemini 2.5 Pro analizuje teksty                   │
│    • Wyciąga NIP + confidence + reasoning               │
│    • Max 50k znaków corpus                             │
└─────────────┬───────────────────────────────────────────┘
              ↓
┌─────────────▼───────────────────────────────────────────┐
│ 6. WALIDACJA (3-poziomowa)                             │
│    • Checksum (matematyczna suma kontrolna)            │
│    • Biała Lista VAT (API MF)                          │
│    • GUS cross-reference (fuzzy match nazw)            │
└─────────────┬───────────────────────────────────────────┘
              ↓
┌─────────────▼───────────────────────────────────────────┐
│ 7. CACHE SAVE                                           │
│    • Zapisz wynik do cache (SQLite)                    │
└─────────────────────────────────────────────────────────┘
```

### Komponenty

- **`orchestrator.py`** - Główny flow, koordynator
- **`ai_extractor.py`** - Vertex AI integration
- **`apify_client.py`** - Apify SDK wrapper
- **`validator.py`** - Walidacja NIP
- **`cache.py`** - SQLite cache
- **`output_handler.py`** - CSV/JSON/Report
- **`cli.py`** - CLI interface
- **`api.py`** - FastAPI endpoints

---

## 🎯 Strategie wyszukiwania

### 1. Cache (instant)

**Skuteczność:** 100% (jeśli w cache)
**Czas:** <10ms

### 2. Google Search + AI (główna strategia)

**Skuteczność:** 60-80%
**Czas:** 5-15s

**Jak działa:**
1. AI generuje queries: `"Firma ABC" "Miasto" NIP`, `"Firma ABC" polityka prywatności`
2. Google Search przez Apify (top 20 URL)
3. Priorytetyzacja URL (/polityka-prywatnosci, /kontakt, /o-nas)
4. Scraping top 10 stron (Playwright)
5. AI analizuje teksty i wyciąga NIP

**Najlepsze dla:**
- Firm z własną stroną internetową
- Firm publikujących politykę prywatności (RODO)

### 3. Fallback scraping (bez Apify)

**Skuteczność:** 30-50%
**Czas:** 10-20s

**Jak działa:**
- httpx + BeautifulSoup (bez proxy)
- Regex extraction bez AI
- Używany gdy Apify niedostępne

**Ograniczenia:**
- Łatwiej zablokować przez Google
- Brak Playwright (niektóre strony wymagają JS)

---

## 💰 Koszty

### Apify

**Free tier:** $5 credit/miesiąc
- ~2000 Google searches
- ~500 scraped pages
- **Wystarczy na ~40-50 firm z pełnym flow**

**Pay-as-you-go:**
- Google Search: ~$0.002/query
- Web Scraper: ~$0.01/page

**Przykład:** 100 firm × 5 queries × 10 scrapes = ~$6

### Vertex AI

- Gemini 2.5 Pro: ~$0.002/1k znaków input
- Query generation: ~500 znaków = ~$0.001
- NIP extraction: ~20k znaków = ~$0.04
- **~$0.05 per firma**

### Całkowite

- **Z Apify:** ~$0.11 per firma
- **Bez Apify (fallback):** ~$0.05 per firma (tylko AI)

---

## 🐛 Troubleshooting

### "Unauthorized" error (Apify)

**Problem:** Błędny lub wygasły token Apify

**Rozwiązanie:**
1. Sprawdź `APIFY_API_TOKEN` w `.env`
2. Token musi zaczynać się od `apify_api_`
3. Pobierz nowy token: https://console.apify.com/account/integrations

### "Actor not found" (Apify)

**Problem:** Niepoprawny ID Custom Actora

**Rozwiązanie:**
1. Sprawdź czy Actor został zbudowany i opublikowany
2. ID format: `username/actor-name` (np. `john/nip-finder-web-scraper`)
3. Zaktualizuj `APIFY_SCRAPER_ACTOR_ID` w `.env`

### Brak wyników Google Search

**Problem:** Google blokuje zapytania / Rate limit

**Rozwiązanie:**
1. Apify ma wbudowane proxy - upewnij się że używasz gotowego Actora
2. Zwiększ timeout: `APIFY_ACTOR_TIMEOUT_SEC=600`
3. Zmniejsz `max_concurrent` w batch

### AI nie wyciąga NIP z tekstów

**Problem:** Teksty nie zawierają NIP / AI nie rozpoznaje kontekstu

**Rozwiązanie:**
1. Sprawdź czy Apify scrapuje właściwe URL (polityka prywatności)
2. Zwiększ `max_urls_to_scrape` (więcej stron = większa szansa)
3. Sprawdź logi AI - czy dostaje teksty

### Błąd "Vertex AI not initialized"

**Problem:** Brak credentials GCP lub niepoprawna konfiguracja

**Rozwiązanie:**
1. Sprawdź `GCP_PROJECT_ID` i `VERTEX_AI_MODEL` w `.env`
2. Upewnij się że masz Application Default Credentials:
   ```bash
   gcloud auth application-default login
   ```
3. Sprawdź czy projekt ma włączone Vertex AI API

### Cache nie działa

**Problem:** Błąd połączenia z SQLite

**Rozwiązanie:**
1. Sprawdź uprawnienia do zapisu w `nip_finder/`
2. Usuń uszkodzony cache: `rm nip_finder/cache.db`
3. Cache zostanie automatycznie odtworzony

### Timeout w batch processing

**Problem:** Niektóre firmy powodują timeout

**Rozwiązanie:**
1. Zmniejsz `max_concurrent` (domyślnie 5)
2. Zwiększ `APIFY_ACTOR_TIMEOUT_SEC` (domyślnie 300s)
3. Przetwórz problematyczne firmy osobno z `skip-cache`

---

## 📊 Metryki success

Przykładowe wyniki dla 100 firm:

```
✅ NIP znaleziony: 73/100 (73%)
✅ Zwalidowany: 68/73 (93% znalezionych)

Strategie:
  • cache: 12 (12%)
  • google_search_ai: 45 (45%)
  • deep_scraping: 16 (16%)

Confidence distribution:
  • High (>0.9): 45 (62%)
  • Medium (0.7-0.9): 20 (27%)
  • Low (<0.7): 8 (11%)

Avg processing time: 9.2s per firma
```

---

## 🔧 Development

### Struktura projektu

```
nip_finder/
├── __init__.py           # Public API
├── config.py             # Konfiguracja
├── models.py             # Pydantic models
├── orchestrator.py       # Główny flow
├── ai_extractor.py       # Vertex AI
├── apify_client.py       # Apify SDK wrapper
├── validator.py          # Walidacja NIP
├── cache.py              # SQLite cache
├── output_handler.py     # CSV/JSON/Report
├── cli.py                # CLI interface
├── api.py                # FastAPI endpoints
├── actors/               # Apify Actors
│   └── web_scraper/      # Custom Scraper Actor
│       ├── main.js
│       ├── package.json
│       └── README.md
└── tests/                # Testy
    ├── test_nip_finder.py
    ├── run_manual_test.py
    └── test_sample_data.csv
```

### Uruchomienie testów

```bash
# Testy jednostkowe
pytest nip_finder/tests/test_nip_finder.py -v

# Manual test z próbką danych
python -m nip_finder.tests.run_manual_test
```

---

## 📝 Licencja

Medidesk Internal Project

---

## 👥 Autor

AI Agent + Medidesk Team

---

## 🆘 Wsparcie

W razie problemów:
1. Sprawdź [Troubleshooting](#troubleshooting)
2. Sprawdź logi (`logging.INFO`)
3. Przetestuj pojedyncze komponenty osobno
4. Skontaktuj się z zespołem Medidesk
