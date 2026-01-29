"""
Output handlers - generowanie różnych formatów outputu:
- CSV (do Excel)
- JSON (dla API)
- Detailed Report (Markdown)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from .models import BatchNIPResult, NIPResult

logger = logging.getLogger(__name__)


class OutputHandler:
    """
    Handler do generowania różnych formatów output.
    """
    
    @staticmethod
    def generate_csv(
        results: List[NIPResult],
        output_path: str,
    ):
        """
        Generuje plik CSV z wynikami.
        
        Args:
            results: Lista NIPResult
            output_path: Ścieżka do pliku CSV
        """
        logger.info("📄 Generuję CSV: %s", output_path)
        
        # Przygotuj dane do DataFrame
        rows = []
        for result in results:
            row = {
                "company_name": result.company_name,
                "city": result.city or "",
                "nip": result.nip or "",
                "nip_formatted": result.nip_formatted or "",
                "found": "TAK" if result.found else "NIE",
                "confidence": f"{result.confidence:.2f}",
                "strategy": result.strategy_used or "",
                "source_url": result.source.url if result.source else "",
                "valid_checksum": "TAK" if result.validation and result.validation.valid_checksum else "",
                "vat_active": "TAK" if result.validation and result.validation.vat_active else ("NIE" if result.validation and result.validation.vat_active is False else ""),
                "gus_name": result.validation.gus_name if result.validation else "",
                "name_match_score": f"{result.validation.name_match_score:.2f}" if result.validation and result.validation.name_match_score else "",
                "validated": "TAK" if result.validation and result.validation.validated else "NIE",
                "processing_time_ms": result.processing_time_ms,
                "errors": "; ".join(result.errors) if result.errors else "",
                "warnings": "; ".join(result.warnings) if result.warnings else "",
            }
            rows.append(row)
        
        # Utwórz DataFrame
        df = pd.DataFrame(rows)
        
        # Zapisz do CSV (UTF-8 z BOM dla Excel)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        
        logger.info("✅ CSV zapisany: %d wierszy", len(rows))
    
    @staticmethod
    def generate_json(
        results: List[NIPResult],
        output_path: str,
    ):
        """
        Generuje plik JSON z wynikami.
        
        Args:
            results: Lista NIPResult
            output_path: Ścieżka do pliku JSON
        """
        logger.info("📄 Generuję JSON: %s", output_path)
        
        # Konwersja do dict
        data = {
            "generated_at": datetime.utcnow().isoformat(),
            "total": len(results),
            "results": [result.model_dump() for result in results],
        }
        
        # Zapisz
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info("✅ JSON zapisany: %d wyników", len(results))
    
    @staticmethod
    def generate_detailed_report(
        results: List[NIPResult],
        output_path: str,
    ):
        """
        Generuje szczegółowy raport w Markdown.
        
        Args:
            results: Lista NIPResult
            output_path: Ścieżka do pliku MD
        """
        logger.info("📄 Generuję detailed report: %s", output_path)
        
        # === STATYSTYKI ===
        total = len(results)
        successful = sum(1 for r in results if r.found)
        failed = total - successful
        
        avg_confidence = sum(r.confidence for r in results if r.found) / successful if successful > 0 else 0
        avg_time = sum(r.processing_time_ms for r in results) / total if total > 0 else 0
        
        # Validated count
        validated_count = sum(
            1 for r in results 
            if r.found and r.validation and r.validation.validated
        )
        
        # Strategy breakdown
        strategy_stats = {}
        for r in results:
            if r.found and r.strategy_used:
                strategy_stats[r.strategy_used] = strategy_stats.get(r.strategy_used, 0) + 1
        
        # Failure reasons
        failure_reasons = {}
        for r in results:
            if not r.found and r.errors:
                for error in r.errors:
                    failure_reasons[error] = failure_reasons.get(error, 0) + 1
        
        # === MARKDOWN ===
        lines = []
        lines.append("# NIP Finder - Detailed Report")
        lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"\n## Summary\n")
        lines.append(f"- **Total queries:** {total}")
        lines.append(f"- **NIP found:** {successful} ({successful/total*100:.1f}%)")
        lines.append(f"- **Validated:** {validated_count} ({validated_count/successful*100:.1f}% of found)" if successful > 0 else "- **Validated:** 0")
        lines.append(f"- **Failed:** {failed} ({failed/total*100:.1f}%)")
        lines.append(f"- **Avg confidence:** {avg_confidence:.2f}")
        lines.append(f"- **Avg processing time:** {avg_time:.0f}ms")
        
        lines.append("\n## Strategy Performance\n")
        if strategy_stats:
            for strategy, count in sorted(strategy_stats.items(), key=lambda x: -x[1]):
                percentage = count / successful * 100 if successful > 0 else 0
                lines.append(f"- **{strategy}:** {count} ({percentage:.1f}%)")
        else:
            lines.append("- No successful strategies")
        
        lines.append("\n## Failure Analysis\n")
        if failure_reasons:
            lines.append(f"**Top failure reasons:**\n")
            for reason, count in sorted(failure_reasons.items(), key=lambda x: -x[1])[:10]:
                percentage = count / failed * 100 if failed > 0 else 0
                lines.append(f"- {reason}: {count} ({percentage:.1f}%)")
        else:
            lines.append("- No failures")
        
        lines.append("\n## Detailed Results\n")
        
        # Top 10 successful
        lines.append("### ✅ Top Successful Results\n")
        successful_results = [r for r in results if r.found]
        successful_results.sort(key=lambda r: r.confidence, reverse=True)
        
        for i, r in enumerate(successful_results[:10], 1):
            lines.append(f"#### {i}. {r.company_name}")
            lines.append(f"- **NIP:** {r.nip_formatted or r.nip}")
            lines.append(f"- **Confidence:** {r.confidence:.2f}")
            lines.append(f"- **Strategy:** {r.strategy_used}")
            if r.source:
                lines.append(f"- **Source:** [{r.source.url}]({r.source.url})")
            if r.validation:
                lines.append(f"- **Validated:** {'✅ Yes' if r.validation.validated else '⚠️ No'}")
                if r.validation.gus_name:
                    lines.append(f"- **GUS name:** {r.validation.gus_name}")
                    if r.validation.name_match_score:
                        lines.append(f"- **Name match:** {r.validation.name_match_score:.2f}")
            if r.ai_reasoning:
                lines.append(f"- **AI reasoning:** {r.ai_reasoning}")
            lines.append(f"- **Time:** {r.processing_time_ms}ms")
            lines.append("")
        
        # Top 10 failures
        lines.append("### ❌ Top Failures\n")
        failed_results = [r for r in results if not r.found]
        
        for i, r in enumerate(failed_results[:10], 1):
            lines.append(f"#### {i}. {r.company_name}")
            if r.city:
                lines.append(f"- **City:** {r.city}")
            if r.errors:
                lines.append(f"- **Errors:** {', '.join(r.errors)}")
            if r.warnings:
                lines.append(f"- **Warnings:** {', '.join(r.warnings)}")
            lines.append(f"- **Time:** {r.processing_time_ms}ms")
            lines.append("")
        
        # === ZAPIS ===
        content = "\n".join(lines)
        
        Path(output_path).write_text(content, encoding="utf-8")
        
        logger.info("✅ Detailed report zapisany")
    
    @staticmethod
    def generate_batch_summary(
        batch_result: BatchNIPResult,
        output_path: str,
    ):
        """
        Generuje podsumowanie batch processing (Markdown).
        
        Args:
            batch_result: BatchNIPResult
            output_path: Ścieżka do pliku MD
        """
        logger.info("📄 Generuję batch summary: %s", output_path)
        
        lines = []
        lines.append("# Batch Processing Summary")
        lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"\n## Results\n")
        lines.append(f"- **Total:** {batch_result.total}")
        lines.append(f"- **Successful:** {batch_result.successful}")
        lines.append(f"- **Failed:** {batch_result.failed}")
        lines.append(f"- **Success rate:** {batch_result.successful/batch_result.total*100:.1f}%")
        lines.append(f"- **Avg confidence:** {batch_result.avg_confidence:.2f}")
        lines.append(f"- **Avg time:** {batch_result.avg_processing_time_ms}ms")
        
        if batch_result.strategy_stats:
            lines.append("\n## Strategy Breakdown\n")
            for strategy, count in sorted(batch_result.strategy_stats.items(), key=lambda x: -x[1]):
                percentage = count / batch_result.successful * 100 if batch_result.successful > 0 else 0
                lines.append(f"- **{strategy}:** {count} ({percentage:.1f}%)")
        
        content = "\n".join(lines)
        Path(output_path).write_text(content, encoding="utf-8")
        
        logger.info("✅ Batch summary zapisany")
