"""Modele danych - Pydantic schemas."""

from .lead_input import LeadInput, LeadInputRaw
from .lead_output import (
    DuplicateMatch,
    DuplicatesResult,
    GUSData,
    LeadOutput,
    NormalizedData,
    ProcessingRecommendation,
    ScrapedContactData,
)
from .evidence_bundle import (
    EvidenceBundle,
    EvidenceSource,
    EvidenceItem,
    ContactEvidence,
    IdentityEvidence,
    LocationEvidence,
    SocialLinksEvidence,
    AIOutputs,
    ProcessingCost,
    # API Contracts
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

__all__ = [
    # Lead Input/Output
    "LeadInput",
    "LeadInputRaw",
    "LeadOutput",
    "NormalizedData",
    "GUSData",
    "DuplicateMatch",
    "DuplicatesResult",
    "ProcessingRecommendation",
    "ScrapedContactData",
    # Evidence Bundle
    "EvidenceBundle",
    "EvidenceSource",
    "EvidenceItem",
    "ContactEvidence",
    "IdentityEvidence",
    "LocationEvidence",
    "SocialLinksEvidence",
    "AIOutputs",
    "ProcessingCost",
    # API Contracts
    "LeadNormalizeRequest",
    "LeadNormalizeResponse",
    "LeadEnrichCoreRequest",
    "LeadEnrichCoreResponse",
    "LeadDedupeRequest",
    "LeadDedupeResponse",
    "OrgEnrichCoreRequest",
    "OrgEnrichCoreResponse",
    "OrgEnrichSocialRequest",
    "OrgEnrichSocialResponse",
]
