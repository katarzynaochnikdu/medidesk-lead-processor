"""
Multi-agent system do przetwarzania lokalizacji.

Struktura:
- CoordinatorAgent: Zarządza przepływem i decyduje co robić
- ParsingAgent: Parsuje adresy (regex)
- EnrichmentAgent: Wzbogaca dane przez Brave Search (gmina/powiat/woj)
- ValidationAgent: Waliduje kompletność danych
"""

import asyncio
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LocationData:
    """Reprezentacja danych lokalizacji."""
    name: Optional[str]
    city: str
    address: str
    postal_code: Optional[str]
    phone: Optional[str]
    source_url: str
    
    # Komponenty adresu (wypełnia ParsingAgent)
    shipping_street: Optional[str] = None
    shipping_street_name: Optional[str] = None
    shipping_building_number: Optional[str] = None
    shipping_local_number: Optional[str] = None
    
    # Szczegóły lokalizacji (wypełnia EnrichmentAgent)
    shipping_gmina: Optional[str] = None
    shipping_powiat: Optional[str] = None
    shipping_state: Optional[str] = None
    
    # Status przetwarzania
    parsed: bool = False
    enriched: bool = False
    complete: bool = False
    
    def to_shipping_fields(self) -> dict:
        """
        Mapuje dane lokalizacji do pól Shipping (filia) w Zoho CRM.
        
        Returns:
            Dict z polami Shipping_* gotowymi do zapisu w Zoho
        """
        return {
            # Pełny adres (jak znaleziono)
            "Shipping_Street": self.shipping_street or self.address,
            
            # Komponenty adresu (parsowane)
            "Shipping_Street_Name": self.shipping_street_name,
            "Shipping_Building_Number": self.shipping_building_number,
            "Shipping_Local_Number": self.shipping_local_number,
            
            # Lokalizacja
            "Shipping_Code": self.postal_code,
            "Shipping_City": self.city,
            "Shipping_Gmina": self.shipping_gmina,
            "Shipping_Powiat": self.shipping_powiat,
            "Shipping_State": self.shipping_state,
            "Shipping_Country": "Polska",
            
            # Dodatkowe
            "Phone": self.phone,
            "Location_Name": self.name,
            "Source_URL": self.source_url,
        }


class ParsingAgent:
    """Agent parsujący adresy na komponenty."""
    
    def parse_address(self, location: LocationData) -> LocationData:
        """Parsuje adres na komponenty ulicy, budynku, lokalu."""
        import re
        
        if not location.address:
            return location
        
        address = location.address.strip()
        location.shipping_street = address
        
        # Wzorce polskich adresów
        patterns = [
            # ul. Nazwa Ulicy 123/45
            r'(?:ul\.|ulica|al\.|aleja)\s+([A-ZŻŹĆĄŚĘŁÓŃ][a-ząćęłńóśźż\w\s\.\-]+?)\s+(\d+[a-zA-Z]?)(?:\s*/\s*([A-Z0-9]+))?',
            # Nazwa Ulicy 123/45 (bez ul.)
            r'^([A-ZŻŹĆĄŚĘŁÓŃ][a-ząćęłńóśźż\w\s\.\-]+?)\s+(\d+[a-zA-Z]?)(?:\s*/\s*([A-Z0-9]+))?$',
        ]
        
        for pattern in patterns:
            match = re.match(pattern, address, re.IGNORECASE)
            if match:
                location.shipping_street_name = match.group(1).strip()
                location.shipping_building_number = match.group(2)
                if match.lastindex >= 3 and match.group(3):
                    location.shipping_local_number = match.group(3)
                location.parsed = True
                break
        
        return location
    
    def batch_parse(self, locations: List[LocationData]) -> List[LocationData]:
        """Parsuje batch lokalizacji."""
        parsed = []
        for loc in locations:
            parsed_loc = self.parse_address(loc)
            parsed.append(parsed_loc)
        
        logger.info("ParsingAgent: Parsed %d locations", len(parsed))
        return parsed


class EnrichmentAgent:
    """Agent wzbogacający dane przez Brave Search."""
    
    def __init__(self, brave_service):
        self.brave = brave_service
    
    async def enrich_location(self, location: LocationData) -> LocationData:
        """Wzbogaca lokalizację o gmina/powiat/województwo."""
        if not location.postal_code or not location.city:
            return location
        
        # Sprawdź czy już wzbogacone
        if location.enriched:
            return location
        
        # Pobierz szczegóły z Brave
        details = await self.brave.find_location_details(
            location.postal_code,
            location.city
        )
        
        location.shipping_gmina = details.get('gmina')
        location.shipping_powiat = details.get('powiat')
        # Województwo małymi literami
        woj = details.get('wojewodztwo')
        location.shipping_state = woj.lower() if woj else None
        location.enriched = True
        
        return location
    
    async def batch_enrich(
        self,
        locations: List[LocationData],
        use_cache: bool = True
    ) -> List[LocationData]:
        """
        Wzbogaca batch lokalizacji z cache'owaniem.
        
        Args:
            locations: Lista lokalizacji
            use_cache: Czy używać cache dla unikalnych (kod, miasto)
        """
        if not use_cache:
            # Bez cache - przetworz każdą lokalizację
            enriched = []
            for loc in locations:
                enriched_loc = await self.enrich_location(loc)
                enriched.append(enriched_loc)
                await asyncio.sleep(1.2)  # Rate limit
            return enriched
        
        # Z cache - pogrupuj unikalne pary (kod, miasto)
        location_cache = {}
        unique_pairs = {}
        
        for idx, loc in enumerate(locations):
            if loc.postal_code and loc.city:
                key = f"{loc.postal_code}|{loc.city}"
                if key not in unique_pairs:
                    unique_pairs[key] = []
                unique_pairs[key].append(idx)
        
        logger.info(
            "EnrichmentAgent: Processing %d unique locations from %d total",
            len(unique_pairs),
            len(locations)
        )
        
        # Pobierz szczegóły dla unikalnych par
        for key in unique_pairs:
            code, city = key.split('|')
            details = await self.brave.find_location_details(code, city)
            location_cache[key] = details
            await asyncio.sleep(1.2)  # Rate limit
        
        # Uzupełnij wszystkie lokalizacje z cache
        enriched = []
        for loc in locations:
            if loc.postal_code and loc.city:
                key = f"{loc.postal_code}|{loc.city}"
                if key in location_cache:
                    details = location_cache[key]
                    loc.shipping_gmina = details.get('gmina')
                    loc.shipping_powiat = details.get('powiat')
                    # Województwo małymi literami
                    woj = details.get('wojewodztwo')
                    loc.shipping_state = woj.lower() if woj else None
                    loc.enriched = True
            enriched.append(loc)
        
        return enriched


class ValidationAgent:
    """Agent walidujący kompletność danych."""
    
    def validate_location(self, location: LocationData) -> LocationData:
        """Sprawdza czy lokalizacja ma wszystkie wymagane dane."""
        required_fields = [
            'city',
            'address',
            'shipping_street_name',
            'shipping_building_number',
        ]
        
        optional_but_important = [
            'postal_code',
            'shipping_gmina',
            'shipping_powiat',
            'shipping_state',
        ]
        
        # Sprawdź wymagane pola
        all_required = all(getattr(location, field) for field in required_fields)
        
        # Sprawdź opcjonalne ale ważne
        important_filled = sum(
            1 for field in optional_but_important
            if getattr(location, field)
        )
        
        # Lokalizacja jest kompletna jeśli ma wszystkie wymagane
        # i co najmniej 2/4 opcjonalnych
        location.complete = all_required and important_filled >= 2
        
        return location
    
    def batch_validate(self, locations: List[LocationData]) -> Dict:
        """Waliduje batch i zwraca statystyki."""
        validated = []
        stats = {
            "total": len(locations),
            "complete": 0,
            "parsed": 0,
            "enriched": 0,
            "missing_parse": 0,
            "missing_enrichment": 0,
        }
        
        for loc in locations:
            validated_loc = self.validate_location(loc)
            validated.append(validated_loc)
            
            if validated_loc.complete:
                stats["complete"] += 1
            if validated_loc.parsed:
                stats["parsed"] += 1
            else:
                stats["missing_parse"] += 1
            if validated_loc.enriched:
                stats["enriched"] += 1
            else:
                stats["missing_enrichment"] += 1
        
        logger.info(
            "ValidationAgent: %d/%d locations complete (parsed: %d, enriched: %d)",
            stats["complete"],
            stats["total"],
            stats["parsed"],
            stats["enriched"],
        )
        
        return {
            "locations": validated,
            "stats": stats,
        }


class CoordinatorAgent:
    """
    Agent koordynujący przepływ przetwarzania lokalizacji.
    
    Decyduje:
    - Czy użyć parsowania AI czy regex
    - Czy potrzebne jest wzbogacenie przez Brave
    - W jakiej kolejności wykonać operacje
    - Czy retry nieudanych operacji
    """
    
    def __init__(self, brave_service):
        self.parsing_agent = ParsingAgent()
        self.enrichment_agent = EnrichmentAgent(brave_service)
        self.validation_agent = ValidationAgent()
    
    async def process_locations(
        self,
        raw_locations: List[Dict],
        strategy: str = "balanced"
    ) -> Dict:
        """
        Przetwarza lokalizacje z wybraną strategią.
        
        Args:
            raw_locations: Lista surowych danych lokalizacji
            strategy: Strategia przetwarzania:
                - "fast": Tylko parsowanie, bez wzbogacania
                - "balanced": Parsowanie + wzbogacanie z cache
                - "complete": Parsowanie + pełne wzbogacanie dla każdej
        
        Returns:
            Dict z przetworzonymi lokalizacjami i metadanymi
        """
        logger.info(
            "CoordinatorAgent: Starting processing of %d locations (strategy: %s)",
            len(raw_locations),
            strategy
        )
        
        # Faza 1: Konwersja do LocationData
        locations = self._convert_to_location_data(raw_locations)
        
        # Faza 2: Parsowanie adresów
        locations = self.parsing_agent.batch_parse(locations)
        
        # Faza 3: Wzbogacanie (zależnie od strategii)
        if strategy == "fast":
            logger.info("CoordinatorAgent: Skipping enrichment (fast mode)")
        elif strategy == "balanced":
            locations = await self.enrichment_agent.batch_enrich(
                locations,
                use_cache=True
            )
        elif strategy == "complete":
            locations = await self.enrichment_agent.batch_enrich(
                locations,
                use_cache=False
            )
        
        # Faza 4: Walidacja
        result = self.validation_agent.batch_validate(locations)
        
        # Konwersja z powrotem do dict
        output_locations = [self._location_to_dict(loc) for loc in result["locations"]]
        
        return {
            "locations": output_locations,
            "stats": result["stats"],
            "strategy": strategy,
        }
    
    def _convert_to_location_data(self, raw_locations: List[Dict]) -> List[LocationData]:
        """Konwertuje surowe dane do LocationData."""
        locations = []
        for raw in raw_locations:
            loc = LocationData(
                name=raw.get('name'),
                city=raw.get('city', ''),
                address=raw.get('address', ''),
                postal_code=raw.get('postal_code'),
                phone=raw.get('phone'),
                source_url=raw.get('source_url', ''),
            )
            locations.append(loc)
        return locations
    
    def _location_to_dict(self, location: LocationData) -> Dict:
        """Konwertuje LocationData do dict dla API response."""
        return {
            "name": location.name,
            "shipping_street": location.shipping_street,
            "shipping_street_name": location.shipping_street_name,
            "shipping_building_number": location.shipping_building_number,
            "shipping_local_number": location.shipping_local_number,
            "shipping_code": location.postal_code,
            "shipping_city": location.city,
            "shipping_gmina": location.shipping_gmina,
            "shipping_powiat": location.shipping_powiat,
            "shipping_state": location.shipping_state,
            "shipping_country": "Polska",
            "phone": location.phone,
            "source_url": location.source_url,
            # Metadane
            "_parsed": location.parsed,
            "_enriched": location.enriched,
            "_complete": location.complete,
        }
