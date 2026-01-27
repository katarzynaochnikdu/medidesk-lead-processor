@echo off
REM Tworzenie środowiska wirtualnego i instalacja zależności

echo === Setup Virtual Environment ===
echo.

REM Utwórz venv
python -m venv .venv

REM Aktywuj
call .venv\Scripts\activate.bat

REM Upgrade pip
python -m pip install --upgrade pip

REM Zainstaluj zależności
pip install -r requirements.txt

echo.
echo === Setup Complete ===
echo.
echo Aktywuj środowisko: .venv\Scripts\activate.bat
echo Uruchom serwer: run_local.bat
