"""
CLI interface dla NIP Finder.

Commands:
- nip-finder single - pojedyncze wyszukiwanie
- nip-finder batch - batch processing z CSV
- nip-finder cache - zarzadzanie cache
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import click
import pandas as pd

from .config import get_nip_finder_settings
from .models import BatchNIPResult, NIPRequest
from .orchestrator import NIPFinder
from .output_handler import OutputHandler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

logger = logging.getLogger(__name__)


@click.group()
@click.version_option(version="0.1.0", prog_name="nip-finder")
def cli():
    """
    NIP Finder - wyszukiwanie NIP firm na podstawie minimalnych danych.
    
    Przyklady uzycia:
    
    \b
    # Pojedyncze wyszukiwanie
    nip-finder single --name "VITA MEDICA SIEDLCE" --city "Siedlce"
    
    \b
    # Batch processing z CSV
    nip-finder batch input.csv --output results.csv
    
    \b
    # Stats cache
    nip-finder cache stats
    """
    pass


@cli.command()
@click.option("--name", "-n", required=True, help="Nazwa firmy")
@click.option("--city", "-c", help="Miasto (opcjonalne)")
@click.option("--email", "-e", help="Email (opcjonalne)")
@click.option("--skip-cache", is_flag=True, help="Pomin cache")
@click.option("--output", "-o", help="Zapisz do pliku JSON")
def single(name: str, city: str, email: str, skip_cache: bool, output: str):
    """
    Wyszukaj NIP dla pojedynczej firmy.
    
    Przyklad:
    \b
    nip-finder single --name "VITA MEDICA SIEDLCE" --city "Siedlce"
    """
    
    async def run():
        click.echo(f"[SEARCH] Szukam NIP dla: {name}")
        
        finder = NIPFinder()
        
        result = await finder.find_nip(
            company_name=name,
            city=city,
            email=email,
            skip_cache=skip_cache,
        )
        
        # Wyswietl wynik
        click.echo("\n" + "="*60)
        if result.found:
            click.secho(f"[OK] NIP ZNALEZIONY", fg="green", bold=True)
            click.echo(f"\n  Firma: {result.company_name}")
            if result.city:
                click.echo(f"  Miasto: {result.city}")
            click.echo(f"\n  NIP: {result.nip_formatted or result.nip}")
            click.echo(f"  Confidence: {result.confidence:.2%}")
            click.echo(f"  Strategia: {result.strategy_used}")
            
            if result.source:
                click.echo(f"  Zrodlo: {result.source.url}")
            
            if result.validation:
                click.echo(f"\n  WALIDACJA:")
                click.echo(f"    Checksum: {'[OK]' if result.validation.valid_checksum else '[FAIL]'}")
                if result.validation.vat_active is not None:
                    click.echo(f"    VAT aktywny: {'[OK]' if result.validation.vat_active else '[FAIL]'}")
                if result.validation.gus_name:
                    click.echo(f"    GUS nazwa: {result.validation.gus_name}")
                    if result.validation.name_match_score:
                        click.echo(f"    Match score: {result.validation.name_match_score:.2%}")
                click.echo(f"    Zwalidowany: {'[OK]' if result.validation.validated else '[WARN]'}")
            
            if result.ai_reasoning:
                click.echo(f"\n  AI reasoning: {result.ai_reasoning}")
            
        else:
            click.secho(f"[FAIL] NIP NIE ZNALEZIONY", fg="red", bold=True)
            if result.errors:
                click.echo(f"\n  Bledy:")
                for error in result.errors:
                    click.echo(f"    - {error}")
        
        if result.warnings:
            click.echo(f"\n  Ostrzezenia:")
            for warning in result.warnings:
                click.echo(f"    - {warning}")
        
        click.echo(f"\n  Czas: {result.processing_time_ms}ms")
        click.echo("="*60)
        
        # Zapisz do pliku jesli podano
        if output:
            with open(output, "w", encoding="utf-8") as f:
                json.dump(result.model_dump(), f, indent=2, ensure_ascii=False, default=str)
            click.echo(f"\n[SAVED] Zapisano do: {output}")
        
        await finder.close()
    
    asyncio.run(run())


@cli.command()
@click.argument("input_csv", type=click.Path(exists=True))
@click.option("--output", "-o", default="results.csv", help="Plik CSV z wynikami")
@click.option("--report", "-r", help="Plik MD z raportem szczegolowym")
@click.option("--json-output", "-j", help="Plik JSON z wynikami")
@click.option("--max-concurrent", "-m", default=5, type=int, help="Maksymalna liczba rownoleglych zapytan")
@click.option("--name-column", default="company_name", help="Nazwa kolumny z nazwa firmy")
@click.option("--city-column", default="city", help="Nazwa kolumny z miastem")
@click.option("--email-column", default="email", help="Nazwa kolumny z emailem")
def batch(input_csv: str, output: str, report: str, json_output: str, max_concurrent: int, 
          name_column: str, city_column: str, email_column: str):
    """
    Batch processing z pliku CSV.
    
    CSV musi zawierac kolumny: company_name, city (opcjonalne), email (opcjonalne).
    
    Przyklad:
    \b
    nip-finder batch input.csv --output results.csv --report report.md
    """
    
    async def run():
        click.echo(f"[BATCH] Batch processing: {input_csv}")
        
        # Wczytaj CSV
        try:
            df = pd.read_csv(input_csv, encoding="utf-8")
        except:
            # Fallback: try utf-8-sig (Excel z BOM)
            df = pd.read_csv(input_csv, encoding="utf-8-sig")
        
        total_rows = len(df)
        click.echo(f"[INFO] Wczytano {total_rows} wierszy")
        
        # Walidacja kolumn
        if name_column not in df.columns:
            click.secho(f"[ERROR] Brak kolumny '{name_column}' w CSV", fg="red")
            return
        
        # Przygotuj requests
        requests = []
        for _, row in df.iterrows():
            req = NIPRequest(
                company_name=str(row[name_column]) if pd.notna(row.get(name_column)) else "",
                city=str(row[city_column]) if city_column in row and pd.notna(row.get(city_column)) else None,
                email=str(row[email_column]) if email_column in row and pd.notna(row.get(email_column)) else None,
            )
            requests.append(req)
        
        # Filtruj puste
        requests = [r for r in requests if r.company_name.strip()]
        click.echo(f"[INFO] Do przetworzenia: {len(requests)} firm")
        
        # Batch processing
        finder = NIPFinder()
        
        click.echo(f"\n[START] Processing (max concurrent: {max_concurrent})...")
        
        with click.progressbar(length=len(requests), label="Processing") as bar:
            async def process_with_progress(reqs):
                results = []
                for i, req in enumerate(reqs):
                    result = await finder.find_nip_from_request(req)
                    results.append(result)
                    bar.update(1)
                return results
            
            results = await process_with_progress(requests)
        
        await finder.close()
        
        # Statystyki
        successful = sum(1 for r in results if r.found)
        failed = len(results) - successful
        
        avg_confidence = sum(r.confidence for r in results if r.found) / successful if successful > 0 else 0
        avg_time = sum(r.processing_time_ms for r in results) / len(results) if results else 0
        
        # Strategy stats
        strategy_stats = {}
        for r in results:
            if r.found and r.strategy_used:
                strategy_stats[r.strategy_used] = strategy_stats.get(r.strategy_used, 0) + 1
        
        # Batch result
        batch_result = BatchNIPResult(
            total=len(results),
            successful=successful,
            failed=failed,
            results=results,
            avg_confidence=avg_confidence,
            avg_processing_time_ms=int(avg_time),
            strategy_stats=strategy_stats,
        )
        
        # Wyswietl podsumowanie
        click.echo("\n" + "="*60)
        click.secho("[SUMMARY] PODSUMOWANIE", fg="cyan", bold=True)
        click.echo("="*60)
        click.echo(f"[OK] Znaleziono NIP: {successful}/{len(results)} ({successful/len(results)*100:.1f}%)")
        click.echo(f"[FAIL] Nie znaleziono: {failed}/{len(results)} ({failed/len(results)*100:.1f}%)")
        click.echo(f"[INFO] Srednia confidence: {avg_confidence:.2%}")
        click.echo(f"[TIME] Sredni czas: {avg_time:.0f}ms")
        
        if strategy_stats:
            click.echo(f"\n[STATS] Strategie:")
            for strategy, count in sorted(strategy_stats.items(), key=lambda x: -x[1]):
                click.echo(f"  - {strategy}: {count} ({count/successful*100:.1f}%)")
        
        click.echo("="*60)
        
        # Zapisz outputs
        OutputHandler.generate_csv(results, output)
        click.secho(f"\n[SAVED] CSV zapisany: {output}", fg="green")
        
        if json_output:
            OutputHandler.generate_json(results, json_output)
            click.secho(f"[SAVED] JSON zapisany: {json_output}", fg="green")
        
        if report:
            OutputHandler.generate_detailed_report(results, report)
            click.secho(f"[SAVED] Report zapisany: {report}", fg="green")
        
        click.echo(f"\n[DONE] Batch processing zakonczony!")
    
    asyncio.run(run())


@cli.group()
def cache():
    """Zarzadzanie cache."""
    pass


@cache.command()
def stats():
    """Wyswietl statystyki cache."""
    
    async def run():
        from .cache import NIPCache
        
        cache_obj = NIPCache()
        stats_data = await cache_obj.stats()
        await cache_obj.close()
        
        click.echo("\n" + "="*60)
        click.secho("[CACHE] CACHE STATISTICS", fg="cyan", bold=True)
        click.echo("="*60)
        click.echo(f"  Total entries: {stats_data.get('total_entries', 0)}")
        click.echo(f"  Found: {stats_data.get('found', 0)}")
        click.echo(f"  Not found: {stats_data.get('not_found', 0)}")
        click.echo(f"  Expired: {stats_data.get('expired', 0)}")
        click.echo(f"  TTL: {stats_data.get('ttl_days', 0)} days")
        click.echo("="*60)
    
    asyncio.run(run())


@cache.command()
def clear():
    """Usun wygasle wpisy z cache."""
    
    async def run():
        from .cache import NIPCache
        
        cache_obj = NIPCache()
        
        click.echo("[CLEAN] Czyszczenie cache...")
        await cache_obj.clear_expired()
        await cache_obj.close()
        
        click.secho("[OK] Cache wyczyszczony!", fg="green")
    
    asyncio.run(run())


if __name__ == "__main__":
    cli()
