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
from .models.evidence_bundle import (
    EvidenceBundle,
    EvidenceSource,
    LocationEvidence,
    LeadNormalizeRequest,
    LeadNormalizeResponse,
    LeadEnrichCoreRequest,
    LeadEnrichCoreResponse,
    LeadDedupeRequest,
    LeadDedupeResponse,
    OrgEnrichCoreRequest,
    OrgEnrichCoreResponse,
    OrgEnrichSocialRequest,
    OrgEnrichSocialResponse,
)
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


class FindLocationsRequest(BaseModel):
    """Request do wyszukiwania placówek organizacji."""
    nip: str
    strategy: str = "balanced"  # fast | balanced | complete
    

@app.post(
    "/find-organization-locations",
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def find_organization_locations(
    request: FindLocationsRequest,
    _authorized: bool = Depends(verify_api_key),
):
    """
    Szuka wszystkich placówek/filii organizacji o podanym NIP.
    
    Mechanizm (Multi-Agent):
    1. Brave Search - szuka nazwy firmy po NIP + scrapuje strony z placówkami
    2. Vertex AI - wyodrębnia adresy z pełnej treści stron
    3. ParsingAgent - parsuje adresy na komponenty (ulica, budynek, lokal)
    4. EnrichmentAgent - wzbogaca o gmina/powiat/województwo (Brave Search)
    5. ValidationAgent - waliduje kompletność danych
    
    Parametry:
    - nip: NIP organizacji (10 cyfr)
    - strategy: Strategia przetwarzania (opcjonalnie)
        - "fast": Tylko parsowanie, bez wzbogacania (szybkie)
        - "balanced": Parsowanie + wzbogacanie z cache (domyślne)
        - "complete": Pełne wzbogacanie każdej lokalizacji (dokładne, wolniejsze)
    
    Zwraca:
    - organization_name: nazwa głównej organizacji
    - nip: NIP organizacji
    - total_found: liczba znalezionych placówek
    - locations: lista placówek z parsowanymi adresami
    - processing_stats: statystyki przetwarzania multi-agent
    """
    try:
        from .services.brave_search import get_brave_search_service
        from .services.vertex_ai import get_vertex_ai_service
        
        # Walidacja NIP
        nip = request.nip.replace("-", "").replace(" ", "").strip()
        if not nip or len(nip) != 10 or not nip.isdigit():
            return JSONResponse(
                status_code=400,
                content={"error": "NIP musi mieć 10 cyfr"},
            )
        
        # 1. Brave Search + Web Scraping - zbierz dane o organizacji i placówkach
        brave = get_brave_search_service()
        raw_data = await brave.find_organization_locations_with_scraping(nip)
        
        # Przekaż strategy do AI jako metadane
        raw_data["processing_strategy"] = request.strategy
        
        if raw_data.get("error"):
            return JSONResponse(
                status_code=400,
                content={"error": raw_data["error"]},
            )
        
        company_name = raw_data.get("company_name")
        if not company_name:
            return {
                "nip": nip,
                "organization_name": None,
                "total_found": 0,
                "locations": [],
                "error": "Nie znaleziono firmy o podanym NIP",
                "sources": raw_data.get("sources", []),
            }
        
        # 2. Vertex AI - wyodrębnij placówki z surowych danych
        ai_service = get_vertex_ai_service()
        extraction_result = await ai_service.extract_locations(
            company_name=company_name,
            nip=nip,
            raw_data=raw_data,
        )
        
        # 3. Przygotuj odpowiedź
        locations_raw = extraction_result.get("locations", [])
        
        return {
            "nip": nip,
            "organization_name": extraction_result.get("organization_name", company_name),
            "total_found": extraction_result.get("total_found", len(locations_raw)),
            
            # Lokalizacje - format surowy (wszystkie dane)
            "locations": locations_raw,
            
            # Lokalizacje - format Zoho CRM ready (tylko pola Shipping_*)
            "locations_zoho_format": [
                {k: v for k, v in loc.items() if k.startswith(("shipping_", "Shipping_")) or k in ["name", "phone", "source_url"]}
                for loc in locations_raw
            ],
            
            "notes": extraction_result.get("notes"),
            "sources": raw_data.get("sources", [])[:10],
            "processing_stats": extraction_result.get("processing_stats", {}),
            
            # Debug info
            "search_metadata": {
                "company_name_found": company_name,
                "snippets_analyzed": len(raw_data.get("raw_snippets", [])),
                "priority_urls": [d.get("url") for d in raw_data.get("locations_data", [])],
            },
        }
        
    except Exception as e:
        logger.error("Error finding organization locations: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
        )


# === NOWE ENDPOINTY - Segmentowane API ===

# --- Lead Core ---

@app.post(
    "/lead/normalize",
    response_model=LeadNormalizeResponse,
    tags=["Lead Core"],
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def lead_normalize(
    request: LeadNormalizeRequest,
    _authorized: bool = Depends(verify_api_key),
    normalizer: DataNormalizerService = Depends(get_normalizer_service),
):
    """
    Normalizacja danych leada (etap 1).
    
    Zwraca znormalizowane dane osoby/firmy + EvidenceBundle do przekazania dalej.
    Nie wykonuje: NIP lookup, GUS, deduplikacja Zoho.
    """
    import time
    start_time = time.time()
    
    try:
        from .models.lead_input import LeadInput, LeadInputRaw
        
        # Parsuj dane wejściowe
        raw_input = LeadInputRaw(**request.data)
        lead_input = LeadInput.from_raw(raw_input)
        
        # Inicjalizuj EvidenceBundle
        evidence = EvidenceBundle()
        
        # Dodaj dane wejściowe do evidence
        if lead_input.email:
            evidence.add_email(lead_input.email, EvidenceSource.INPUT)
            evidence.person_email = lead_input.email.lower()
        if lead_input.phone:
            evidence.add_phone(lead_input.phone, EvidenceSource.INPUT)
            evidence.person_phone = lead_input.phone
        if lead_input.company_name:
            evidence.add_company_name(lead_input.company_name, EvidenceSource.INPUT, confidence=0.8)
        if lead_input.nip:
            evidence.set_nip(lead_input.nip, EvidenceSource.INPUT, confidence=1.0)
        if lead_input.first_name:
            evidence.person_first_name = lead_input.first_name
        if lead_input.last_name:
            evidence.person_last_name = lead_input.last_name
        
        # Normalizacja AI (opcjonalna)
        if not request.skip_ai:
            try:
                normalized = await normalizer._ai_normalization(request.data)
                evidence.ai_outputs.normalization_done = True
                evidence.ai_outputs.normalized_first_name = normalized.first_name
                evidence.ai_outputs.normalized_last_name = normalized.last_name
                evidence.ai_outputs.normalized_company_name = normalized.company_name
                evidence.ai_outputs.detected_gender = normalized.gender
                
                # Zaktualizuj dane osoby
                if normalized.first_name:
                    evidence.person_first_name = normalized.first_name
                if normalized.last_name:
                    evidence.person_last_name = normalized.last_name
                if normalized.company_name:
                    evidence.add_company_name(normalized.company_name, EvidenceSource.AI_NORMALIZATION, confidence=0.95)
                if normalized.nip:
                    evidence.set_nip(normalized.nip, EvidenceSource.AI_NORMALIZATION, confidence=0.9)
                if normalized.website:
                    evidence.set_domain(normalized.website, EvidenceSource.AI_NORMALIZATION, confidence=0.85)
                
                evidence.mark_queried(EvidenceSource.AI_NORMALIZATION)
                
                normalized_dict = normalized.model_dump()
            except Exception as e:
                evidence.warnings.append(f"AI normalization failed: {str(e)}")
                normalized_dict = None
        else:
            # Podstawowa normalizacja bez AI
            normalized = await normalizer._basic_normalization(lead_input)
            normalized_dict = normalized.model_dump()
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        evidence.costs.total_time_ms = processing_time_ms
        
        return LeadNormalizeResponse(
            success=True,
            normalized_data=normalized_dict,
            evidence=evidence,
            warnings=evidence.warnings,
            errors=evidence.errors,
            processing_time_ms=processing_time_ms,
        )
        
    except Exception as e:
        logger.error("Error in lead/normalize: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/lead/enrich-core",
    response_model=LeadEnrichCoreResponse,
    tags=["Lead Core"],
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def lead_enrich_core(
    request: LeadEnrichCoreRequest,
    _authorized: bool = Depends(verify_api_key),
    normalizer: DataNormalizerService = Depends(get_normalizer_service),
):
    """
    Wzbogacenie danych leada (etap 2).
    
    Wykonuje: normalizację + NIP lookup (jeśli brak) + GUS (jeśli NIP).
    Zwraca EvidenceBundle z zebranymi danymi do dalszego użycia.
    
    Nie wykonuje: deduplikacja Zoho, social media, recenzje.
    """
    import time
    start_time = time.time()
    
    try:
        from .models.lead_input import LeadInput, LeadInputRaw
        from .utils.validators import normalize_nip, is_valid_nip, format_nip, extract_email_domain, is_public_email_domain
        
        # Użyj istniejącego EvidenceBundle lub stwórz nowy
        evidence = request.evidence or EvidenceBundle()
        
        # Parsuj dane wejściowe
        raw_input = LeadInputRaw(**request.data)
        lead_input = LeadInput.from_raw(raw_input)
        
        # Dodaj dane wejściowe do evidence (jeśli nie ma)
        if lead_input.email and not evidence.person_email:
            evidence.add_email(lead_input.email, EvidenceSource.INPUT)
            evidence.person_email = lead_input.email.lower()
        if lead_input.phone and not evidence.person_phone:
            evidence.add_phone(lead_input.phone, EvidenceSource.INPUT)
            evidence.person_phone = lead_input.phone
        if lead_input.company_name and not evidence.has_company_name():
            evidence.add_company_name(lead_input.company_name, EvidenceSource.INPUT, confidence=0.8)
        if lead_input.nip and not evidence.has_nip():
            clean_nip = normalize_nip(lead_input.nip)
            if clean_nip:
                evidence.set_nip(clean_nip, EvidenceSource.INPUT, confidence=1.0)
        
        # 1. Normalizacja AI (jeśli nie była robiona)
        normalized_dict = None
        if not request.skip_ai and not evidence.ai_outputs.normalization_done:
            try:
                normalized = await normalizer._ai_normalization(request.data)
                evidence.ai_outputs.normalization_done = True
                evidence.ai_outputs.normalized_first_name = normalized.first_name
                evidence.ai_outputs.normalized_last_name = normalized.last_name
                evidence.ai_outputs.normalized_company_name = normalized.company_name
                evidence.ai_outputs.detected_gender = normalized.gender
                
                if normalized.first_name:
                    evidence.person_first_name = normalized.first_name
                if normalized.last_name:
                    evidence.person_last_name = normalized.last_name
                if normalized.company_name:
                    evidence.add_company_name(normalized.company_name, EvidenceSource.AI_NORMALIZATION, confidence=0.95)
                if normalized.nip:
                    clean_nip = normalize_nip(normalized.nip)
                    if clean_nip:
                        evidence.set_nip(clean_nip, EvidenceSource.AI_NORMALIZATION, confidence=0.9)
                if normalized.website:
                    evidence.set_domain(normalized.website, EvidenceSource.AI_NORMALIZATION, confidence=0.85)
                
                evidence.mark_queried(EvidenceSource.AI_NORMALIZATION)
                normalized_dict = normalized.model_dump()
            except Exception as e:
                evidence.warnings.append(f"AI normalization failed: {str(e)}")
        
        # 2. NIP Finder (jeśli brak NIP i mamy firmę)
        if not request.skip_nip_search and not evidence.has_nip() and evidence.has_company_name():
            if normalizer.nip_finder and not evidence.has_queried(EvidenceSource.NIP_FINDER):
                try:
                    company_name = evidence.identity.get_best_name()
                    city = lead_input.city
                    
                    # Email do NIPFinder (nie publiczny)
                    email_for_search = evidence.person_email
                    if email_for_search:
                        email_domain = extract_email_domain(email_for_search)
                        if email_domain and is_public_email_domain(email_domain):
                            email_for_search = None
                    
                    nip_result = await normalizer.nip_finder.find_nip(
                        company_name=company_name,
                        city=city,
                        email=email_for_search,
                    )
                    
                    evidence.mark_queried(EvidenceSource.NIP_FINDER)
                    
                    if nip_result.found and nip_result.nip:
                        evidence.set_nip(nip_result.nip, EvidenceSource.NIP_FINDER, confidence=nip_result.confidence)
                        evidence.warnings.append(
                            f"NIP znaleziony przez {nip_result.strategy_used.value if nip_result.strategy_used else 'unknown'}: "
                            f"{format_nip(nip_result.nip)} (confidence: {nip_result.confidence:.0%})"
                        )
                    
                    # Merge scraped_data do evidence (emaile, telefony, adresy, social)
                    if nip_result.scraped_data:
                        evidence.merge_scraped_data(
                            nip_result.scraped_data,
                            EvidenceSource.NIP_FINDER,
                            source_url=nip_result.scraped_data.source_urls[0] if nip_result.scraped_data.source_urls else None
                        )
                        
                except Exception as e:
                    evidence.warnings.append(f"NIP search failed: {str(e)}")
        
        # 3. GUS lookup (jeśli mamy NIP)
        gus_dict = None
        if not request.skip_gus and evidence.has_nip() and not evidence.has_queried(EvidenceSource.GUS):
            try:
                nip = evidence.identity.get_nip()
                gus_data = await normalizer.gus_client.lookup_nip(nip)
                evidence.mark_queried(EvidenceSource.GUS)
                
                if gus_data.found:
                    # Dodaj dane z GUS do evidence
                    if gus_data.regon:
                        from .models.evidence_bundle import EvidenceItem
                        evidence.identity.regon = EvidenceItem(
                            value=gus_data.regon,
                            source=EvidenceSource.GUS,
                            confidence=1.0,
                        )
                    if gus_data.full_name:
                        evidence.add_company_name(gus_data.full_name, EvidenceSource.GUS, confidence=1.0)
                    
                    # Adres siedziby
                    if gus_data.city or gus_data.street:
                        address_parts = []
                        if gus_data.street:
                            address_parts.append(gus_data.street)
                        if gus_data.building_number:
                            address_parts.append(gus_data.building_number)
                        address = " ".join(address_parts) if address_parts else None
                        
                        evidence.add_location(LocationEvidence(
                            name="Siedziba (GUS)",
                            address=address,
                            city=gus_data.city,
                            postal_code=gus_data.zip_code,
                            street=gus_data.street,
                            source=EvidenceSource.GUS,
                        ))
                    
                    gus_dict = gus_data.model_dump()
                else:
                    if gus_data.error:
                        evidence.warnings.append(f"GUS: {gus_data.error}")
                        
            except Exception as e:
                evidence.warnings.append(f"GUS lookup failed: {str(e)}")
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        evidence.costs.total_time_ms = processing_time_ms
        
        return LeadEnrichCoreResponse(
            success=True,
            normalized_data=normalized_dict,
            gus_data=gus_dict,
            evidence=evidence,
            warnings=evidence.warnings,
            errors=evidence.errors,
            processing_time_ms=processing_time_ms,
        )
        
    except Exception as e:
        logger.error("Error in lead/enrich-core: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/lead/dedupe",
    response_model=LeadDedupeResponse,
    tags=["Lead Core"],
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def lead_dedupe(
    request: LeadDedupeRequest,
    _authorized: bool = Depends(verify_api_key),
    normalizer: DataNormalizerService = Depends(get_normalizer_service),
):
    """
    Deduplikacja w Zoho CRM (etap 3).
    
    Szuka duplikatów na podstawie danych z EvidenceBundle lub podanych pól.
    Zwraca wyniki tier-based matching + rekomendację.
    """
    import time
    start_time = time.time()
    
    try:
        evidence = request.evidence
        
        # Pobierz dane do deduplikacji z evidence lub z request
        email = request.email or evidence.person_email
        phone = request.phone or evidence.person_phone
        first_name = request.first_name or evidence.person_first_name
        last_name = request.last_name or evidence.person_last_name
        company_name = request.company_name or evidence.identity.get_best_name()
        nip = request.nip or evidence.identity.get_nip()
        
        # Wyszukaj duplikaty
        duplicates = await normalizer.zoho_service.find_all_duplicates(
            email=email,
            phone=phone,
            first_name=first_name,
            last_name=last_name,
            company_name=company_name,
            nip=nip,
        )
        
        evidence.mark_queried(EvidenceSource.ZOHO)
        
        # Generuj rekomendację
        from .models.lead_output import GUSData, NormalizedData
        normalized = NormalizedData(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            company_name=company_name,
            nip=nip,
        )
        gus_data = GUSData(found=evidence.identity.regon is not None)
        
        recommendation = normalizer._generate_recommendation(normalized, gus_data, duplicates)
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        evidence.costs.total_time_ms += processing_time_ms
        
        return LeadDedupeResponse(
            success=True,
            duplicates=duplicates.model_dump(),
            recommendation=recommendation.model_dump(),
            evidence=evidence,
            processing_time_ms=processing_time_ms,
        )
        
    except Exception as e:
        logger.error("Error in lead/dedupe: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --- Organization Intel ---

@app.post(
    "/org/enrich-core",
    response_model=OrgEnrichCoreResponse,
    tags=["Organization Intel"],
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def org_enrich_core(
    request: OrgEnrichCoreRequest,
    _authorized: bool = Depends(verify_api_key),
    normalizer: DataNormalizerService = Depends(get_normalizer_service),
):
    """
    Wzbogacenie danych organizacji - CORE (bez social/reviews).
    
    Zbiera: placówki, kontakty, specjalizacja, typ placówki.
    NIE zbiera: social media stats, recenzje, activity score.
    
    Preferuje: NIP → GUS → WWW scraping → Google Maps.
    Re-używa dane z EvidenceBundle jeśli dostępne.
    """
    import time
    start_time = time.time()
    
    try:
        # Użyj istniejącego EvidenceBundle lub stwórz nowy
        evidence = request.evidence or EvidenceBundle()
        
        # Uzupełnij evidence z request (jeśli podano)
        if request.nip and not evidence.has_nip():
            from .utils.validators import normalize_nip
            clean_nip = normalize_nip(request.nip)
            if clean_nip:
                evidence.set_nip(clean_nip, EvidenceSource.INPUT, confidence=1.0)
        
        if request.website and not evidence.has_domain():
            evidence.set_domain(request.website, EvidenceSource.INPUT, confidence=0.9)
        
        if request.company_name and not evidence.has_company_name():
            evidence.add_company_name(request.company_name, EvidenceSource.INPUT, confidence=0.8)
        
        # Określ punkt wejścia
        entry_point = evidence.get_entry_point()
        
        # 1. Jeśli mamy NIP i nie było GUS - zrób GUS
        if evidence.has_nip() and not evidence.has_queried(EvidenceSource.GUS):
            try:
                nip = evidence.identity.get_nip()
                gus_data = await normalizer.gus_client.lookup_nip(nip)
                evidence.mark_queried(EvidenceSource.GUS)
                
                if gus_data.found:
                    from .models.evidence_bundle import EvidenceItem
                    if gus_data.regon:
                        evidence.identity.regon = EvidenceItem(value=gus_data.regon, source=EvidenceSource.GUS, confidence=1.0)
                    if gus_data.full_name:
                        evidence.add_company_name(gus_data.full_name, EvidenceSource.GUS, confidence=1.0)
                    
                    # Adres siedziby
                    if gus_data.city or gus_data.street:
                        address_parts = []
                        if gus_data.street:
                            address_parts.append(gus_data.street)
                        if gus_data.building_number:
                            address_parts.append(gus_data.building_number)
                        address = " ".join(address_parts) if address_parts else None
                        
                        evidence.add_location(LocationEvidence(
                            name="Siedziba (GUS)",
                            address=address,
                            city=gus_data.city,
                            postal_code=gus_data.zip_code,
                            street=gus_data.street,
                            source=EvidenceSource.GUS,
                        ))
            except Exception as e:
                evidence.warnings.append(f"GUS lookup failed: {str(e)}")
        
        # 2. Jeśli mamy domenę i nie było scrapingu - zrób scraping WWW
        if evidence.has_domain() and not evidence.has_queried(EvidenceSource.WEBSITE_SCRAPER):
            try:
                # Importuj company_intel scraper
                from company_intel.scrapers import WebsiteScraper
                from company_intel.config import get_settings as get_ci_settings
                
                website_scraper = WebsiteScraper(get_ci_settings())
                domain = evidence.identity.get_domain()
                website_url = f"https://{domain}"
                
                result = await website_scraper.execute(url=website_url)
                evidence.mark_queried(EvidenceSource.WEBSITE_SCRAPER)
                
                if result.success:
                    data = result.data
                    
                    # Kontakty
                    for kontakt in data.get("kontakty", []):
                        if kontakt.get("typ") == "email":
                            evidence.add_email(kontakt["wartosc"], EvidenceSource.WEBSITE_SCRAPER, source_url=website_url)
                        elif kontakt.get("typ") == "telefon":
                            evidence.add_phone(kontakt["wartosc"], EvidenceSource.WEBSITE_SCRAPER, source_url=website_url)
                    
                    # Social links
                    social_links = data.get("social_links")
                    if social_links:
                        from .models.evidence_bundle import EvidenceItem
                        if getattr(social_links, 'facebook', None):
                            evidence.social_links.facebook = EvidenceItem(value=social_links.facebook, source=EvidenceSource.WEBSITE_SCRAPER)
                        if getattr(social_links, 'instagram', None):
                            evidence.social_links.instagram = EvidenceItem(value=social_links.instagram, source=EvidenceSource.WEBSITE_SCRAPER)
                        if getattr(social_links, 'linkedin', None):
                            evidence.social_links.linkedin = EvidenceItem(value=social_links.linkedin, source=EvidenceSource.WEBSITE_SCRAPER)
                        if getattr(social_links, 'tiktok', None):
                            evidence.social_links.tiktok = EvidenceItem(value=social_links.tiktok, source=EvidenceSource.WEBSITE_SCRAPER)
                
                await website_scraper.close()
                
            except ImportError:
                evidence.warnings.append("company_intel module not available for website scraping")
            except Exception as e:
                evidence.warnings.append(f"Website scraping failed: {str(e)}")
        
        # 3. Google Maps dla placówek (jeśli mamy nazwę firmy i nie było)
        if not request.skip_locations and evidence.has_company_name() and not evidence.has_queried(EvidenceSource.GOOGLE_MAPS):
            try:
                from company_intel.scrapers import GoogleMapsScraper
                from company_intel.config import get_settings as get_ci_settings
                
                maps_scraper = GoogleMapsScraper(get_ci_settings())
                company_name = evidence.identity.get_best_name()
                city = request.city
                website = evidence.identity.get_domain()
                
                result = await maps_scraper.execute(
                    company_name=company_name,
                    city=city,
                    max_places=5,
                    website=f"https://{website}" if website else None,
                    include_reviews=False,  # CORE - bez recenzji
                )
                evidence.mark_queried(EvidenceSource.GOOGLE_MAPS)
                
                if result.success:
                    placowki = result.data.get("placowki", [])
                    for p in placowki:
                        adres = getattr(p, 'adres', None)
                        evidence.add_location(LocationEvidence(
                            name=getattr(p, 'nazwa', None),
                            address=str(adres) if adres else None,
                            city=getattr(adres, 'miasto', None) if adres else None,
                            postal_code=getattr(adres, 'kod', None) if adres else None,
                            street=getattr(adres, 'ulica', None) if adres else None,
                            phone=p.kontakty[0].wartosc if p.kontakty else None,
                            google_place_id=getattr(p, 'google_maps_place_id', None),
                            google_rating=getattr(p, 'google_rating', None),
                            google_reviews_count=getattr(p, 'google_reviews_count', None),
                            source=EvidenceSource.GOOGLE_MAPS,
                        ))
                
                await maps_scraper.close()
                
            except ImportError:
                evidence.warnings.append("company_intel module not available for Google Maps")
            except Exception as e:
                evidence.warnings.append(f"Google Maps failed: {str(e)}")
        
        # 4. AI kategoryzacja (opcjonalna)
        if not request.skip_ai_categorization and not evidence.ai_outputs.categorization_done:
            try:
                from .services.vertex_ai import get_vertex_ai_service
                
                ai_service = get_vertex_ai_service()
                company_name = evidence.identity.get_best_name()
                nip = evidence.identity.get_nip()
                
                # Zbierz snippety (tu uproszczenie - w pełnej implementacji użyj tekstu ze stron)
                classification = await ai_service.classify_company(
                    company_name=company_name,
                    nip=nip,
                )
                
                if classification:
                    evidence.ai_outputs.categorization_done = True
                    evidence.ai_outputs.specialization = classification.get("specjalizacja", [])
                    evidence.ai_outputs.payer_type = classification.get("platnik_uslug", [])
                    evidence.ai_outputs.ownership_type = classification.get("typ_wlasnosci")
                    evidence.ai_outputs.industry = classification.get("industry")
                    evidence.ai_outputs.confidence = classification.get("confidence", 0.0)
                    evidence.ai_outputs.reasoning = classification.get("reasoning")
                    
            except Exception as e:
                evidence.warnings.append(f"AI categorization failed: {str(e)}")
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        evidence.costs.total_time_ms = processing_time_ms
        
        # Przygotuj odpowiedź
        return OrgEnrichCoreResponse(
            success=True,
            evidence=evidence,
            company_name=evidence.identity.get_best_name(),
            nip=evidence.identity.get_nip(),
            regon=evidence.identity.regon.value if evidence.identity.regon else None,
            specialization=evidence.ai_outputs.specialization,
            payer_type=evidence.ai_outputs.payer_type,
            ownership_type=evidence.ai_outputs.ownership_type,
            locations_count=len(evidence.locations),
            locations=[loc.model_dump() for loc in evidence.locations],
            emails=evidence.contacts.get_emails(),
            phones=evidence.contacts.get_phones(),
            warnings=evidence.warnings,
            errors=evidence.errors,
            processing_time_ms=processing_time_ms,
        )
        
    except Exception as e:
        logger.error("Error in org/enrich-core: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/org/enrich-social",
    response_model=OrgEnrichSocialResponse,
    tags=["Organization Intel"],
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def org_enrich_social(
    request: OrgEnrichSocialRequest,
    _authorized: bool = Depends(verify_api_key),
):
    """
    Wzbogacenie danych organizacji - Social Media (opcjonalne).
    
    Zbiera: Facebook, Instagram, TikTok stats + Activity Score.
    Opcjonalnie: recenzje Google Maps i ZnanyLekarz.
    
    Wymaga EvidenceBundle z linkami social (z org/enrich-core).
    """
    import time
    start_time = time.time()
    
    try:
        evidence = request.evidence
        social_profiles = []
        
        # Pobierz linki social z evidence lub z request
        facebook_url = request.facebook_url or (evidence.social_links.facebook.value if evidence.social_links.facebook else None)
        instagram_url = request.instagram_url or (evidence.social_links.instagram.value if evidence.social_links.instagram else None)
        tiktok_url = request.tiktok_url or (evidence.social_links.tiktok.value if evidence.social_links.tiktok else None)
        
        # Scrapuj social media
        try:
            from company_intel.scrapers.facebook import FacebookScraper
            from company_intel.scrapers.instagram import InstagramScraper
            from company_intel.scrapers.tiktok import TikTokScraper
            from company_intel.analyzers import ActivityScorer
            from company_intel.config import get_settings as get_ci_settings
            
            ci_settings = get_ci_settings()
            
            # Facebook
            if facebook_url:
                try:
                    fb_scraper = FacebookScraper(ci_settings)
                    fb_result = await fb_scraper.execute(facebook_url=facebook_url)
                    if fb_result.success and fb_result.data.get("profile"):
                        profile = fb_result.data["profile"]
                        social_profiles.append(profile.model_dump() if hasattr(profile, 'model_dump') else profile)
                    await fb_scraper.close()
                except Exception as e:
                    evidence.warnings.append(f"Facebook scraping failed: {str(e)}")
            
            # Instagram
            if instagram_url:
                try:
                    ig_scraper = InstagramScraper(ci_settings)
                    ig_result = await ig_scraper.execute(instagram_url=instagram_url)
                    if ig_result.success and ig_result.data.get("profile"):
                        profile = ig_result.data["profile"]
                        social_profiles.append(profile.model_dump() if hasattr(profile, 'model_dump') else profile)
                    await ig_scraper.close()
                except Exception as e:
                    evidence.warnings.append(f"Instagram scraping failed: {str(e)}")
            
            # TikTok
            if tiktok_url:
                try:
                    tt_scraper = TikTokScraper(ci_settings)
                    tt_result = await tt_scraper.execute(tiktok_url=tiktok_url)
                    if tt_result.success and tt_result.data.get("profile"):
                        profile = tt_result.data["profile"]
                        social_profiles.append(profile.model_dump() if hasattr(profile, 'model_dump') else profile)
                    await tt_scraper.close()
                except Exception as e:
                    evidence.warnings.append(f"TikTok scraping failed: {str(e)}")
            
            # Activity Score
            scorer = ActivityScorer(ci_settings)
            from company_intel.models import SocialProfile, Placowka
            
            # Konwertuj social_profiles do modeli
            profiles_for_score = []
            for p in social_profiles:
                if isinstance(p, dict):
                    profiles_for_score.append(SocialProfile(**p))
                else:
                    profiles_for_score.append(p)
            
            # Konwertuj locations do placówek (uproszczone)
            placowki_for_score = []
            for loc in evidence.locations:
                placowki_for_score.append(Placowka(
                    google_rating=loc.google_rating,
                    google_reviews_count=loc.google_reviews_count,
                ))
            
            activity_score_result = scorer.calculate(
                social_profiles=profiles_for_score,
                placowki=placowki_for_score,
                website_url=evidence.identity.get_domain(),
            )
            
            activity_score = activity_score_result.total
            activity_recommendation = activity_score_result.recommendation.value
            
            evidence.mark_queried(EvidenceSource.SOCIAL_SCRAPER)
            
        except ImportError:
            evidence.warnings.append("company_intel module not available for social scraping")
            activity_score = 0
            activity_recommendation = None
        except Exception as e:
            evidence.warnings.append(f"Social scraping failed: {str(e)}")
            activity_score = 0
            activity_recommendation = None
        
        # Recenzje (opcjonalnie)
        reviews_insights = None
        if request.include_reviews:
            try:
                from company_intel.analyzers import ReviewsAnalyzer
                from company_intel.scrapers import GoogleMapsScraper
                from company_intel.config import get_settings as get_ci_settings
                
                # Tu można dodać logikę zbierania i analizy recenzji
                # Na razie placeholder
                evidence.warnings.append("Reviews analysis not yet implemented in this endpoint")
                
            except Exception as e:
                evidence.warnings.append(f"Reviews analysis failed: {str(e)}")
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        evidence.costs.total_time_ms += processing_time_ms
        
        return OrgEnrichSocialResponse(
            success=True,
            evidence=evidence,
            social_profiles=social_profiles,
            activity_score=activity_score,
            activity_recommendation=activity_recommendation,
            reviews_insights=reviews_insights,
            warnings=evidence.warnings,
            errors=evidence.errors,
            processing_time_ms=processing_time_ms,
        )
        
    except Exception as e:
        logger.error("Error in org/enrich-social: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
