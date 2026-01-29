# NIP Finder - Quick Start

Szybki start dla wyszukiwania NIP firm.

---

## 🚀 Setup (5 minut)

### 1. Zainstaluj dependencies

```bash
pip install -r requirements-nip-finder.txt
```

### 2. Skonfiguruj Apify

```bash
# 1. Załóż konto: https://apify.com/ (free tier: $5/miesiąc)
# 2. Pobierz token: Settings → Integrations
# 3. Deploy Custom Actor (zobacz: actors/web_scraper/README.md)
```

### 3. Konfiguracja .env

Skopiuj `nip_finder/.env.example` do głównego `.env` i wypełnij:

```bash
# Minimalne wymagania:
APIFY_API_TOKEN=apify_api_xxxxxxxxxx
GCP_PROJECT_ID=your-project
VERTEX_AI_MODEL=gemini-2.5-pro
```

---

## 💻 Użycie

### CLI - Pojedyncze wyszukiwanie

```bash
python -m nip_finder.cli single \
  --name "VITA MEDICA SIEDLCE" \
  --city "Siedlce"
```

### CLI - Batch z CSV

```bash
# Przygotuj CSV (company_name, city, email)
python -m nip_finder.cli batch input.csv \
  --output results.csv \
  --report report.md
```

### API

```bash
# Uruchom serwer
uvicorn nip_finder.api:app --reload

# Test
curl -X POST http://localhost:8000/find-nip \
  -H "Content-Type: application/json" \
  -d '{"company_name": "VITA MEDICA SIEDLCE", "city": "Siedlce"}'
```

### Python

```python
import asyncio
from nip_finder import NIPFinder

async def main():
    finder = NIPFinder()
    
    result = await finder.find_nip(
        company_name="VITA MEDICA SIEDLCE",
        city="Siedlce"
    )
    
    if result.found:
        print(f"NIP: {result.nip_formatted}")
        print(f"Confidence: {result.confidence:.2%}")
    
    await finder.close()

asyncio.run(main())
```

---

## 🎯 Przykłady

### CSV input format

```csv
company_name,city,email
VITA MEDICA SIEDLCE,Siedlce,
Centrum medyczne kropka,Warszawa,kontakt@centrum.pl
NZOZ Przychodnia,Kraków,
```

### Output

**results.csv:**
```csv
company_name,city,nip,nip_formatted,found,confidence,validated
VITA MEDICA SIEDLCE,Siedlce,1234567890,123-456-78-90,TAK,0.95,TAK
Centrum medyczne,Warszawa,,,NIE,0.00,NIE
```

**report.md:**
```markdown
# NIP Finder Report

## Summary
- Total: 2
- Found: 1 (50%)
- Avg confidence: 0.95

## Top Results
1. VITA MEDICA SIEDLCE
   - NIP: 123-456-78-90
   - Confidence: 95%
   - Source: https://vitamedica.pl/polityka-prywatnosci
   - Validated: ✅
```

---

## 🐛 Troubleshooting

### Apify "Unauthorized"
→ Sprawdź `APIFY_API_TOKEN` w `.env`

### "Actor not found"
→ Deploy Custom Actor (zobacz `actors/web_scraper/README.md`)

### Vertex AI error
→ Sprawdź `GCP_PROJECT_ID` i credentials: `gcloud auth application-default login`

### Brak wyników
→ Zwiększ `MAX_URLS_TO_SCRAPE` lub sprawdź logi

---

## 📚 Więcej informacji

- **Pełna dokumentacja:** [`README-NIP-FINDER.md`](../README-NIP-FINDER.md)
- **Apify setup:** [`APIFY_SETUP_INSTRUCTIONS.md`](../APIFY_SETUP_INSTRUCTIONS.md)
- **Custom Actor:** [`actors/web_scraper/README.md`](actors/web_scraper/README.md)
- **Tests:** [`tests/run_manual_test.py`](tests/run_manual_test.py)

---

## 💰 Koszty

- **Apify free tier:** $5/miesiąc = ~40-50 firm
- **Vertex AI:** ~$0.05 per firma
- **Całkowite:** ~$0.11 per firma (z Apify)

---

## ✅ Checklist

- [ ] Zainstalowane dependencies
- [ ] Konto Apify + token
- [ ] Custom Actor deployed
- [ ] `.env` skonfigurowany
- [ ] Test pojedynczego wyszukiwania działa
- [ ] Test batch z CSV działa

---

🎉 **Gotowe!** Możesz teraz wyszukiwać NIP dla firm z minimalnych danych.
