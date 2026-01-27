@echo off
REM Uruchomienie lokalne serwisu Lead Processor
REM Wymaga zainstalowanych zależności: pip install -r requirements.txt

echo === Lead Processor - Local Development ===
echo.

REM Sprawdź czy istnieje .env
if not exist .env (
    echo [WARN] Brak pliku .env - kopiuję z .env.example
    copy .env.example .env
    echo [INFO] Edytuj plik .env i uzupełnij dane
    pause
    exit /b 1
)

REM Aktywuj venv jeśli istnieje
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

REM Ustaw zmienne dla developmentu
set ENVIRONMENT=development
set LOG_LEVEL=DEBUG

echo [INFO] Starting server on http://localhost:8080
echo [INFO] API docs: http://localhost:8080/docs
echo.

python -m uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
