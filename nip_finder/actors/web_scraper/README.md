# NIP Finder Web Scraper Actor

Custom Apify Actor do scrapingu stron dla NIP Finder.

## Funkcjonalność

Scrapuje listę URL i wyciąga tekst z priorytetyzacją:

1. **Footer** (90% szans na NIP) - stopka strony
2. **Sekcje relevantne** (70%) - sekcje z keywords: nip, kontakt, rodo, polityka
3. **Full page** (30%) - cała strona jako fallback

## Input

```json
{
  "urls": [
    "https://przychodnia-abc.pl/polityka-prywatnosci",
    "https://centrum-medyczne.pl/kontakt"
  ],
  "maxTextLength": 10000,
  "timeout": 30000
}
```

## Output

```json
[
  {
    "url": "https://przychodnia-abc.pl/polityka-prywatnosci",
    "text": "Administrator danych: PRZYCHODNIA ABC SP. Z O.O., NIP: 1234567890...",
    "textSource": "footer",
    "success": true,
    "textLength": 5432
  }
]
```

## Deployment

### Opcja A: Przez Apify Console (zalecane)

1. Przejdź na: https://console.apify.com/actors
2. Kliknij **+ Create new**
3. Template: **Empty project**
4. Nazwa: `nip-finder-web-scraper`
5. Skopiuj zawartość:
   - `main.js` → Main file
   - `package.json` → Package.json
   - `INPUT_SCHEMA.json` → Input schema
6. Kliknij **Build**
7. Po zbudowaniu: **Publish**
8. Skopiuj Actor ID (format: `username/nip-finder-web-scraper`)
9. Dodaj do `.env`:
   ```
   APIFY_SCRAPER_ACTOR_ID=username/nip-finder-web-scraper
   ```

### Opcja B: Przez Apify CLI

```bash
cd nip_finder/actors/web_scraper

# Inicjalizacja (jeśli nie zrobione)
apify login
apify init

# Deploy
apify push

# Test lokalny
apify run
```

## Test lokalny

Utwórz `test_input.json`:

```json
{
  "urls": [
    "https://www.nfz.gov.pl/kontakt"
  ]
}
```

Uruchom:

```bash
node main.js
```

## Wymagania

- Node.js >= 16
- Apify account
- ~$0.01 za stronę

## Troubleshooting

### Timeout errors
- Zwiększ `timeout` w input (default: 30s)
- Niektóre strony ładują się wolno

### Empty text
- Strona może wymagać JS do renderowania
- Playwright obsługuje JS, ale niektóre strony mogą mieć dodatkową ochronę

### Rate limiting
- Dodaj `await Apify.utils.sleep(1000)` między requests
- Użyj proxy (Apify ma wbudowane)
