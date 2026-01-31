import asyncio
import json
import logging
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

# Zaladuj zmienne srodowiskowe z .env PRZED wszystkim
from dotenv import load_dotenv
load_dotenv()

# Wycisz warningi przed importami
warnings.filterwarnings("ignore")
os.environ["APIFY_LOG_LEVEL"] = "ERROR"
os.environ["PYTHONWARNINGS"] = "ignore"

from company_intel.orchestrator import CompanyIntelOrchestrator


# =============================================================================
# KONFIGURACJA FIRM DO TESTOWANIA
# =============================================================================

COMPANIES = [
    {
        "name": "ProBody Clinic",
        "nip": "5842809779",
        "website": "https://spaprobody.pl/"
    },
    {
        "name": "Klinika Ambroziak",
        "nip": "1231243387",
        "website": "https://klinikaambroziak.pl"
    },
    {
        "name": "Aldent Wroclaw",
        "nip": "8941864949",
        "website": "https://aldent.wroclaw.pl"
    },
]


# =============================================================================
# OUTPUT FOLDER
# =============================================================================

TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
OUTPUT_DIR = Path(f"analysis_runs/batch_{TIMESTAMP}")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = OUTPUT_DIR / "batch.log"

# Otwieramy plik na logi
log_file_handle = open(LOG_FILE, "w", encoding="utf-8")

# File handler
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S"
))

logging.basicConfig(level=logging.DEBUG, handlers=[file_handler])

# Redirect stdout/stderr to log file
class LogRedirect:
    def __init__(self, file):
        self.file = file
        self.original = None
    def write(self, msg):
        if msg.strip():
            self.file.write(msg)
    def flush(self):
        self.file.flush()

sys.stdout = LogRedirect(log_file_handle)
sys.stderr = LogRedirect(log_file_handle)


def pout(msg: str):
    """Print to terminal (bypassing redirect)."""
    sys.__stdout__.write(msg + "\n")
    sys.__stdout__.flush()


def progress(step: int, total: int, company: str, stage: str, status: str = "...", elapsed: float = 0):
    """Print progress bar to terminal."""
    pct = int(step / total * 100)
    bar_len = 30
    filled = int(bar_len * step / total)
    bar = "#" * filled + "-" * (bar_len - filled)
    line = f"\r[{bar}] {pct:3d}% | {company[:20]:<20} | {stage[:35]:<35} | {status}"
    sys.__stdout__.write(line)
    sys.__stdout__.flush()


async def analyze_company(orchestrator, company: dict, company_dir: Path) -> dict:
    """
    Analyze a single company - NIP vs Website comparison.
    
    WAŻNE: Każda analiza dostaje TYLKO jeden punkt wejścia:
    - Analiza NIP: tylko NIP, musi sam znaleźć website
    - Analiza Website: tylko website, musi sam znaleźć NIP
    """
    results = {
        "name": company["name"],
        "input_nip": company["nip"],
        "input_website": company["website"],
        "nip_analysis": None,
        "website_analysis": None,
    }
    
    # === ANALIZA PO NIP (tylko NIP, bez website) ===
    pout(f"\n  [NIP] Analyzing by NIP only: {company['nip']}...")
    pout(f"        (must find website on its own)")
    try:
        # analyze_by_nip: NIP -> GUS -> szuka website -> pełna analiza
        # UWAGA: skip_reviews=True bo analityka opinii kosztuje dużo API (wiemy że działa)
        result = await orchestrator.analyze_by_nip(
            nip=company["nip"],
            skip_social=False,
            skip_reviews=True  # ZAPAUZOWANE w testach - nie usunięte
        )
        results["nip_analysis"] = result.to_dict()
        
        # Zapisz do pliku
        with open(company_dir / "results_NIP.json", "w", encoding="utf-8") as f:
            json.dump(results["nip_analysis"], f, ensure_ascii=False, indent=2)
        
        found_website = result.social_media.website if result.social_media else None
        pout(f"  [NIP] Done - {len(result.placowki)} placowek, score: {result.activity_score}")
        pout(f"        Found website: {found_website or 'NIE ZNALEZIONO'}")
    except Exception as e:
        pout(f"  [NIP] Error: {e}")
        results["nip_analysis"] = {"error": str(e)}
    
    # === ANALIZA PO WEBSITE (tylko website, bez NIP) ===
    pout(f"\n  [WEB] Analyzing by Website only: {company['website']}...")
    pout(f"        (must find NIP on its own)")
    try:
        result = await orchestrator.analyze(
            website=company["website"],
            # NIE podajemy nip - musi sam znaleźć!
            skip_social=False,
            skip_reviews=True  # ZAPAUZOWANE w testach - nie usunięte
        )
        results["website_analysis"] = result.to_dict()
        
        # Zapisz do pliku
        with open(company_dir / "results_Website.json", "w", encoding="utf-8") as f:
            json.dump(results["website_analysis"], f, ensure_ascii=False, indent=2)
        
        pout(f"  [WEB] Done - {len(result.placowki)} placowek, score: {result.activity_score}")
        pout(f"        Found NIP: {result.nip or 'NIE ZNALEZIONO'}")
    except Exception as e:
        pout(f"  [WEB] Error: {e}")
        results["website_analysis"] = {"error": str(e)}
    
    return results


async def main():
    pout("=" * 70)
    pout(f"[*] BATCH ANALYSIS: {len(COMPANIES)} companies")
    pout(f"    Output: {OUTPUT_DIR}")
    pout("=" * 70)
    
    start_time = time.time()
    
    # Init orchestrator
    orchestrator = CompanyIntelOrchestrator()
    
    all_results = []
    
    for i, company in enumerate(COMPANIES, 1):
        pout(f"\n{'='*70}")
        pout(f"[{i}/{len(COMPANIES)}] {company['name']}")
        pout(f"    NIP: {company['nip'] or 'do znalezienia'}")
        pout(f"    Website: {company['website']}")
        pout("=" * 70)
        
        company_dir = OUTPUT_DIR / company["name"].replace(" ", "_").lower()
        company_dir.mkdir(parents=True, exist_ok=True)
        
        result = await analyze_company(orchestrator, company, company_dir)
        all_results.append(result)
        
        # Podsumowanie firmy
        pout(f"\n  [SUMMARY] {company['name']}:")
        if result["nip_analysis"] and "error" not in result["nip_analysis"]:
            nip_data = result["nip_analysis"]
            pout(f"    NIP:     {nip_data.get('placowki_count', '?')} placowek, score: {nip_data.get('activity_score', '?')}")
        if result["website_analysis"] and "error" not in result["website_analysis"]:
            web_data = result["website_analysis"]
            pout(f"    Website: {web_data.get('placowki_count', '?')} placowek, score: {web_data.get('activity_score', '?')}")
    
    # Zapisz zbiorcze wyniki
    with open(OUTPUT_DIR / "batch_summary.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - start_time
    
    pout(f"\n{'='*70}")
    pout(f"[DONE] Batch completed in {elapsed:.1f}s")
    pout(f"[OUT]  Results: {OUTPUT_DIR}")
    pout("=" * 70)
    
    # Close log file
    log_file_handle.close()


if __name__ == "__main__":
    asyncio.run(main())
