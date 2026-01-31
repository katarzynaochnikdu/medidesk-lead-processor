import asyncio
import io
import json
import logging
import os
import sys
import time
import warnings
from datetime import datetime
from contextlib import contextmanager, redirect_stdout, redirect_stderr

# Wycisz warningi przed importami
warnings.filterwarnings("ignore")
os.environ["APIFY_LOG_LEVEL"] = "ERROR"
os.environ["PYTHONWARNINGS"] = "ignore"

from company_intel.orchestrator import CompanyIntelOrchestrator


# =============================================================================
# LOGGING SETUP - logi do pliku, progress na terminal
# =============================================================================

LOG_FILE = f"analysis_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Otwieramy plik na logi (stdout/stderr z bibliotek tez tu pojda)
log_file_handle = open(LOG_FILE, "w", encoding="utf-8")

# File handler - szczegolowe logi
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S"
))

# Konfiguracja root loggera - tylko do pliku
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[file_handler]
)

# Wycisz szumy z bibliotek
for noisy in ["httpx", "httpcore", "urllib3", "apify_client", "apify", 
              "google", "vertexai", "grpc", "asyncio"]:
    logging.getLogger(noisy).setLevel(logging.CRITICAL)

logger = logging.getLogger("analysis")

# Zachowaj oryginalny stdout do progress bara
_real_stdout = sys.stdout
_real_stderr = sys.stderr


# =============================================================================
# PROGRESS BAR - prosty pasek na terminal
# =============================================================================

class ProgressBar:
    """Prosty pasek postępu na terminal."""
    
    def __init__(self, total_steps: int):
        self.total = total_steps
        self.current = 0
        self.current_step_name = ""
        self.step_start_time = None
        self.total_start_time = time.time()
    
    def start_step(self, name: str):
        """Rozpocznij nowy etap."""
        self.current += 1
        self.current_step_name = name
        self.step_start_time = time.time()
        logger.info(f"[START] {name}")
        self._render()
    
    def finish_step(self, extra_info: str = ""):
        """Zakończ bieżący etap."""
        elapsed = time.time() - self.step_start_time
        logger.info(f"[DONE]  {self.current_step_name} ({elapsed:.2f}s) {extra_info}")
        self._render(done=True, elapsed=elapsed)
    
    def _render(self, done: bool = False, elapsed: float = 0):
        """Renderuj pasek na terminalu."""
        pct = int((self.current / self.total) * 100)
        bar_len = 30
        filled = int(bar_len * self.current / self.total)
        bar = "#" * filled + "-" * (bar_len - filled)
        
        status = f"OK {elapsed:.1f}s" if done else "..."
        total_elapsed = time.time() - self.total_start_time
        
        line = f"\r[{bar}] {pct:3d}% | {self.current}/{self.total} | {self.current_step_name[:40]:<40} | {status} | Total: {total_elapsed:.1f}s"
        _real_stdout.write(line)
        _real_stdout.flush()
        if done:
            _real_stdout.write("\n")  # nowa linia po zakonczeniu etapu
            _real_stdout.flush()
    
    def finish_all(self):
        """Zakoncz caly proces."""
        total_elapsed = time.time() - self.total_start_time
        _real_stdout.write(f"\n{'='*70}\n")
        _real_stdout.write(f"[DONE] ZAKONCZONO | Calkowity czas: {total_elapsed:.2f}s\n")
        _real_stdout.write(f"[LOG]  Logi zapisane do: {LOG_FILE}\n")
        _real_stdout.write(f"{'='*70}\n")
        _real_stdout.flush()
        logger.info(f"[TOTAL] Calkowity czas: {total_elapsed:.2f}s")


@contextmanager
def timed_step(progress: ProgressBar, name: str):
    """Context manager do mierzenia czasu etapu."""
    progress.start_step(name)
    try:
        yield
    finally:
        progress.finish_step()


# =============================================================================
# MAIN ANALYSIS
# =============================================================================

def pout(msg: str):
    """Print to real stdout (terminal)."""
    _real_stdout.write(msg + "\n")
    _real_stdout.flush()


async def main():
    # Przekieruj stdout/stderr do pliku logow (Apify drukuje tam bezposrednio)
    sys.stdout = log_file_handle
    sys.stderr = log_file_handle
    
    pout(f"\n{'='*70}")
    pout(f"[*] ANALIZA POROWNAWCZA: Klinika OT.CO")
    pout(f"    NIP: 5213873364 | Website: https://klinikaotco.pl")
    pout(f"    Logi: {LOG_FILE}")
    pout(f"{'='*70}\n")
    
    # 6 głównych etapów
    progress = ProgressBar(total_steps=6)
    
    orchestrator = CompanyIntelOrchestrator()
    nip_result = None
    website_result = None
    
    try:
        # --- ETAP 1: Inicjalizacja ---
        with timed_step(progress, "Inicjalizacja orchestratora"):
            logger.debug(f"Orchestrator zainicjalizowany")
        
        # --- ETAP 2: Analiza po NIP ---
        with timed_step(progress, "Analiza po NIP (5213873364)"):
            nip_result = await orchestrator.analyze_by_nip(
                "5213873364",
                skip_social=True,
                skip_ai=False,
                skip_reviews=True,
                core_only=False,
            )
            logger.info(f"  → Znaleziono {len(nip_result.placowki)} placówek")
            logger.info(f"  → Activity score: {nip_result.activity_score.total}")
            logger.info(f"  → Źródła: {nip_result.metadata.sources_used}")
        
        # --- ETAP 3: Podsumowanie NIP ---
        with timed_step(progress, "Przygotowanie podsumowania NIP"):
            nip_summary = {
                "label": "OT.CO NIP",
                "sources": nip_result.metadata.sources_used,
                "placowki_count": len(nip_result.placowki),
                "activity_score_total": nip_result.activity_score.total,
                "activity_recommendation": nip_result.activity_score.recommendation.value,
                "signals": nip_result.activity_score.signals,
                "social_profiles": [p.to_dict() for p in nip_result.social_profiles],
                "addresses": [p.adres.to_dict() for p in nip_result.placowki],
            }
            logger.debug(f"NIP summary prepared: {len(nip_summary['addresses'])} addresses")
        
        # --- ETAP 4: Analiza po Website ---
        with timed_step(progress, "Analiza po Website (klinikaotco.pl)"):
            website_result = await orchestrator.analyze(
                company_name="Klinika OT.CO",
                website="https://klinikaotco.pl",
                skip_social=True,
                skip_ai=False,
                skip_reviews=True,
                core_only=False,
            )
            logger.info(f"  → Znaleziono {len(website_result.placowki)} placówek")
            logger.info(f"  → Activity score: {website_result.activity_score.total}")
            logger.info(f"  → Źródła: {website_result.metadata.sources_used}")
        
        # --- ETAP 5: Podsumowanie Website ---
        with timed_step(progress, "Przygotowanie podsumowania Website"):
            website_summary = {
                "label": "OT.CO Website",
                "sources": website_result.metadata.sources_used,
                "placowki_count": len(website_result.placowki),
                "activity_score_total": website_result.activity_score.total,
                "activity_recommendation": website_result.activity_score.recommendation.value,
                "signals": website_result.activity_score.signals,
                "social_profiles": [p.to_dict() for p in website_result.social_profiles],
                "addresses": [p.adres.to_dict() for p in website_result.placowki],
            }
            logger.debug(f"Website summary prepared: {len(website_summary['addresses'])} addresses")
        
        # --- ETAP 6: Zapis wyników ---
        with timed_step(progress, "Zapis wyników do JSON"):
            output = {
                "generated_at": datetime.now().isoformat(),
                "comparison": {
                    "nip": nip_summary,
                    "website": website_summary,
                },
                "differences": {
                    "placowki_nip": nip_summary["placowki_count"],
                    "placowki_website": website_summary["placowki_count"],
                    "activity_nip": nip_summary["activity_score_total"],
                    "activity_website": website_summary["activity_score_total"],
                }
            }
            with open("otco_analysis_results.json", "w", encoding="utf-8") as out:
                json.dump(output, out, ensure_ascii=False, indent=2)
            logger.info("Wyniki zapisane do otco_analysis_results.json")
        
        progress.finish_all()
        
        # Pokaz krotkie podsumowanie roznic
        pout(f"\n[SUMMARY] PODSUMOWANIE ROZNIC:")
        pout(f"   {'Metryka':<25} | {'NIP':>10} | {'Website':>10}")
        pout(f"   {'-'*25}-+-{'-'*10}-+-{'-'*10}")
        pout(f"   {'Liczba placowek':<25} | {nip_summary['placowki_count']:>10} | {website_summary['placowki_count']:>10}")
        pout(f"   {'Activity Score':<25} | {nip_summary['activity_score_total']:>10} | {website_summary['activity_score_total']:>10}")
        pout(f"   {'Liczba zrodel':<25} | {len(nip_summary['sources']):>10} | {len(website_summary['sources']):>10}")
        pout(f"\n[FILE] Pelne wyniki: otco_analysis_results.json")
        
    finally:
        await orchestrator.close()
        # Przywroc stdout/stderr
        sys.stdout = _real_stdout
        sys.stderr = _real_stderr
        log_file_handle.close()


if __name__ == "__main__":
    asyncio.run(main())
