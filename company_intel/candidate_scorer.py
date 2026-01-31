"""
CandidateScorer - wspólny scoring kandydatów NIP/WWW.

Jeden scoring niezależny od metody (Google, Brave, AI, Zoho).
Polityka decyzji: ACCEPT / SUSPECT / REJECT.
"""

import logging
import re
from typing import Optional

from .models import (
    NIPCandidate,
    CandidateEvidence,
    CandidateDecision,
    EvidenceType,
    ChaoticLeadParsed,
)

logger = logging.getLogger(__name__)


# Blacklista domen - agregatory i marketplace
BLACKLISTED_DOMAINS = {
    "wyjatkowyprezent.pl",
    "groupon.pl",
    "allegro.pl",
    "olx.pl",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
}

# Greylista - źródła o średniej wiarygodności
GREYLIST_DOMAINS = {
    "znamifirme.pl",
    "panoramafirm.pl",
    "firmy.net",
    "pkt.pl",
    "yelp.pl",
}

# Whitelist - rejestry i oficjalne źródła
REGISTRY_DOMAINS = {
    "aleo.com",
    "rejestr.io",
    "krs-online.com.pl",
    "ceidg.gov.pl",
    "gus.gov.pl",
    "biznes.gov.pl",
    "infoveriti.pl",
}


def validate_nip_checksum(nip: str) -> bool:
    """
    Waliduje checksum NIP.
    
    NIP ma 10 cyfr, ostatnia to checksum.
    Wagi: 6, 5, 7, 2, 3, 4, 5, 6, 7
    """
    # Usuń wszystko poza cyframi
    digits = re.sub(r'\D', '', nip)
    
    if len(digits) != 10:
        return False
    
    weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    total = sum(int(d) * w for d, w in zip(digits[:9], weights))
    checksum = total % 11
    
    # Checksum nie może być 10
    if checksum == 10:
        return False
    
    return checksum == int(digits[9])


def calculate_fuzzy_name_match(name1: str, name2: str) -> float:
    """
    Oblicza fuzzy match między dwiema nazwami.
    
    Returns:
        Score 0.0 - 1.0
    """
    if not name1 or not name2:
        return 0.0
    
    # Normalizuj
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    
    # Dokładne dopasowanie
    if n1 == n2:
        return 1.0
    
    # Jedna zawiera drugą
    if n1 in n2 or n2 in n1:
        shorter = min(len(n1), len(n2))
        longer = max(len(n1), len(n2))
        return 0.7 + 0.3 * (shorter / longer)
    
    # Porównanie słów (set intersection)
    words1 = set(n1.split())
    words2 = set(n2.split())
    
    if not words1 or not words2:
        return 0.0
    
    common = words1 & words2
    total = words1 | words2
    
    return len(common) / len(total)


def get_domain_from_url(url: str) -> str:
    """Wyciąga domenę z URL."""
    domain = url.lower()
    domain = re.sub(r'^https?://', '', domain)
    domain = domain.replace("www.", "")
    domain = domain.split("/")[0]
    return domain


class CandidateScorer:
    """
    Wspólny scorer dla kandydatów NIP.
    
    Scoring:
    - score_id: twarde potwierdzenia (GUS, NIP na domenie, Zoho)
    - score_match: miękkie dopasowania (fuzzy nazwa, lokalizacja)
    - score_source: wiarygodność źródła (registry > official > blog > aggregator)
    
    Decyzje:
    - ACCEPT: checksum OK + twarde potwierdzenie
    - SUSPECT: checksum OK, ale konflikt lub brak potwierdzenia
    - REJECT: checksum fail / blacklist / źródło niewiarygodne
    """
    
    # Progi decyzji
    ACCEPT_THRESHOLD = 50  # Minimalna suma punktów do ACCEPT
    SUSPECT_THRESHOLD = 20  # Poniżej = REJECT
    
    # Punktacja
    SCORE_CHECKSUM_OK = 10
    SCORE_GUS_HIT = 30
    SCORE_GUS_NAME_MATCH = 15
    SCORE_GUS_NAME_MISMATCH = -20
    SCORE_NIP_ON_DOMAIN = 25
    SCORE_ZOHO_HIT = 25
    SCORE_FUZZY_NAME_HIGH = 10  # fuzzy >= 0.8
    SCORE_FUZZY_NAME_MEDIUM = 5  # fuzzy >= 0.5
    SCORE_SOURCE_REGISTRY = 15
    SCORE_SOURCE_OFFICIAL = 10
    SCORE_SOURCE_GREYLIST = -5
    SCORE_SOURCE_BLACKLIST = -30
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def create_candidate(self, nip: str) -> NIPCandidate:
        """Tworzy nowego kandydata NIP."""
        return NIPCandidate(nip=nip)
    
    def add_checksum_evidence(self, candidate: NIPCandidate) -> bool:
        """
        Dodaje dowód walidacji checksum.
        
        Returns:
            True jeśli checksum OK
        """
        is_valid = validate_nip_checksum(candidate.nip)
        
        if is_valid:
            candidate.add_evidence(CandidateEvidence(
                evidence_type=EvidenceType.CHECKSUM_OK,
                source="checksum",
                value=candidate.nip,
                score=self.SCORE_CHECKSUM_OK,
                details="NIP checksum valid",
            ))
            self.logger.debug("[SCORER] NIP %s: checksum OK (+%d)", candidate.nip, self.SCORE_CHECKSUM_OK)
        else:
            # Checksum fail = natychmiastowy REJECT
            candidate.decision = CandidateDecision.REJECT
            candidate.decision_reason = "Invalid NIP checksum"
            self.logger.warning("[SCORER] NIP %s: checksum FAIL -> REJECT", candidate.nip)
        
        return is_valid
    
    def add_gus_evidence(
        self,
        candidate: NIPCandidate,
        gus_found: bool,
        gus_name: Optional[str] = None,
        gus_city: Optional[str] = None,
        gus_street: Optional[str] = None,
        input_name: Optional[str] = None,
    ) -> None:
        """
        Dodaje dowód z GUS.
        
        Args:
            candidate: Kandydat NIP
            gus_found: Czy GUS zwrócił rekord
            gus_name: Nazwa z GUS
            gus_city: Miasto z GUS
            gus_street: Ulica z GUS
            input_name: Nazwa z inputu (do porównania)
        """
        if gus_found:
            candidate.add_evidence(CandidateEvidence(
                evidence_type=EvidenceType.GUS_HIT,
                source="gus",
                value=gus_name,
                score=self.SCORE_GUS_HIT,
                details=f"GUS found: {gus_name[:50] if gus_name else '?'}",
            ))
            candidate.gus_name = gus_name
            candidate.gus_city = gus_city
            candidate.gus_street = gus_street
            
            self.logger.info(
                "[SCORER] NIP %s: GUS HIT (+%d) - '%s'",
                candidate.nip,
                self.SCORE_GUS_HIT,
                gus_name[:40] if gus_name else "?",
            )
            
            # Sprawdź dopasowanie nazwy
            if input_name and gus_name:
                fuzzy_score = calculate_fuzzy_name_match(input_name, gus_name)
                
                if fuzzy_score >= 0.5:
                    candidate.add_evidence(CandidateEvidence(
                        evidence_type=EvidenceType.GUS_NAME_MATCH,
                        source="gus_name_match",
                        value=f"{input_name} ~ {gus_name}",
                        score=self.SCORE_GUS_NAME_MATCH,
                        details=f"Fuzzy match: {fuzzy_score:.2f}",
                    ))
                    self.logger.info(
                        "[SCORER] NIP %s: name match (+%d) fuzzy=%.2f",
                        candidate.nip,
                        self.SCORE_GUS_NAME_MATCH,
                        fuzzy_score,
                    )
                else:
                    # Nazwa mocno nie pasuje - NIP podejrzany
                    candidate.add_evidence(CandidateEvidence(
                        evidence_type=EvidenceType.GUS_NAME_MISMATCH,
                        source="gus_name_mismatch",
                        value=f"{input_name} != {gus_name}",
                        score=self.SCORE_GUS_NAME_MISMATCH,
                        details=f"Name mismatch: {fuzzy_score:.2f}",
                    ))
                    self.logger.warning(
                        "[SCORER] NIP %s: name MISMATCH (%d) fuzzy=%.2f",
                        candidate.nip,
                        self.SCORE_GUS_NAME_MISMATCH,
                        fuzzy_score,
                    )
        else:
            self.logger.warning("[SCORER] NIP %s: GUS not found", candidate.nip)
    
    def add_domain_evidence(
        self,
        candidate: NIPCandidate,
        nip_found_on_domain: bool,
        domain: str,
    ) -> None:
        """
        Dodaje dowód że NIP został znaleziony na domenie.
        """
        if nip_found_on_domain:
            candidate.add_evidence(CandidateEvidence(
                evidence_type=EvidenceType.NIP_ON_DOMAIN,
                source="domain_scrape",
                value=domain,
                score=self.SCORE_NIP_ON_DOMAIN,
                details=f"NIP found on {domain}",
            ))
            self.logger.info(
                "[SCORER] NIP %s: found on domain (+%d) %s",
                candidate.nip,
                self.SCORE_NIP_ON_DOMAIN,
                domain,
            )
    
    def add_zoho_evidence(
        self,
        candidate: NIPCandidate,
        zoho_found: bool,
        zoho_name: Optional[str] = None,
    ) -> None:
        """
        Dodaje dowód z Zoho.
        """
        if zoho_found:
            candidate.add_evidence(CandidateEvidence(
                evidence_type=EvidenceType.ZOHO_HIT,
                source="zoho",
                value=zoho_name,
                score=self.SCORE_ZOHO_HIT,
                details=f"Found in Zoho CRM: {zoho_name}",
            ))
            self.logger.info(
                "[SCORER] NIP %s: Zoho HIT (+%d) - '%s'",
                candidate.nip,
                self.SCORE_ZOHO_HIT,
                zoho_name[:40] if zoho_name else "?",
            )
    
    def add_source_evidence(
        self,
        candidate: NIPCandidate,
        source_url: str,
    ) -> None:
        """
        Dodaje dowód wiarygodności źródła.
        """
        domain = get_domain_from_url(source_url)
        
        if domain in BLACKLISTED_DOMAINS:
            candidate.add_evidence(CandidateEvidence(
                evidence_type=EvidenceType.SOURCE_BLACKLIST,
                source="source_check",
                value=domain,
                score=self.SCORE_SOURCE_BLACKLIST,
                details=f"Blacklisted source: {domain}",
            ))
            self.logger.warning(
                "[SCORER] NIP %s: blacklisted source (%d) %s",
                candidate.nip,
                self.SCORE_SOURCE_BLACKLIST,
                domain,
            )
        elif domain in REGISTRY_DOMAINS:
            candidate.add_evidence(CandidateEvidence(
                evidence_type=EvidenceType.SOURCE_REGISTRY,
                source="source_check",
                value=domain,
                score=self.SCORE_SOURCE_REGISTRY,
                details=f"Registry source: {domain}",
            ))
            self.logger.info(
                "[SCORER] NIP %s: registry source (+%d) %s",
                candidate.nip,
                self.SCORE_SOURCE_REGISTRY,
                domain,
            )
        elif domain in GREYLIST_DOMAINS:
            candidate.add_evidence(CandidateEvidence(
                evidence_type=EvidenceType.SOURCE_AGGREGATOR,
                source="source_check",
                value=domain,
                score=self.SCORE_SOURCE_GREYLIST,
                details=f"Greylist source: {domain}",
            ))
            self.logger.debug(
                "[SCORER] NIP %s: greylist source (%d) %s",
                candidate.nip,
                self.SCORE_SOURCE_GREYLIST,
                domain,
            )
        else:
            # Nieznane źródło - neutralne lub lekki bonus dla oficjalnych stron
            if self._looks_like_official_domain(domain, candidate.gus_name):
                candidate.add_evidence(CandidateEvidence(
                    evidence_type=EvidenceType.SOURCE_OFFICIAL,
                    source="source_check",
                    value=domain,
                    score=self.SCORE_SOURCE_OFFICIAL,
                    details=f"Likely official: {domain}",
                ))
                self.logger.info(
                    "[SCORER] NIP %s: official source (+%d) %s",
                    candidate.nip,
                    self.SCORE_SOURCE_OFFICIAL,
                    domain,
                )
    
    def _looks_like_official_domain(self, domain: str, company_name: Optional[str]) -> bool:
        """
        Sprawdza czy domena wygląda na oficjalną stronę firmy.
        """
        if not company_name:
            return False
        
        # Wyciągnij słowa kluczowe z nazwy firmy
        name_words = set(company_name.lower().split())
        
        # Usuń typowe słowa
        name_words -= {"sp", "zoo", "spółka", "z", "o", "sa", "sp.", "z.o.o.", "s.a."}
        
        # Sprawdź czy którekolwiek słowo jest w domenie
        domain_lower = domain.lower()
        for word in name_words:
            if len(word) >= 3 and word in domain_lower:
                return True
        
        return False
    
    def make_decision(self, candidate: NIPCandidate) -> CandidateDecision:
        """
        Podejmuje decyzję o kandydacie na podstawie zebranego scoringu.
        
        Returns:
            CandidateDecision (ACCEPT / SUSPECT / REJECT)
        """
        # Jeśli już REJECT (np. checksum fail) - nie zmieniaj
        if candidate.decision == CandidateDecision.REJECT:
            return candidate.decision
        
        total = candidate.total_score
        
        # Sprawdź czy ma twarde potwierdzenie (GUS lub NIP na domenie lub Zoho)
        has_hard_confirmation = any(
            e.evidence_type in [
                EvidenceType.GUS_HIT,
                EvidenceType.NIP_ON_DOMAIN,
                EvidenceType.ZOHO_HIT,
            ]
            for e in candidate.evidences
        )
        
        # Sprawdź czy ma name mismatch
        has_name_mismatch = any(
            e.evidence_type == EvidenceType.GUS_NAME_MISMATCH
            for e in candidate.evidences
        )
        
        # Decyzja
        if total >= self.ACCEPT_THRESHOLD and has_hard_confirmation and not has_name_mismatch:
            candidate.decision = CandidateDecision.ACCEPT
            candidate.decision_reason = f"Score {total} >= {self.ACCEPT_THRESHOLD}, hard confirmation present"
        elif total >= self.SUSPECT_THRESHOLD:
            candidate.decision = CandidateDecision.SUSPECT
            if has_name_mismatch:
                candidate.decision_reason = f"Score {total}, but name mismatch - needs additional confirmation"
            elif not has_hard_confirmation:
                candidate.decision_reason = f"Score {total}, but no hard confirmation"
            else:
                candidate.decision_reason = f"Score {total} < {self.ACCEPT_THRESHOLD}"
        else:
            candidate.decision = CandidateDecision.REJECT
            candidate.decision_reason = f"Score {total} < {self.SUSPECT_THRESHOLD}"
        
        self.logger.info(
            "[SCORER] NIP %s: DECISION=%s (score=%d, hard_confirm=%s, mismatch=%s) - %s",
            candidate.nip,
            candidate.decision.value,
            total,
            has_hard_confirmation,
            has_name_mismatch,
            candidate.decision_reason,
        )
        
        return candidate.decision
    
    def score_and_decide(
        self,
        nip: str,
        gus_found: bool = False,
        gus_name: Optional[str] = None,
        gus_city: Optional[str] = None,
        gus_street: Optional[str] = None,
        input_name: Optional[str] = None,
        nip_on_domain: bool = False,
        domain: Optional[str] = None,
        zoho_found: bool = False,
        zoho_name: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> NIPCandidate:
        """
        Convenience method - tworzy kandydata, dodaje wszystkie dowody i podejmuje decyzję.
        
        Returns:
            NIPCandidate z decyzją
        """
        candidate = self.create_candidate(nip)
        
        # 1. Checksum
        if not self.add_checksum_evidence(candidate):
            return candidate  # REJECT
        
        # 2. GUS
        if gus_found:
            self.add_gus_evidence(
                candidate,
                gus_found=True,
                gus_name=gus_name,
                gus_city=gus_city,
                gus_street=gus_street,
                input_name=input_name,
            )
        
        # 3. Domain
        if nip_on_domain and domain:
            self.add_domain_evidence(candidate, True, domain)
        
        # 4. Zoho
        if zoho_found:
            self.add_zoho_evidence(candidate, True, zoho_name)
        
        # 5. Source
        if source_url:
            self.add_source_evidence(candidate, source_url)
        
        # 6. Decyzja
        self.make_decision(candidate)
        
        return candidate
