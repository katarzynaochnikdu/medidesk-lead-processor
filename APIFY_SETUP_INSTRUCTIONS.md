# Instrukcje Setup Apify dla NIP Finder

## Krok 1: Załóż konto Apify

1. Przejdź na https://apify.com/
2. Kliknij "Sign up" i załóż konto (można użyć Google/GitHub)
3. **Free tier**: $5 credit miesięcznie (wystarczy na ~2000 Google searches + 500 scrapes)

## Krok 2: Pobierz API Token

1. Po zalogowaniu przejdź do: **Settings** → **Integrations**
2. W sekcji **Personal API tokens** kliknij **+ New token**
3. Nazwa: `nip-finder-token`
4. Skopiuj wygenerowany token (zaczyna się od `apify_api_`)

## Krok 3: Dodaj token do .env

W pliku `.env` w głównym folderze projektu dodaj:

```bash
# Apify
APIFY_API_TOKEN=apify_api_xxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Krok 4: Znajdź gotowe Actors w Apify Store

### Actor 1: Google Search Scraper (gotowy, darmowy)

1. Przejdź na: https://apify.com/apify/google-search-scraper
2. Ten Actor jest już gotowy do użycia!
3. Actor ID: `apify/google-search-scraper`
4. Dodaj do `.env`:
   ```bash
   APIFY_GOOGLE_ACTOR_ID=apify/google-search-scraper
   ```

### Actor 2: Web Scraper (stworzymy własny)

Utworzymy Custom Actor do głębokiego scrapingu stron.
Instrukcje poniżej.

## Krok 5: Zainstaluj Apify CLI (opcjonalne, do tworzenia Actors)

```bash
npm install -g apify-cli
apify login
```

Podaj API token z kroku 2.

## Krok 6: Test gotowego Google Search Actor

Przetestuj czy API działa:

```bash
cd nip_finder
python -c "
from apify_client import ApifyClient
client = ApifyClient('TWÓJ_TOKEN')
run = client.actor('apify/google-search-scraper').call(
    run_input={'queries': 'VITA MEDICA Siedlce NIP'}
)
print('Success!', run)
"
```

## Krok 7: Utworzenie Custom Web Scraper Actor

### Opcja A: Przez Apify Console (łatwiejsze)

1. Przejdź do: https://console.apify.com/actors
2. Kliknij **+ Create new**
3. Template: **Playwright + Python** lub **Playwright + JavaScript**
4. Nazwa: `nip-finder-web-scraper`
5. Skopiuj kod z `nip_finder/actors/web_scraper/main.js` (utworzymy w następnym kroku)
6. Deploy Actor
7. Skopiuj Actor ID (format: `twoja_nazwa/nip-finder-web-scraper`)
8. Dodaj do `.env`:
   ```bash
   APIFY_SCRAPER_ACTOR_ID=twoja_nazwa/nip-finder-web-scraper
   ```

### Opcja B: Przez CLI (dla zaawansowanych)

```bash
cd nip_finder/actors/web_scraper
apify init
apify push
```

## Gotowe!

Po wykonaniu tych kroków będziesz mógł używać NIP Finder.

## Koszty (orientacyjne)

- **Google Search**: ~$0.002 za jedno wyszukiwanie
- **Web Scraper**: ~$0.01 za stronę
- **Przykład**: 100 firm × 5 queries × 10 scrapes = ~$6

**Free tier ($5/miesiąc)** wystarcza na:
- ~2000 wyszukiwań Google
- ~500 scrapowanych stron
- Czyli ~40-50 firm z pełnym flow

## Troubleshooting

### "Unauthorized" error
- Sprawdź czy token w `.env` jest poprawny
- Token musi zaczynać się od `apify_api_`

### "Actor not found"
- Sprawdź czy Actor ID jest poprawne
- Format: `username/actor-name` lub `apify/actor-name`

### Rate limit exceeded
- Free tier ma limity
- Upgrade do płatnego planu lub poczekaj do następnego miesiąca
