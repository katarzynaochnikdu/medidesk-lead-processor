"""
Multi-tier validation orchestrator.

Koordynuje walidację NIP przez wszystkie 3 walidatory:
1. Checksum (wymagana)
2. Domain (jeśli domena dostępna)
3. GUS (opcjonalna)
"""

import logging
from typing import Optional

from ..config import NIPFinderV3Settings, get_settings
from ..models import ValidationResult
from .checksum import ChecksumValidator
from .domain_validator import DomainValidator
from .gus_validator import GUSValidator

logger = logging.getLogger(__name__)


class NIPValidator:
    """
    Multi-tier NIP validator.

    Koordynuje walidację przez:
    - Checksum (zawsze)
    - Domain (jeśli domena dostępna)
    - GUS (opcjonalnie)
    """

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()
        self.checksum_validator = ChecksumValidator()
        self.domain_validator = DomainValidator(settings)
        self.gus_validator = GUSValidator(settings)

    async def close(self):
        """Close resources."""
        await self.domain_validator.close()

    async def validate(
        self,
        nip: str,
        company_name: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> ValidationResult:
        """
        Waliduje NIP przez wszystkie dostępne metody.

        Args:
            nip: NIP do walidacji
            company_name: Nazwa firmy (dla GUS cross-reference)
            domain: Domena firmowa (dla domain validation)

        Returns:
            ValidationResult z wynikami wszystkich walidacji
        """
        logger.info("Validator: walidacja NIP %s", nip)

        errors = []

        # ============================================
        # TIER 1: Checksum (wymagana)
        # ============================================
        checksum_valid = self.checksum_validator.validate(nip)

        if not checksum_valid:
            logger.error("❌ Validator: checksum niepoprawny dla NIP %s", nip)
            return ValidationResult(
                validated=False,
                checksum_valid=False,
                domain_valid=None,
                gus_found=None,
                gus_name=None,
                name_match_score=None,
                errors=["Niepoprawny checksum NIP"],
            )

        logger.info("✅ Validator: checksum poprawny")

        # ============================================
        # TIER 2: Domain validation (jeśli domena)
        # ============================================
        domain_valid: Optional[bool] = None
        domain_skipped = False

        if domain and self.settings.require_domain_validation:
            # Sprawdź czy to registry domain (portal, rejestr) lub domena nie pasuje do firmy
            if self.domain_validator.is_registry_domain(domain, company_name):
                logger.info("⏭️ Validator: %s to registry/portal (lub nie pasuje do '%s') - pomijam walidację domeny", 
                          domain, company_name)
                domain_skipped = True
                domain_valid = None  # Nie sprawdzano
            else:
                logger.info("Validator: sprawdzam domenę %s", domain)
                domain_valid = await self.domain_validator.validate(nip, domain)

                if domain_valid is False:
                    errors.append(f"NIP nie znaleziony na domenie {domain}")
                    logger.warning("⚠️ Validator: NIP nie zwalidowany z domeną")

        # ============================================
        # TIER 3: GUS cross-reference (opcjonalna)
        # ============================================
        gus_found: Optional[bool] = None
        gus_name: Optional[str] = None
        name_match_score: Optional[float] = None

        if company_name and self.settings.require_gus_validation:
            logger.info("Validator: sprawdzam GUS dla firmy '%s'", company_name)
            gus_found, gus_name, name_match_score = await self.gus_validator.validate(
                nip, company_name
            )

            if gus_found and name_match_score is not None:
                if name_match_score < self.settings.fuzzy_match_threshold:
                    errors.append(
                        f"Niska zgodność nazwy: {company_name} vs {gus_name} "
                        f"(score: {name_match_score:.2f})"
                    )
                    logger.warning("⚠️ Validator: niska zgodność nazwy z GUS")

        # ============================================
        # Całościowa walidacja
        # ============================================
        # domain_valid: True=OK, False=FAIL, None=skipped (registry domain)
        # Dla registry domains: domain_skipped=True, domain_valid=None -> traktuj jako OK
        domain_ok = (
            domain_skipped  # Registry domain - pomiń
            or domain_valid is True  # Zwalidowano pomyślnie
            or domain_valid is None  # Nie sprawdzano
            or not self.settings.require_domain_validation  # Walidacja wyłączona
        )
        
        validated = (
            checksum_valid  # Checksum musi być OK
            and domain_ok  # Domena OK lub pominięta
            and (not self.settings.require_gus_validation or
                 (gus_found and (name_match_score or 0.0) >= self.settings.fuzzy_match_threshold))
        )

        if validated:
            logger.info("✅ Validator: NIP %s w pełni zwalidowany", nip)
        else:
            logger.warning("⚠️ Validator: NIP %s nie przeszedł pełnej walidacji", nip)

        return ValidationResult(
            validated=validated,
            checksum_valid=checksum_valid,
            domain_valid=domain_valid,
            gus_found=gus_found,
            gus_name=gus_name,
            name_match_score=name_match_score,
            errors=errors,
        )
