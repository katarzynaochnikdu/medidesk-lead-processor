"""
Lead Processing Service - główna aplikacja FastAPI.
Endpoint do przetwarzania leadów z Zoho CRM.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import Settings, get_settings
from .models.lead_input import LeadInputRaw
from .models.lead_output import LeadOutput
from .services.data_normalizer import DataNormalizerService

# Konfiguracja logowania
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Singleton serwisu (zarządzany przez lifespan)
_normalizer_service: Optional[DataNormalizerService] = None


def get_normalizer_service() -> DataNormalizerService:
    """Dependency injection dla serwisu normalizacji."""
    global _normalizer_service
    if _normalizer_service is None:
        settings = get_settings()
        use_mocks = settings.environment == "development" and not settings.gcp_project_id
        _normalizer_service = DataNormalizerService(
            settings=settings,
            use_mocks=use_mocks,
        )
    return _normalizer_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Zarządzanie cyklem życia aplikacji."""
    logger.info("Starting Lead Processing Service...")
    
    # Inicjalizacja serwisów
    get_normalizer_service()
    
    yield
    
    # Cleanup
    logger.info("Shutting down Lead Processing Service...")
    if _normalizer_service:
        await _normalizer_service.close()


# Aplikacja FastAPI
app = FastAPI(
    title="Lead Processing Service",
    description="Przetwarzanie leadów z Zoho CRM: normalizacja AI, GUS, deduplikacja",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - dozwolone dla Zoho
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://*.zoho.eu",
        "https://*.zoho.com",
        "https://crm.zoho.eu",
        "https://crm.zoho.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# === Modele API ===

class ProcessRequest(BaseModel):
    """Request do przetwarzania leada."""
    
    # Dane leada - elastyczne (przyjmujemy wszystko)
    data: dict[str, Any]
    
    # Opcje przetwarzania
    skip_ai: bool = False
    skip_gus: bool = False
    skip_duplicates: bool = False


class HealthResponse(BaseModel):
    """Response health check."""
    status: str
    version: str
    environment: str


class ErrorResponse(BaseModel):
    """Response błędu."""
    error: str
    detail: Optional[str] = None


# === Autoryzacja ===

async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
) -> bool:
    """
    Weryfikuje API key z headera.
    Akceptuje:
    - X-API-Key: <key>
    - Authorization: Bearer <key>
    """
    settings = get_settings()
    
    # W development można pominąć autoryzację
    if settings.environment == "development" and not settings.api_key:
        return True
    
    # Sprawdź X-API-Key
    if x_api_key and x_api_key == settings.api_key:
        return True
    
    # Sprawdź Authorization Bearer
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token == settings.api_key:
            return True
    
    raise HTTPException(
        status_code=401,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


# === Endpointy ===

@app.get("/", response_model=HealthResponse)
async def root():
    """Health check i informacje o serwisie."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        environment=settings.environment,
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check dla Cloud Run."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        environment=settings.environment,
    )


@app.post(
    "/process",
    response_model=LeadOutput,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        422: {"model": ErrorResponse, "description": "Validation Error"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def process_lead(
    request: ProcessRequest,
    _authorized: bool = Depends(verify_api_key),
    normalizer: DataNormalizerService = Depends(get_normalizer_service),
):
    """
    Przetwarza lead z Zoho CRM.
    
    Etapy przetwarzania:
    1. Normalizacja AI - poprawia wielkość liter, rozdziela imię/nazwisko, wykrywa płeć
    2. Walidacja GUS - pobiera oficjalne dane firmy po NIP
    3. Deduplikacja - szuka duplikatów w Zoho CRM (Contacts, Accounts, Leads)
    4. Rekomendacja - sugeruje działanie (create_new, link_to_existing, etc.)
    
    Headers:
    - X-API-Key: <your-api-key>
    
    Body:
    ```json
    {
        "data": {
            "raw_name": "jan kowalski",
            "company": "medidesk sp z o.o.",
            "email": "jan@medidesk.pl",
            "phone": "601234567",
            "nip": "1234567890"
        },
        "skip_ai": false,
        "skip_gus": false,
        "skip_duplicates": false
    }
    ```
    """
    try:
        logger.info("Processing lead request: %d bytes", len(str(request.data)))
        
        result = await normalizer.process_lead(
            raw_data=request.data,
            skip_ai=request.skip_ai,
            skip_gus=request.skip_gus,
            skip_duplicates=request.skip_duplicates,
        )
        
        return result
        
    except Exception as e:
        logger.error("Error processing lead: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


@app.post(
    "/normalize",
    response_model=LeadOutput,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def normalize_only(
    request: ProcessRequest,
    _authorized: bool = Depends(verify_api_key),
    normalizer: DataNormalizerService = Depends(get_normalizer_service),
):
    """
    Tylko normalizacja AI - bez GUS i deduplikacji.
    Szybszy endpoint do prostego czyszczenia danych.
    """
    try:
        result = await normalizer.process_lead(
            raw_data=request.data,
            skip_ai=request.skip_ai,
            skip_gus=True,
            skip_duplicates=True,
        )
        return result
        
    except Exception as e:
        logger.error("Error normalizing: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


@app.post(
    "/check-duplicates",
    response_model=LeadOutput,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def check_duplicates_only(
    request: ProcessRequest,
    _authorized: bool = Depends(verify_api_key),
    normalizer: DataNormalizerService = Depends(get_normalizer_service),
):
    """
    Tylko sprawdzenie duplikatów - bez AI i GUS.
    Szybki endpoint do weryfikacji czy lead istnieje.
    """
    try:
        result = await normalizer.process_lead(
            raw_data=request.data,
            skip_ai=True,
            skip_gus=True,
            skip_duplicates=False,
        )
        return result
        
    except Exception as e:
        logger.error("Error checking duplicates: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


@app.post(
    "/validate-nip",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def validate_nip(
    nip: str,
    _authorized: bool = Depends(verify_api_key),
    normalizer: DataNormalizerService = Depends(get_normalizer_service),
):
    """
    Waliduje NIP i pobiera dane z GUS.
    """
    try:
        from .utils.validators import is_valid_nip, normalize_nip
        
        clean_nip = normalize_nip(nip)
        
        if not clean_nip:
            return JSONResponse(
                status_code=400,
                content={"error": "Nieprawidłowy format NIP"},
            )
        
        checksum_valid = is_valid_nip(clean_nip)
        
        if not checksum_valid:
            return {
                "nip": clean_nip,
                "valid": False,
                "error": "NIP nie przeszedł walidacji sumy kontrolnej",
                "gus_data": None,
            }
        
        # Pobierz dane z GUS
        gus_data = await normalizer.gus_client.lookup_nip(clean_nip)
        
        return {
            "nip": clean_nip,
            "valid": gus_data.found,
            "gus_data": gus_data.model_dump() if gus_data.found else None,
            "error": gus_data.error if not gus_data.found else None,
        }
        
    except Exception as e:
        logger.error("Error validating NIP: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


@app.post(
    "/search-nip",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def search_nip(
    company_name: str,
    _authorized: bool = Depends(verify_api_key),
):
    """
    Szuka NIP firmy po nazwie przez Brave Search.
    Przeszukuje portale rejestrowe (rejestr.io, aleo.com, panoramafirm.pl, etc.)
    
    Query params:
    - company_name: Nazwa firmy do wyszukania
    
    Returns:
    - nip: Znaleziony NIP lub null
    - sources: Źródła z których wyciągnięto NIP
    """
    try:
        from .services.brave_search import get_brave_search_service
        
        if not company_name or len(company_name) < 3:
            return JSONResponse(
                status_code=400,
                content={"error": "Nazwa firmy musi mieć min. 3 znaki"},
            )
        
        brave = get_brave_search_service()
        nip = await brave.find_nip(company_name)
        
        if nip:
            # Waliduj przez GUS
            from .utils.validators import is_valid_nip
            normalizer = get_normalizer_service()
            gus_data = await normalizer.gus_client.lookup_nip(nip)
            
            return {
                "company_name": company_name,
                "nip": nip,
                "nip_valid": is_valid_nip(nip),
                "gus_verified": gus_data.found,
                "gus_data": gus_data.model_dump() if gus_data.found else None,
            }
        
        return {
            "company_name": company_name,
            "nip": None,
            "error": "Nie znaleziono NIP dla podanej nazwy firmy",
        }
        
    except Exception as e:
        logger.error("Error searching NIP: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


@app.post(
    "/search-company-info",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def search_company_info(
    company_name: str,
    _authorized: bool = Depends(verify_api_key),
):
    """
    Zbiera informacje o firmie z internetu przez Brave Search.
    
    Query params:
    - company_name: Nazwa firmy
    
    Returns:
    - sources: Lista źródeł z informacjami
    - snippets: Fragmenty tekstu ze źródeł
    """
    try:
        from .services.brave_search import get_brave_search_service
        
        if not company_name or len(company_name) < 3:
            return JSONResponse(
                status_code=400,
                content={"error": "Nazwa firmy musi mieć min. 3 znaki"},
            )
        
        brave = get_brave_search_service()
        info = await brave.get_company_info(company_name)
        
        return {
            "company_name": company_name,
            "sources_count": len(info.get("sources", [])),
            "sources": info.get("sources", [])[:10],  # Max 10 źródeł
        }
        
    except Exception as e:
        logger.error("Error searching company info: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


class EnrichCompanyRequest(BaseModel):
    """Request do wzbogacania danych firmy."""
    company_name: str
    address: Optional[str] = None
    nip: Optional[str] = None


@app.post(
    "/enrich-company",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def enrich_company(
    request: EnrichCompanyRequest,
    _authorized: bool = Depends(verify_api_key),
    normalizer: DataNormalizerService = Depends(get_normalizer_service),
):
    """
    Wzbogaca dane firmy - szuka w internecie i klasyfikuje przez AI.
    
    Zwraca pola do Zoho CRM:
    - industry: Branża (Placówka medyczna, Konkurencja, Partner, etc.)
    - specjalizacja: Lista specjalizacji (POZ, Stomatologia, Szpital, etc.)
    - platnik_uslug: Lista płatników (NFZ, Komercyjne, Ubezpieczenie)
    - address_type: Typ adresu (Siedziba i Filia / Siedziba)
    - nip: NIP znaleziony lub podany
    - gus_data: Dane z GUS jeśli znaleziono NIP
    """
    try:
        from .services.brave_search import get_brave_search_service
        from .services.vertex_ai import get_vertex_ai_service
        
        if not request.company_name or len(request.company_name) < 3:
            return JSONResponse(
                status_code=400,
                content={"error": "Nazwa firmy musi mieć min. 3 znaki"},
            )
        
        # 1. Zbierz dane z internetu
        brave = get_brave_search_service()
        enrichment_data = await brave.enrich_company(
            company_name=request.company_name,
            address=request.address,
        )
        
        # Użyj podanego NIP jeśli jest, w przeciwnym razie użyj znalezionego
        nip = request.nip or enrichment_data.get("nip")
        
        # 2. Jeśli mamy NIP - pobierz dane z GUS
        gus_data = None
        if nip:
            gus_result = await normalizer.gus_client.lookup_nip(nip)
            if gus_result.found:
                gus_data = gus_result.model_dump()
        
        # 3. Klasyfikuj przez AI
        ai_service = get_vertex_ai_service()
        classification = await ai_service.classify_company(
            company_name=request.company_name,
            nip=nip,
            address=request.address or (gus_data.get("street") if gus_data else None),
            web_snippets=enrichment_data.get("web_snippets"),
            sources=enrichment_data.get("sources"),
        )
        
        # 4. Przygotuj odpowiedź w formacie Zoho CRM
        return {
            "company_name": request.company_name,
            "nip": nip,
            "gus_verified": gus_data is not None,
            "gus_data": gus_data,
            
            # Klasyfikacja AI - pola do Zoho
            "industry": classification.get("industry"),
            "specjalizacja": classification.get("specjalizacja", []),
            "platnik_uslug": classification.get("platnik_uslug", []),
            "address_type": classification.get("address_type"),
            "is_medical_at_address": classification.get("is_medical_at_address"),
            
            # Metadane
            "confidence": classification.get("confidence"),
            "reasoning": classification.get("reasoning"),
            "sources_count": len(enrichment_data.get("sources", [])),
        }
        
    except Exception as e:
        logger.error("Error enriching company: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


# === Error handlers ===

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handler dla HTTPException."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handler dla nieoczekiwanych wyjątków."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


# === Uruchomienie lokalne ===

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        reload=True,
    )
