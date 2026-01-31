"""
Batch Lead Processing - pełne przetwarzanie leadów z pliku XLS.

Dla każdego leada wykonuje:
1. Normalizacja AI (imię, nazwisko, firma)
2. Wyszukiwanie NIP (NIPFinderV3) + zbieranie danych ze strony WWW
3. Lookup GUS (dane rejestrowe)
4. Analiza Company Intel CORE (placówki, kontakty, specjalizacja)
5. Deduplikacja Zoho CRM

Wyniki zapisuje do nowego pliku XLSX z pełnymi danymi.
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Wyłącz verbose logi
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apify_client").setLevel(logging.WARNING)


class LeadBatchProcessor:
    """Procesor batch dla leadów z pliku XLS."""
    
    def __init__(
        self,
        skip_zoho: bool = False,
        skip_company_intel: bool = False,
        core_only: bool = True,  # Domyślnie tylko CORE (bez social/reviews)
    ):
        self.skip_zoho = skip_zoho
        self.skip_company_intel = skip_company_intel
        self.core_only = core_only
        
        # Inicjalizacja serwisów (lazy)
        self._normalizer = None
        self._company_intel = None
    
    async def _get_normalizer(self):
        """Lazy init DataNormalizerService."""
        if self._normalizer is None:
            from src.services.data_normalizer import DataNormalizerService
            self._normalizer = DataNormalizerService(use_mocks=False)
        return self._normalizer
    
    async def _get_company_intel(self):
        """Lazy init CompanyIntelOrchestrator."""
        if self._company_intel is None:
            from company_intel.orchestrator import CompanyIntelOrchestrator
            self._company_intel = CompanyIntelOrchestrator()
        return self._company_intel
    
    async def close(self):
        """Zamknij wszystkie serwisy."""
        if self._normalizer:
            await self._normalizer.close()
        if self._company_intel:
            await self._company_intel.close()
    
    async def process_single_lead(self, row: dict) -> dict:
        """
        Przetwarza pojedynczy lead.
        
        Args:
            row: Dict z danymi leada z XLS
            
        Returns:
            Dict z wynikami przetwarzania
        """
        start_time = time.time()
        result = {
            "input": row,
            "success": False,
            "processing_time_ms": 0,
            "errors": [],
            "warnings": [],
        }
        
        try:
            # === ETAP 1: Normalizacja + NIP + GUS ===
            normalizer = await self._get_normalizer()
            
            # Przygotuj dane wejściowe
            raw_data = {
                "company": row.get("company") or row.get("firma") or row.get("Company") or row.get("Firma"),
                "first_name": row.get("first_name") or row.get("imie") or row.get("First_Name") or row.get("Imię"),
                "last_name": row.get("last_name") or row.get("nazwisko") or row.get("Last_Name") or row.get("Nazwisko"),
                "email": row.get("email") or row.get("Email") or row.get("e-mail"),
                "phone": row.get("phone") or row.get("telefon") or row.get("Phone") or row.get("Telefon"),
                "nip": row.get("nip") or row.get("NIP"),
                "city": row.get("city") or row.get("miasto") or row.get("City") or row.get("Miasto"),
                "address": row.get("address") or row.get("adres") or row.get("Address") or row.get("Adres"),
            }
            
            # Normalizacja + NIP + GUS
            lead_result = await normalizer.process_lead(
                raw_data=raw_data,
                skip_ai=False,
                skip_gus=False,
                skip_duplicates=self.skip_zoho,
            )
            
            result["normalized"] = lead_result.normalized.model_dump() if lead_result.normalized else None
            result["gus_data"] = lead_result.gus_data.model_dump() if lead_result.gus_data else None
            result["duplicates"] = lead_result.duplicates.model_dump() if lead_result.duplicates else None
            result["recommendation"] = lead_result.recommendation.model_dump() if lead_result.recommendation else None
            result["warnings"].extend(lead_result.warnings)
            
            # Pobierz scraped_data jeśli jest
            scraped_data = normalizer.get_scraped_company_data()
            if scraped_data:
                result["scraped_contacts"] = {
                    "domain": scraped_data.domain,
                    "emails": scraped_data.emails[:5],
                    "phones": scraped_data.phones[:5],
                    "addresses": scraped_data.addresses[:3],
                    "social_links": scraped_data.social_links,
                }
            
            # === ETAP 2: Company Intel (opcjonalnie) ===
            if not self.skip_company_intel:
                nip = lead_result.normalized.nip if lead_result.normalized else None
                company_name = lead_result.normalized.company_name if lead_result.normalized else raw_data.get("company")
                
                if nip or company_name:
                    try:
                        ci = await self._get_company_intel()
                        
                        if nip:
                            # Analiza po NIP (pełniejsza)
                            ci_result = await ci.analyze_by_nip(
                                nip=nip,
                                skip_social=self.core_only,
                                skip_ai=False,
                                skip_reviews=self.core_only,
                                core_only=self.core_only,
                            )
                        else:
                            # Analiza po nazwie
                            ci_result = await ci.analyze(
                                company_name=company_name,
                                city=raw_data.get("city"),
                                skip_social=self.core_only,
                                skip_ai=False,
                                skip_reviews=self.core_only,
                                core_only=self.core_only,
                            )
                        
                        result["company_intel"] = {
                            "nazwa_pelna": ci_result.nazwa_pelna,
                            "nazwa_zwyczajowa": ci_result.nazwa_zwyczajowa,
                            "nip": ci_result.nip,
                            "regon": ci_result.regon,
                            "kategoryzacja": ci_result.kategoryzacja.model_dump() if ci_result.kategoryzacja else None,
                            "placowki_count": len(ci_result.placowki),
                            "placowki": [
                                {
                                    "nazwa": p.nazwa,
                                    "adres": str(p.adres) if p.adres else None,
                                    "miasto": p.adres.miasto if p.adres else None,
                                    "google_rating": p.google_rating,
                                    "google_reviews_count": p.google_reviews_count,
                                    "kontakty": [k.wartosc for k in (p.kontakty or [])[:3]],
                                }
                                for p in (ci_result.placowki or [])[:5]
                            ],
                            "social_media": ci_result.social_media.to_dict() if ci_result.social_media else None,
                            "activity_score": ci_result.activity_score.total if ci_result.activity_score else None,
                            "activity_recommendation": ci_result.activity_score.recommendation.value if ci_result.activity_score else None,
                            "sources_used": ci_result.metadata.sources_used if ci_result.metadata else [],
                        }
                        
                        if ci_result.metadata and ci_result.metadata.warnings:
                            result["warnings"].extend(ci_result.metadata.warnings)
                            
                    except Exception as e:
                        result["warnings"].append(f"Company Intel failed: {str(e)}")
            
            result["success"] = True
            
        except Exception as e:
            logger.exception("Error processing lead: %s", e)
            result["errors"].append(str(e))
        
        result["processing_time_ms"] = int((time.time() - start_time) * 1000)
        return result
    
    async def process_file(
        self,
        input_file: str,
        output_file: Optional[str] = None,
        max_rows: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Przetwarza plik XLS/XLSX z leadami.
        
        Args:
            input_file: Ścieżka do pliku wejściowego
            output_file: Ścieżka do pliku wyjściowego (opcjonalna)
            max_rows: Maksymalna liczba wierszy do przetworzenia
            
        Returns:
            DataFrame z wynikami
        """
        logger.info("=" * 60)
        logger.info("BATCH LEAD PROCESSING")
        logger.info("=" * 60)
        logger.info(f"Input file: {input_file}")
        
        # Wczytaj plik
        if input_file.endswith(".xlsx") or input_file.endswith(".xls"):
            df = pd.read_excel(input_file)
        elif input_file.endswith(".csv"):
            df = pd.read_csv(input_file)
        else:
            raise ValueError(f"Unsupported file format: {input_file}")
        
        logger.info(f"Loaded {len(df)} rows")
        logger.info(f"Columns: {list(df.columns)}")
        
        if max_rows:
            df = df.head(max_rows)
            logger.info(f"Processing first {max_rows} rows")
        
        # Przetwarzaj każdy wiersz
        results = []
        total_start = time.time()
        
        for idx, row in df.iterrows():
            row_dict = row.to_dict()
            logger.info(f"\n--- Processing row {idx + 1}/{len(df)} ---")
            
            # Pokaż co przetwarzamy
            company = row_dict.get("company") or row_dict.get("firma") or row_dict.get("Company") or "N/A"
            email = row_dict.get("email") or row_dict.get("Email") or "N/A"
            logger.info(f"Company: {company}, Email: {email}")
            
            result = await self.process_single_lead(row_dict)
            results.append(result)
            
            # Pokaż postęp
            if result["success"]:
                normalized = result.get("normalized", {})
                nip = normalized.get("nip_formatted") if normalized else None
                company_name = normalized.get("company_name") if normalized else None
                
                dups = result.get("duplicates", {})
                contact_exists = dups.get("contact", {}).get("exists", False) if dups else False
                account_exists = dups.get("account", {}).get("exists", False) if dups else False
                
                ci = result.get("company_intel", {})
                activity_score = ci.get("activity_score") if ci else None
                placowki_count = ci.get("placowki_count", 0) if ci else 0
                
                logger.info(f"  ✓ NIP: {nip or 'nie znaleziono'}")
                logger.info(f"  ✓ Firma: {company_name or 'N/A'}")
                logger.info(f"  ✓ Zoho: Contact={contact_exists}, Account={account_exists}")
                logger.info(f"  ✓ Intel: {placowki_count} placówek, score={activity_score}")
                logger.info(f"  ✓ Time: {result['processing_time_ms']}ms")
            else:
                logger.error(f"  ✗ Errors: {result['errors']}")
        
        total_time = time.time() - total_start
        
        # Zamknij serwisy
        await self.close()
        
        # Przygotuj wynikowy DataFrame
        output_rows = []
        for r in results:
            inp = r.get("input", {})
            norm = r.get("normalized", {}) or {}
            gus = r.get("gus_data", {}) or {}
            dups = r.get("duplicates", {}) or {}
            rec = r.get("recommendation", {}) or {}
            scraped = r.get("scraped_contacts", {}) or {}
            ci = r.get("company_intel", {}) or {}
            
            output_rows.append({
                # Input
                "input_company": inp.get("company") or inp.get("firma") or inp.get("Company"),
                "input_email": inp.get("email") or inp.get("Email"),
                "input_phone": inp.get("phone") or inp.get("telefon"),
                "input_nip": inp.get("nip") or inp.get("NIP"),
                
                # Normalizacja
                "normalized_first_name": norm.get("first_name"),
                "normalized_last_name": norm.get("last_name"),
                "normalized_company": norm.get("company_name"),
                "normalized_email": norm.get("email"),
                "normalized_phone": norm.get("phone"),
                "normalized_nip": norm.get("nip"),
                "nip_formatted": norm.get("nip_formatted"),
                "nip_valid": norm.get("nip_valid"),
                
                # GUS
                "gus_found": gus.get("found"),
                "gus_full_name": gus.get("full_name"),
                "gus_regon": gus.get("regon"),
                "gus_city": gus.get("city"),
                "gus_street": gus.get("street"),
                
                # Scraped data
                "scraped_domain": scraped.get("domain"),
                "scraped_emails": ", ".join(scraped.get("emails", [])[:3]),
                "scraped_phones": ", ".join(scraped.get("phones", [])[:3]),
                "scraped_facebook": scraped.get("social_links", {}).get("facebook"),
                "scraped_instagram": scraped.get("social_links", {}).get("instagram"),
                
                # Zoho duplicates
                "zoho_contact_exists": dups.get("contact", {}).get("exists"),
                "zoho_contact_id": dups.get("contact", {}).get("primary_id"),
                "zoho_account_exists": dups.get("account", {}).get("exists"),
                "zoho_account_id": dups.get("account", {}).get("parent_id"),
                
                # Recommendation
                "recommendation_action": rec.get("action"),
                "recommendation_confidence": rec.get("confidence"),
                "recommendation_reason": rec.get("reason"),
                
                # Company Intel
                "ci_nazwa_pelna": ci.get("nazwa_pelna"),
                "ci_kategoryzacja_industry": ci.get("kategoryzacja", {}).get("industry") if ci.get("kategoryzacja") else None,
                "ci_kategoryzacja_specjalizacja": ", ".join(ci.get("kategoryzacja", {}).get("specjalizacja", [])) if ci.get("kategoryzacja") else None,
                "ci_placowki_count": ci.get("placowki_count"),
                "ci_activity_score": ci.get("activity_score"),
                "ci_activity_recommendation": ci.get("activity_recommendation"),
                "ci_sources": ", ".join(ci.get("sources_used", [])),
                
                # Meta
                "success": r.get("success"),
                "processing_time_ms": r.get("processing_time_ms"),
                "warnings": "; ".join(r.get("warnings", [])[:3]),
                "errors": "; ".join(r.get("errors", [])),
            })
        
        result_df = pd.DataFrame(output_rows)
        
        # Zapisz do pliku
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"batch_results_{timestamp}.xlsx"
        
        result_df.to_excel(output_file, index=False)
        logger.info(f"\nResults saved to: {output_file}")
        
        # Podsumowanie
        logger.info("\n" + "=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total rows: {len(results)}")
        logger.info(f"Successful: {sum(1 for r in results if r['success'])}")
        logger.info(f"Failed: {sum(1 for r in results if not r['success'])}")
        logger.info(f"Total time: {total_time:.1f}s")
        logger.info(f"Avg time per lead: {total_time / len(results):.1f}s")
        
        # Statystyki NIP
        nip_found = sum(1 for r in results if r.get("normalized", {}) and r["normalized"].get("nip"))
        logger.info(f"NIP found: {nip_found}/{len(results)} ({100 * nip_found / len(results):.0f}%)")
        
        # Statystyki Zoho
        if not self.skip_zoho:
            contact_exists = sum(1 for r in results if r.get("duplicates", {}).get("contact", {}).get("exists"))
            account_exists = sum(1 for r in results if r.get("duplicates", {}).get("account", {}).get("exists"))
            logger.info(f"Zoho Contact exists: {contact_exists}/{len(results)}")
            logger.info(f"Zoho Account exists: {account_exists}/{len(results)}")
        
        return result_df


async def main():
    """Główna funkcja - przetwarza plik z argumentu lub domyślny."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Batch Lead Processing")
    parser.add_argument("input_file", nargs="?", default="companies_data_test.xlsx", help="Input XLS/XLSX file")
    parser.add_argument("-o", "--output", help="Output file (default: batch_results_TIMESTAMP.xlsx)")
    parser.add_argument("-n", "--max-rows", type=int, help="Max rows to process")
    parser.add_argument("--skip-zoho", action="store_true", help="Skip Zoho duplicate check")
    parser.add_argument("--skip-intel", action="store_true", help="Skip Company Intel analysis")
    parser.add_argument("--full-intel", action="store_true", help="Full Company Intel (with social/reviews)")
    
    args = parser.parse_args()
    
    processor = LeadBatchProcessor(
        skip_zoho=args.skip_zoho,
        skip_company_intel=args.skip_intel,
        core_only=not args.full_intel,
    )
    
    try:
        await processor.process_file(
            input_file=args.input_file,
            output_file=args.output,
            max_rows=args.max_rows,
        )
    finally:
        await processor.close()


if __name__ == "__main__":
    asyncio.run(main())
