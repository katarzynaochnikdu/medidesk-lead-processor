"""
Bazowa klasa dla wszystkich scraperów.

Zapewnia:
- Logowanie wszystkich in/out
- Obsługę błędów
- Timing
- Strukturę wyników
"""

import logging
import time
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, TypeVar, Generic

from ..config import CompanyIntelSettings, get_settings


# Setup loggera z formatowaniem
def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Tworzy logger z odpowiednim formatowaniem."""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


@dataclass
class ScraperResult:
    """Wynik scrapera - ustandaryzowany format."""
    
    success: bool = False
    data: Any = None
    error: Optional[str] = None
    
    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    duration_ms: int = 0
    
    # Debug info
    source: str = ""
    input_data: dict = field(default_factory=dict)
    raw_response: Optional[Any] = None
    
    # Koszty
    cost_usd: float = 0.0
    
    def to_dict(self) -> dict:
        """Konwertuje do dict."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "source": self.source,
            "cost_usd": self.cost_usd,
        }
    
    def __str__(self) -> str:
        status = "OK" if self.success else f"FAIL: {self.error}"
        return f"ScraperResult({self.source}, {status}, {self.duration_ms}ms)"


class BaseScraper(ABC):
    """
    Bazowa klasa dla wszystkich scraperów.
    
    Zapewnia:
    - Automatyczne logowanie in/out
    - Timing
    - Obsługę błędów
    - Strukturę wyników
    """
    
    def __init__(self, settings: Optional[CompanyIntelSettings] = None):
        self.settings = settings or get_settings()
        self.logger = setup_logger(
            f"scraper.{self.__class__.__name__}",
            self.settings.log_level
        )
        self._scraper_name = self.__class__.__name__
    
    def _log_input(self, method: str, input_data: dict) -> None:
        """Loguje dane wejściowe."""
        if self.settings.log_inputs_outputs:
            # Truncate długich wartości
            truncated = self._truncate_dict(input_data, max_len=200)
            self.logger.info(
                "[INPUT] %s.%s | %s",
                self._scraper_name,
                method,
                json.dumps(truncated, ensure_ascii=False, default=str)
            )
    
    def _log_output(self, method: str, result: ScraperResult) -> None:
        """Loguje dane wyjściowe."""
        if self.settings.log_inputs_outputs:
            status = "SUCCESS" if result.success else "FAILED"
            data_preview = self._truncate_dict(
                result.data if isinstance(result.data, dict) else {"data": str(result.data)[:100]},
                max_len=200
            )
            self.logger.info(
                "[OUTPUT] %s.%s | %s | %dms | cost=$%.4f | %s",
                self._scraper_name,
                method,
                status,
                result.duration_ms,
                result.cost_usd,
                json.dumps(data_preview, ensure_ascii=False, default=str) if result.success else result.error
            )
    
    def _truncate_dict(self, data: dict, max_len: int = 200) -> dict:
        """Truncuje długie wartości w dict."""
        if not isinstance(data, dict):
            return data
        
        result = {}
        for k, v in data.items():
            if isinstance(v, str) and len(v) > max_len:
                result[k] = v[:max_len] + "..."
            elif isinstance(v, dict):
                result[k] = self._truncate_dict(v, max_len)
            elif isinstance(v, list) and len(v) > 5:
                result[k] = v[:5] + [f"... +{len(v)-5} more"]
            else:
                result[k] = v
        return result
    
    async def execute(self, **kwargs) -> ScraperResult:
        """
        Wykonuje scraping z pełnym logowaniem.
        
        Wrapper wokół _execute() który dodaje:
        - Logowanie in/out
        - Timing
        - Obsługę błędów
        """
        start_time = time.time()
        result = ScraperResult(
            source=self._scraper_name,
            input_data=kwargs,
            started_at=datetime.utcnow(),
        )
        
        # Log input
        self._log_input("execute", kwargs)
        
        try:
            # Wywołaj właściwą implementację
            result = await self._execute(**kwargs)
            result.source = self._scraper_name
            result.input_data = kwargs
            
        except Exception as e:
            self.logger.exception("[ERROR] %s.execute failed: %s", self._scraper_name, e)
            result.success = False
            result.error = f"{type(e).__name__}: {str(e)}"
        
        finally:
            # Timing
            result.finished_at = datetime.utcnow()
            result.duration_ms = int((time.time() - start_time) * 1000)
            
            # Log output
            self._log_output("execute", result)
        
        return result
    
    @abstractmethod
    async def _execute(self, **kwargs) -> ScraperResult:
        """
        Właściwa implementacja scrapera.
        
        Subklasy implementują tę metodę.
        """
        pass
    
    async def close(self) -> None:
        """Zamyka zasoby scrapera."""
        pass
