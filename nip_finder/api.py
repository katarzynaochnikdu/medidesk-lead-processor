"""
FastAPI endpoints dla NIP Finder.

Endpoints:
- POST /find-nip - pojedyncze wyszukiwanie
- POST /batch-find-nip - batch processing
- GET /cache/stats - statystyki cache
"""

import logging
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .cache import NIPCache
from .models import BatchNIPRequest, BatchNIPResult, NIPRequest, NIPResult
from .orchestrator import NIPFinder

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="NIP Finder API",
    description="API do wyszukiwania NIP firm na podstawie minimalnych danych",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # W produkcji: podaj konkretne domeny
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton NIPFinder
_nip_finder: NIPFinder = None


def get_nip_finder() -> NIPFinder:
    """Zwraca singleton NIPFinder."""
    global _nip_finder
    if _nip_finder is None:
        _nip_finder = NIPFinder()
    return _nip_finder


@app.on_event("startup")
async def startup_event():
    """Startup event - inicjalizacja."""
    logger.info("🚀 NIP Finder API starting...")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event - cleanup."""
    logger.info("🛑 NIP Finder API shutting down...")
    global _nip_finder
    if _nip_finder:
        await _nip_finder.close()


@app.get("/")
async def root():
    """Root endpoint - health check."""
    return {
        "service": "NIP Finder API",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/find-nip", response_model=NIPResult)
async def find_nip(request: NIPRequest) -> NIPResult:
    """
    Wyszukaj NIP dla pojedynczej firmy.
    
    Args:
        request: NIPRequest z nazwą firmy i opcjonalnymi danymi
    
    Returns:
        NIPResult z wynikiem wyszukiwania
    
    Example:
        ```json
        {
          "company_name": "VITA MEDICA SIEDLCE",
          "city": "Siedlce",
          "email": "kontakt@vitamedica.pl"
        }
        ```
    """
    logger.info("🔍 API: Szukam NIP dla: %s", request.company_name)
    
    try:
        finder = get_nip_finder()
        
        result = await finder.find_nip(
            company_name=request.company_name,
            city=request.city,
            email=request.email,
        )
        
        logger.info("✅ API: Wynik dla %s: found=%s", request.company_name, result.found)
        
        return result
        
    except Exception as e:
        logger.error("❌ API error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch-find-nip", response_model=BatchNIPResult)
async def batch_find_nip(request: BatchNIPRequest) -> BatchNIPResult:
    """
    Batch processing - wyszukaj NIP dla wielu firm.
    
    Args:
        request: BatchNIPRequest z listą firm
    
    Returns:
        BatchNIPResult z wynikami i statystykami
    
    Example:
        ```json
        {
          "companies": [
            {
              "company_name": "VITA MEDICA SIEDLCE",
              "city": "Siedlce"
            },
            {
              "company_name": "Centrum Medyczne ABC",
              "city": "Warszawa"
            }
          ],
          "max_concurrent": 5
        }
        ```
    """
    logger.info("📦 API: Batch processing: %d firm", len(request.companies))
    
    try:
        finder = get_nip_finder()
        
        results = await finder.batch_find_nip(
            requests=request.companies,
            max_concurrent=request.max_concurrent,
        )
        
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
        
        batch_result = BatchNIPResult(
            total=len(results),
            successful=successful,
            failed=failed,
            results=results,
            avg_confidence=avg_confidence,
            avg_processing_time_ms=int(avg_time),
            strategy_stats=strategy_stats,
        )
        
        logger.info("✅ API: Batch completed: %d/%d znalezionych", successful, len(results))
        
        return batch_result
        
    except Exception as e:
        logger.error("❌ API batch error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/cache/stats")
async def cache_stats():
    """
    Zwraca statystyki cache.
    
    Returns:
        Dict ze statystykami cache
    """
    try:
        cache = NIPCache()
        stats = await cache.stats()
        await cache.close()
        
        return stats
        
    except Exception as e:
        logger.error("❌ API cache stats error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/cache/clear")
async def cache_clear():
    """
    Usuwa wygasłe wpisy z cache.
    
    Returns:
        Status operacji
    """
    try:
        cache = NIPCache()
        await cache.clear_expired()
        stats = await cache.stats()
        await cache.close()
        
        return {
            "status": "success",
            "message": "Expired entries cleared",
            "stats": stats,
        }
        
    except Exception as e:
        logger.error("❌ API cache clear error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Dla uruchomienia lokalnego
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "nip_finder.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
