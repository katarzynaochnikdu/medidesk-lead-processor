"""
Główny serwis normalizacji danych.
Orkiestruje wszystkie komponenty: AI, GUS, Zoho.
"""

import asyncio
import logging
import time
from typing import Any, Optional

from ..config import Settings, get_settings
from ..models.lead_input import LeadInput, LeadInputRaw
from ..models.lead_output import (
    DuplicatesResult,
    GUSData,
    LeadOutput,
    NormalizedData,
    ProcessingRecommendation,
)
from ..utils.validators import (
    extract_email_domain,
    format_nip,
    format_phone,
    is_valid_nip,
    normalize_nip,
    normalize_phone,
)
from .gus_client import GUSClient, get_gus_client
from .vertex_ai import VertexAIService, get_vertex_ai_service
from .zoho_search import ZohoSearchService, get_zoho_search_service

logger = logging.getLogger(__name__)


class DataNormalizerService:
    """
    Główny serwis przetwarzania leadów.
    Koordynuje wszystkie etapy: normalizacja AI, GUS, deduplikacja.
    
    Rozszerzalny design:
    - Każdy komponent można wymienić (dependency injection)
    - Łatwe dodawanie nowych etapów przetwarzania
    - Pipeline można konfigurować
    """
    
    def __init__(
        self,
        settings: Optional[Settings] = None,
        vertex_ai_service: Optional[VertexAIService] = None,
        gus_client: Optional[GUSClient] = None,
        zoho_service: Optional[ZohoSearchService] = None,
        use_mocks: bool = False,
    ):
        self.settings = settings or get_settings()
        
        # Dependency injection - można podmienić dowolny serwis
        self.vertex_ai = vertex_ai_service or get_vertex_ai_service(
            self.settings, use_mock=use_mocks
        )
        self.gus_client = gus_client or get_gus_client(
            self.settings, use_mock=use_mocks
        )
        self.zoho_service = zoho_service or get_zoho_search_service(
            self.settings, use_mock=use_mocks
        )
    
    async def close(self):
        """Zamknij wszystkie połączenia."""
        await self.gus_client.close()
        await self.zoho_service.close()
    
    async def process_lead(
        self,
        raw_data: dict[str, Any],
        skip_ai: bool = False,
        skip_gus: bool = False,
        skip_duplicates: bool = False,
    ) -> LeadOutput:
        """
        Główna metoda przetwarzania leada.
        
        Args:
            raw_data: Surowe dane leada z Zoho
            skip_ai: Pomiń normalizację AI
            skip_gus: Pomiń walidację GUS
            skip_duplicates: Pomiń wyszukiwanie duplikatów
        
        Returns:
            LeadOutput z wszystkimi przetworzonymi danymi
        """
        start_time = time.time()
        warnings = []
        errors = []
        
        logger.info("Rozpoczynam przetwarzanie leada: %s", raw_data.get("id", "nowy"))
        
        try:
            # 1. Parsowanie danych wejściowych
            raw_input = LeadInputRaw(**raw_data)
            lead_input = LeadInput.from_raw(raw_input)
            
            # 2. Normalizacja AI (lub fallback)
            if skip_ai:
                normalized = await self._basic_normalization(lead_input)
                warnings.append("AI pominięte - użyto podstawowej normalizacji")
            else:
                normalized = await self._ai_normalization(raw_data)
            
            # 3. Uzupełnij dane z walidatorów
            normalized = self._enhance_normalized_data(normalized, lead_input)
            
            # 4. GUS lookup
            gus_data = GUSData(found=False)
            if not skip_gus and normalized.nip:
                gus_data = await self.gus_client.lookup_nip(normalized.nip)
                if gus_data.found:
                    # Uzupełnij brakujące dane z GUS
                    normalized = self._merge_gus_data(normalized, gus_data)
            
            # 5. Wyszukiwanie duplikatów
            duplicates = DuplicatesResult()
            if not skip_duplicates:
                duplicates = await self.zoho_service.find_all_duplicates(
                    email=normalized.email,
                    phone=normalized.phone,
                    first_name=normalized.first_name,
                    last_name=normalized.last_name,
                    company_name=normalized.company_name,
                    nip=normalized.nip,
                )
            
            # 6. Generowanie rekomendacji
            recommendation = self._generate_recommendation(
                normalized, gus_data, duplicates
            )
            
            # Oblicz czas przetwarzania
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            logger.info(
                "Przetwarzanie zakończone: %dms, duplikaty=%d contacts, %d accounts",
                processing_time_ms,
                len(duplicates.contacts),
                len(duplicates.accounts),
            )
            
            return LeadOutput(
                success=True,
                normalized=normalized,
                gus_data=gus_data,
                duplicates=duplicates,
                recommendation=recommendation,
                processing_time_ms=processing_time_ms,
                warnings=warnings,
                errors=errors,
            )
            
        except Exception as e:
            logger.error("Błąd przetwarzania leada: %s", e, exc_info=True)
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            return LeadOutput(
                success=False,
                processing_time_ms=processing_time_ms,
                errors=[str(e)],
                recommendation=ProcessingRecommendation(
                    action="review_required",
                    confidence=0.0,
                    reason=f"Błąd przetwarzania: {str(e)}",
                ),
            )
    
    async def _ai_normalization(self, raw_data: dict[str, Any]) -> NormalizedData:
        """Normalizacja przez Vertex AI."""
        try:
            return await self.vertex_ai.normalize_data(raw_data)
        except Exception as e:
            logger.warning("AI normalization failed, using fallback: %s", e)
            lead_input = LeadInput.from_raw(LeadInputRaw(**raw_data))
            return await self._basic_normalization(lead_input)
    
    async def _basic_normalization(self, lead_input: LeadInput) -> NormalizedData:
        """Podstawowa normalizacja bez AI."""
        first_name = lead_input.first_name
        last_name = lead_input.last_name
        
        # Rozdziel full_name jeśli brak imienia/nazwiska
        if lead_input.full_name and not (first_name and last_name):
            parts = lead_input.full_name.strip().split()
            if len(parts) >= 2:
                first_name = first_name or parts[0]
                last_name = last_name or " ".join(parts[1:])
            elif len(parts) == 1:
                last_name = last_name or parts[0]
        
        # Popraw wielkość liter
        if first_name:
            first_name = first_name.strip().title()
        if last_name:
            last_name = last_name.strip().title()
        
        return NormalizedData(
            first_name=first_name,
            last_name=last_name,
            email=lead_input.email.lower().strip() if lead_input.email else None,
            phone=normalize_phone(lead_input.phone),
            nip=normalize_nip(lead_input.nip),
            company_name=lead_input.company_name.strip().title() if lead_input.company_name else None,
            street=lead_input.street,
            city=lead_input.city,
            zip_code=lead_input.zip_code,
        )
    
    def _enhance_normalized_data(
        self, 
        normalized: NormalizedData, 
        lead_input: LeadInput
    ) -> NormalizedData:
        """Uzupełnia i formatuje dane po normalizacji."""
        # Formatuj telefon
        if normalized.phone:
            normalized.phone_formatted = format_phone(normalized.phone)
        elif lead_input.phone:
            normalized.phone = normalize_phone(lead_input.phone)
            normalized.phone_formatted = format_phone(normalized.phone)
        
        # Formatuj i waliduj NIP
        if normalized.nip:
            normalized.nip = normalize_nip(normalized.nip)
            normalized.nip_formatted = format_nip(normalized.nip)
            normalized.nip_valid = is_valid_nip(normalized.nip)
        elif lead_input.nip:
            normalized.nip = normalize_nip(lead_input.nip)
            normalized.nip_formatted = format_nip(normalized.nip)
            normalized.nip_valid = is_valid_nip(normalized.nip)
        
        # Email lowercase
        if normalized.email:
            normalized.email = normalized.email.lower().strip()
        elif lead_input.email:
            normalized.email = lead_input.email.lower().strip()
        
        # Uzupełnij brakujące pola
        if not normalized.first_name and lead_input.first_name:
            normalized.first_name = lead_input.first_name.strip().title()
        if not normalized.last_name and lead_input.last_name:
            normalized.last_name = lead_input.last_name.strip().title()
        if not normalized.company_name and lead_input.company_name:
            normalized.company_name = lead_input.company_name.strip()
        
        return normalized
    
    def _merge_gus_data(
        self, 
        normalized: NormalizedData, 
        gus_data: GUSData
    ) -> NormalizedData:
        """Uzupełnia dane z GUS."""
        # Nazwa firmy z GUS jest autorytatywna
        if gus_data.full_name:
            # Zachowaj oryginalną nazwę jeśli GUS zwrócił tylko wielkie litery
            if gus_data.full_name == gus_data.full_name.upper():
                # Popraw wielkość liter
                normalized.company_full_name = gus_data.full_name.title()
            else:
                normalized.company_full_name = gus_data.full_name
        
        # Adres z GUS (jeśli brak)
        if not normalized.street and gus_data.street:
            addr_parts = [gus_data.street]
            if gus_data.building_number:
                addr_parts.append(gus_data.building_number)
            if gus_data.apartment_number:
                addr_parts[-1] += f"/{gus_data.apartment_number}"
            normalized.street = " ".join(addr_parts)
        
        if not normalized.city and gus_data.city:
            normalized.city = gus_data.city.title()
        
        if not normalized.zip_code and gus_data.zip_code:
            normalized.zip_code = gus_data.zip_code
        
        return normalized
    
    def _generate_recommendation(
        self,
        normalized: NormalizedData,
        gus_data: GUSData,
        duplicates: DuplicatesResult,
    ) -> ProcessingRecommendation:
        """Generuje rekomendację działania."""
        suggestions = []
        
        # Sprawdź duplikaty
        best_contact = duplicates.best_contact_match
        best_account = duplicates.best_account_match
        
        # Wysoki score duplikatu kontaktu
        if best_contact and best_contact.score >= 0.8:
            return ProcessingRecommendation(
                action="link_to_existing",
                confidence=best_contact.score,
                reason=f"Znaleziono istniejący kontakt: {best_contact.name} ({best_contact.match_reason})",
                contact_id=best_contact.id,
                account_id=best_account.id if best_account else None,
                suggestions=["Sprawdź czy dane kontaktu są aktualne"],
            )
        
        # Średni score - wymaga przeglądu
        if best_contact and best_contact.score >= 0.5:
            return ProcessingRecommendation(
                action="review_required",
                confidence=best_contact.score,
                reason=f"Potencjalny duplikat: {best_contact.name} ({best_contact.match_reason})",
                contact_id=best_contact.id,
                account_id=best_account.id if best_account else None,
                suggestions=["Zweryfikuj ręcznie czy to ten sam kontakt"],
            )
        
        # Znaleziono firmę ale nie kontakt
        if best_account and best_account.score >= 0.8:
            suggestions.append(f"Powiąż z istniejącą firmą: {best_account.name}")
            return ProcessingRecommendation(
                action="create_new",
                confidence=0.8,
                reason="Nowy kontakt w istniejącej firmie",
                account_id=best_account.id,
                suggestions=suggestions,
            )
        
        # GUS potwierdził firmę
        if gus_data.found:
            suggestions.append("Dane firmy potwierdzone w GUS")
            if not best_account:
                suggestions.append("Rozważ utworzenie nowego Account")
        
        # NIP niepoprawny
        if normalized.nip and not normalized.nip_valid:
            suggestions.append("NIP nie przeszedł walidacji sumy kontrolnej")
        
        # Brak emaila lub telefonu
        if not normalized.email and not normalized.phone:
            suggestions.append("Brak danych kontaktowych (email/telefon)")
        
        return ProcessingRecommendation(
            action="create_new",
            confidence=0.7 if gus_data.found else 0.5,
            reason="Nowy lead - brak duplikatów",
            suggestions=suggestions,
        )
    
    # === METODY ROZSZERZAJĄCE - łatwe do nadpisania ===
    
    async def pre_process_hook(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """
        Hook wywoływany przed przetwarzaniem.
        Można nadpisać aby dodać własną logikę.
        """
        return raw_data
    
    async def post_process_hook(self, output: LeadOutput) -> LeadOutput:
        """
        Hook wywoływany po przetwarzaniu.
        Można nadpisać aby dodać własną logikę.
        """
        return output
    
    async def process_lead_with_hooks(
        self,
        raw_data: dict[str, Any],
        **kwargs,
    ) -> LeadOutput:
        """
        Przetwarzanie z hookami pre/post.
        """
        raw_data = await self.pre_process_hook(raw_data)
        output = await self.process_lead(raw_data, **kwargs)
        output = await self.post_process_hook(output)
        return output
