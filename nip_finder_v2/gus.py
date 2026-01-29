"""
GUS BIR1 API Client - wyszukiwanie firm po nazwie.

GUS API pozwala szukac firm nie tylko po NIP/REGON, ale tez po nazwie.
To jest "holy grail" - oficjalne zrodlo danych.
"""

import logging
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from zeep import Client
from zeep.transports import Transport
from requests import Session

from .config import get_settings, NIPFinderV2Settings
from .utils import normalize_company_name, calculate_name_similarity

logger = logging.getLogger(__name__)


# GUS API URLs (BIR 1.1)
# Produkcja - wymaga klucza API
GUS_WSDL_PROD = "https://wyszukiwarkaregon.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc?singleWsdl"
# Test - klucz testowy: abcde12345abcde12345
GUS_WSDL_TEST = "https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc?singleWsdl"


@dataclass
class GUSCompany:
    """Dane firmy z GUS."""
    nip: str
    regon: str
    name: str
    city: Optional[str] = None
    street: Optional[str] = None
    zip_code: Optional[str] = None
    voivodeship: Optional[str] = None
    county: Optional[str] = None


class GUSSearch:
    """
    Klient GUS BIR1 API do wyszukiwania firm po nazwie.
    
    Uzycie:
        gus = GUSSearch()
        result = await gus.search_by_name("PragaMed", city="Warszawa")
        if result:
            print(f"Znaleziono NIP: {result.nip}")
    """
    
    def __init__(self, settings: Optional[NIPFinderV2Settings] = None):
        self.settings = settings or get_settings()
        self._client: Optional[Client] = None
        self._session_id: Optional[str] = None
    
    @property
    def wsdl_url(self) -> str:
        """URL do WSDL (prod lub test)."""
        if self.settings.gus_test_mode:
            return GUS_WSDL_TEST
        return GUS_WSDL_PROD
    
    @property
    def api_key(self) -> str:
        """Klucz API."""
        # Klucz testowy dla srodowiska testowego
        if self.settings.gus_test_mode:
            return "abcde12345abcde12345"
        return self.settings.bir1_gus_api_key
    
    def _get_client(self) -> Client:
        """Lazy init klienta SOAP."""
        if self._client is None:
            session = Session()
            session.headers.update({
                "User-Agent": "NIPFinderV2/1.0",
            })
            transport = Transport(session=session, timeout=self.settings.gus_timeout_sec)
            self._client = Client(self.wsdl_url, transport=transport)
        return self._client
    
    def _login(self) -> bool:
        """Logowanie do GUS API."""
        if not self.api_key:
            logger.error("[GUS] Brak klucza API")
            return False
        
        try:
            client = self._get_client()
            result = client.service.Zaloguj(self.api_key)
            
            if result:
                self._session_id = result
                logger.info("[GUS] Zalogowano, session_id=%s", self._session_id[:10] + "...")
                return True
            else:
                logger.error("[GUS] Logowanie nieudane - pusty wynik")
                return False
                
        except Exception as e:
            logger.error("[GUS] Blad logowania: %s", e)
            return False
    
    def _logout(self):
        """Wylogowanie z GUS API."""
        if self._session_id and self._client:
            try:
                self._client.service.Wyloguj(self._session_id)
                logger.info("[GUS] Wylogowano")
            except Exception as e:
                logger.warning("[GUS] Blad wylogowania: %s", e)
            finally:
                self._session_id = None
    
    def _parse_search_result(self, xml_result: str) -> List[GUSCompany]:
        """Parsuje wynik XML z GUS."""
        import xml.etree.ElementTree as ET
        
        companies = []
        
        if not xml_result:
            return companies
        
        try:
            root = ET.fromstring(xml_result)
            
            for dane in root.findall(".//dane"):
                nip = self._get_text(dane, "Nip")
                regon = self._get_text(dane, "Regon")
                name = self._get_text(dane, "Nazwa")
                
                if nip and name:
                    company = GUSCompany(
                        nip=nip,
                        regon=regon or "",
                        name=name,
                        city=self._get_text(dane, "Miejscowosc"),
                        street=self._get_text(dane, "Ulica"),
                        zip_code=self._get_text(dane, "KodPocztowy"),
                        voivodeship=self._get_text(dane, "Wojewodztwo"),
                        county=self._get_text(dane, "Powiat"),
                    )
                    companies.append(company)
                    
        except ET.ParseError as e:
            logger.error("[GUS] Blad parsowania XML: %s", e)
        
        return companies
    
    def _get_text(self, element, tag: str) -> Optional[str]:
        """Pobiera tekst z elementu XML."""
        found = element.find(tag)
        if found is not None and found.text:
            return found.text.strip()
        return None
    
    def search_by_name(
        self,
        company_name: str,
        city: Optional[str] = None,
    ) -> Optional[GUSCompany]:
        """
        Szuka firmy po nazwie w GUS.
        
        Args:
            company_name: Nazwa firmy (moze byc niepelna)
            city: Miasto (opcjonalne, do filtrowania wynikow)
        
        Returns:
            GUSCompany jesli znaleziono, None w przeciwnym razie
        """
        if not self.settings.has_gus_credentials:
            logger.warning("[GUS] Brak klucza API - pomijam wyszukiwanie")
            return None
        
        # Wyczysc nazwe firmy
        clean_name = normalize_company_name(company_name)
        logger.info("[GUS] Szukam: '%s' (city=%s)", clean_name, city)
        
        # Zaloguj sie
        if not self._login():
            return None
        
        try:
            client = self._get_client()
            
            # Przygotuj parametry wyszukiwania
            # GUS API przyjmuje rozne parametry, my uzywamy Nazwy
            search_params = {
                "Nazwa": clean_name,
            }
            
            # Wywolaj wyszukiwanie
            # Metoda: DaneSzukajPodmioty
            result = client.service.DaneSzukajPodmioty(
                _soapheaders={"sid": self._session_id},
                pParametryWyszukiwania=search_params,
            )
            
            if not result:
                logger.info("[GUS] Brak wynikow dla: %s", clean_name)
                return None
            
            # Parsuj wyniki
            companies = self._parse_search_result(result)
            logger.info("[GUS] Znaleziono %d firm", len(companies))
            
            if not companies:
                return None
            
            # Jesli mamy miasto, filtruj
            if city:
                city_lower = city.lower()
                city_matches = [
                    c for c in companies 
                    if c.city and city_lower in c.city.lower()
                ]
                if city_matches:
                    companies = city_matches
                    logger.info("[GUS] Po filtrowaniu po miastem: %d firm", len(companies))
            
            # Wybierz najlepsze dopasowanie nazwy
            best_match = None
            best_score = 0.0
            
            for company in companies:
                score = calculate_name_similarity(company_name, company.name)
                logger.debug("[GUS] %s -> score=%.2f", company.name[:50], score)
                
                if score > best_score:
                    best_score = score
                    best_match = company
            
            if best_match and best_score >= self.settings.name_match_threshold:
                logger.info(
                    "[GUS] Najlepsze dopasowanie: %s (NIP=%s, score=%.2f)",
                    best_match.name[:50], best_match.nip, best_score
                )
                return best_match
            elif best_match:
                logger.warning(
                    "[GUS] Dopasowanie ponizej progu: %s (score=%.2f < %.2f)",
                    best_match.name[:50], best_score, self.settings.name_match_threshold
                )
            
            return None
            
        except Exception as e:
            logger.error("[GUS] Blad wyszukiwania: %s", e)
            return None
            
        finally:
            self._logout()
    
    async def search_by_name_async(
        self,
        company_name: str,
        city: Optional[str] = None,
    ) -> Optional[GUSCompany]:
        """
        Async wrapper dla search_by_name.
        GUS API jest synchroniczne, wiec uruchamiamy w executor.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.search_by_name, company_name, city)
