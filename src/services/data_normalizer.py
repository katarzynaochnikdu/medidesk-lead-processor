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
    capitalize_name,
    expand_diminutive,
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
from .brave_search import BraveSearchService, get_brave_search_service

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
        brave_service: Optional[BraveSearchService] = None,
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
        self.brave_service = brave_service if not use_mocks else None
        if not use_mocks and not brave_service:
            self.brave_service = get_brave_search_service(self.settings)
    
    async def close(self):
        """Zamknij wszystkie połączenia."""
        await self.gus_client.close()
        await self.zoho_service.close()
        if self.brave_service:
            await self.brave_service.close()
    
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
            
            # 3.5. Brave Search - szukaj NIP jeśli nie mamy
            if not normalized.nip and normalized.company_name and self.brave_service:
                # Wyciągnij domenę z emaila (jeśli nie jest publiczna)
                email_domain = None
                if normalized.email:
                    from ..utils.validators import extract_email_domain, is_public_email_domain
                    email_domain = extract_email_domain(normalized.email)
                    if email_domain and is_public_email_domain(email_domain):
                        email_domain = None  # Ignoruj domeny publiczne (gmail, outlook)
                
                logger.info("Brak NIP - szukam przez Brave Search dla: %s (domena: %s)", 
                           normalized.company_name, email_domain or "brak")
                try:
                    found_nip = await self.brave_service.find_nip(
                        normalized.company_name,
                        email_domain=email_domain
                    )
                    if found_nip:
                        # Waliduj NIP z domeną (jeśli mamy domenę)
                        validated = True
                        if email_domain:
                            try:
                                validated = await self.brave_service.validate_nip_domain(
                                    found_nip, 
                                    email_domain
                                )
                                if not validated:
                                    warnings.append(f"⚠️ NIP {format_nip(found_nip)} nie pasuje do domeny {email_domain} - wymaga weryfikacji")
                                    logger.warning("NIP nie pasuje do domeny - obniżam pewność")
                            except Exception as e:
                                logger.warning("Błąd walidacji NIP vs domena: %s", e)
                        
                        normalized.nip = found_nip
                        normalized.nip_formatted = format_nip(found_nip)
                        normalized.nip_valid = is_valid_nip(found_nip)
                        
                        if validated:
                            warnings.append(f"NIP znaleziony przez Brave Search: {format_nip(found_nip)}")
                        
                        logger.info("Brave Search znalazł NIP: %s (zwalidowany: %s)", found_nip, validated)
                    else:
                        logger.info("Brave Search nie znalazł NIP dla: %s", normalized.company_name)
                except Exception as e:
                    logger.warning("Błąd wyszukiwania NIP przez Brave: %s", e)
                    warnings.append(f"Nie udało się znaleźć NIP przez Brave Search")
            
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
    
    def _prepare_hybrid_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """
        Przygotowuje dane hybrydowe dla AI.
        Laczy strukturalne pola z pelnym kontekstem z raw_name.
        Dzieki temu AI ma wszystkie informacje w jednym miejscu.
        """
        hybrid = raw_data.copy()
        
        # Zbierz pelny kontekst do raw_name
        context_parts = []
        
        # Oryginalny raw_name
        if raw_data.get("raw_name"):
            context_parts.append(f"Marketing Lead - nazwa: {raw_data['raw_name']}")
        
        # Dodaj strukturalne pola jesli istnieja (dla kontekstu)
        if raw_data.get("company"):
            context_parts.append(f"Firma: {raw_data['company']}")
        if raw_data.get("first_name"):
            context_parts.append(f"Imie: {raw_data['first_name']}")
        if raw_data.get("last_name"):
            context_parts.append(f"Nazwisko: {raw_data['last_name']}")
        if raw_data.get("email"):
            context_parts.append(f"Email: {raw_data['email']}")
        if raw_data.get("phone"):
            context_parts.append(f"Telefon: {raw_data['phone']}")
        if raw_data.get("description"):
            context_parts.append(f"Tresc: {raw_data['description']}")
        
        # Zlacz w jeden kontekst
        if context_parts:
            hybrid["_full_context"] = "\n".join(context_parts)
        
        return hybrid
    
    async def _ai_normalization(self, raw_data: dict[str, Any]) -> NormalizedData:
        """Normalizacja przez Vertex AI z hybrydowym kontekstem."""
        try:
            # Przygotuj dane hybrydowe - AI dostaje pelny kontekst
            hybrid_data = self._prepare_hybrid_data(raw_data)
            return await self.vertex_ai.normalize_data(hybrid_data)
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
        
        # Popraw wielkość liter - pierwsza litera każdego słowa wielka, reszta małe
        if first_name:
            first_name = capitalize_name(first_name)
        if last_name:
            last_name = capitalize_name(last_name)
        
        # Firma
        company_name = capitalize_name(lead_input.company_name) if lead_input.company_name else None
        
        # Zwróć dane - walidacja firmy będzie w _enhance_normalized_data
        return NormalizedData(
            first_name=first_name,
            last_name=last_name,
            email=lead_input.email.lower().strip() if lead_input.email else None,
            phone=normalize_phone(lead_input.phone),
            nip=normalize_nip(lead_input.nip),
            company_name=company_name,
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
            normalized.first_name = capitalize_name(lead_input.first_name)
        if not normalized.last_name and lead_input.last_name:
            normalized.last_name = capitalize_name(lead_input.last_name)
        
        # Rozwin zdrobnienia imion (Gosia -> Malgorzata) dla lepszego matchingu
        if normalized.first_name:
            expanded = expand_diminutive(normalized.first_name)
            if expanded and expanded != normalized.first_name:
                logger.info("Rozszerzono zdrobnienie: %s -> %s", normalized.first_name, expanded)
                normalized.first_name = expanded
        if not normalized.company_name and lead_input.company_name:
            normalized.company_name = lead_input.company_name.strip()
        
        # === WALIDACJA FIRMY - odrzuć nierelewantne ===
        if normalized.company_name:
            company_lower = normalized.company_name.lower()
            original_company = normalized.company_name  # Zachowaj oryginalną nazwę
            
            # Firmy zagraniczne tech (nierelewantne dla Medidesk)
            irrelevant = ["amazon", "google", "microsoft", "apple", "facebook", "meta", "linkedin", "twitter"]
            # Placeholdery
            placeholders = ["właściciel", "firma osoby", "prywatna", "brak", "nie dotyczy"]
            
            should_remove = False
            reject_reason = None
            
            if any(irr in company_lower for irr in irrelevant):
                should_remove = True
                reject_reason = f"nierelewantna firma zagraniczna: {original_company}"
                logger.info("Firma odrzucona (nierelewantna): %s", normalized.company_name)
            elif any(ph in company_lower for ph in placeholders):
                should_remove = True
                reject_reason = f"placeholder: {original_company}"
                logger.info("Firma odrzucona (placeholder): %s", normalized.company_name)
            # Facebook/LinkedIn ID (długie cyfry)
            elif normalized.company_name.isdigit() and len(normalized.company_name) > 10:
                should_remove = True
                reject_reason = f"social media ID: {original_company}"
                logger.info("Firma odrzucona (social ID): %s", normalized.company_name)
            # Pojedyncze typowe imię w polu Firma
            elif (len(normalized.company_name.split()) == 1 and 
                  normalized.company_name[0].isupper() and 
                  len(normalized.company_name) < 15 and
                  not normalized.company_name.isupper()):  # Nie skrót (NZOZ, POZ)
                # Prawdopodobnie imię - przepisz jeśli brak first_name
                if not normalized.first_name:
                    normalized.first_name = capitalize_name(normalized.company_name)
                    logger.info("Firma to imię - przepisano do first_name: %s", normalized.company_name)
                should_remove = True
                reject_reason = f"imie zamiast firmy: {original_company}"
            
            if should_remove:
                # Ustaw flagi odrzucenia
                normalized.company_rejected = True
                normalized.company_rejected_reason = reject_reason
                normalized.company_name = None
                # Jeśli nie ma firmy, usuń też NIP (prawdopodobnie błędny)
                if normalized.nip:
                    logger.info("Usuwam NIP (brak relewantnej firmy): %s", normalized.nip)
                    normalized.nip = None
                    normalized.nip_formatted = None
                    normalized.nip_valid = None
        
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
        """Generuje rekomendację działania na podstawie tier-based matching."""
        suggestions = []
        
        # Pobierz wyniki tier-based
        contact_result = duplicates.contact
        account_result = duplicates.account
        
        best_contact = duplicates.best_contact_match
        best_account = duplicates.best_account_match
        
        # === Modyfikator confidence gdy firma odrzucona ===
        # Jesli firma byla nierelewantna (Amazon, placeholder), obniz pewnosc dopasowania
        # bo kontakt moze byc inna osoba o tym samym imieniu/nazwisku
        confidence_penalty = 0.0
        if normalized.company_rejected:
            confidence_penalty = 0.25  # Obniz o 25%
            suggestions.append(f"Firma odrzucona ({normalized.company_rejected_reason}) - obnizono pewnosc")
        
        # === Kontakt istnieje (Tier >= 3) ===
        if contact_result.exists:
            base_confidence = best_contact.tier / 4.0 if best_contact else 0.75
            adjusted_confidence = max(0.3, base_confidence - confidence_penalty)
            
            # Jesli firma odrzucona i nie ma potwierdzenia firmy, wymagaj przegladu
            if normalized.company_rejected and not account_result.exists:
                return ProcessingRecommendation(
                    action="review_required",
                    confidence=adjusted_confidence,
                    reason=f"Znaleziono kontakt {best_contact.name}, ale firma odrzucona jako nierelewantna - moze to inna osoba" if best_contact else "Kontakt znaleziony ale firma nierelewantna",
                    contact_id=contact_result.primary_id,
                    account_id=account_result.parent_id,
                    suggestions=suggestions + ["Zweryfikuj czy to ta sama osoba - firma nie pasuje"],
                )
            
            # Jednoznaczne dopasowanie
            if contact_result.primary_id:
                return ProcessingRecommendation(
                    action="link_to_existing",
                    confidence=adjusted_confidence,
                    reason=f"Znaleziono istniejący kontakt: {best_contact.name} ({best_contact.match_reason})" if best_contact else "Kontakt istnieje",
                    contact_id=contact_result.primary_id,
                    account_id=account_result.parent_id,
                    suggestions=suggestions + ["Sprawdź czy dane kontaktu są aktualne"],
                )
            
            # Wymaga przeglądu (remis na top1)
            if contact_result.needs_review:
                return ProcessingRecommendation(
                    action="review_required",
                    confidence=adjusted_confidence,
                    reason=f"Kilku kandydatów z tym samym tier: {len(contact_result.candidates)} kontaktów",
                    contact_id=best_contact.id if best_contact else None,
                    account_id=account_result.parent_id,
                    suggestions=suggestions + ["Zweryfikuj ręcznie który kontakt jest właściwy"],
                )
        
        # === Tylko kandydaci (Tier 2) - wymaga przeglądu ===
        if best_contact and best_contact.tier == 2:
            return ProcessingRecommendation(
                action="review_required",
                confidence=0.5,
                reason=f"Potencjalny duplikat (słaby): {best_contact.name} ({best_contact.match_reason})",
                contact_id=best_contact.id,
                account_id=account_result.parent_id,
                suggestions=["Słabe dopasowanie - zweryfikuj ręcznie"],
            )
        
        # === Firma istnieje ale nie kontakt ===
        if account_result.exists and not contact_result.exists:
            suggestions.append(f"Powiąż z istniejącą firmą: {best_account.name}" if best_account else "Firma istnieje")
            return ProcessingRecommendation(
                action="create_new",
                confidence=0.8,
                reason="Nowy kontakt w istniejącej firmie",
                account_id=account_result.parent_id,
                suggestions=suggestions,
            )
        
        # === Brak dopasowań - utwórz nowe ===
        
        # GUS potwierdził firmę
        if gus_data.found:
            suggestions.append("Dane firmy potwierdzone w GUS")
            if not account_result.exists:
                suggestions.append("Utwórz nowy Account z danymi z GUS")
        
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
            account_id=account_result.parent_id if account_result.exists else None,
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
