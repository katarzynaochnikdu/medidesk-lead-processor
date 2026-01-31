"""Utils for NIP Finder V3."""

from .domain_utils import (
    extract_email_domain,
    get_company_domain_from_email,
    is_public_email_domain,
    normalize_domain,
)
from .extractors import (
    extract_addresses_from_text,
    extract_emails_from_text,
    extract_nip_from_text,
    extract_phones_from_text,
    extract_social_links,
    extract_social_links_from_text,
    format_nip,
    validate_nip_checksum,
)
from .normalizers import (
    calculate_name_match_score,
    extract_company_base_name,
    fuzzy_match,
    normalize_company_name,
)
from .rate_limiter import RateLimiter

__all__ = [
    "extract_nip_from_text",
    "extract_emails_from_text",
    "extract_phones_from_text",
    "extract_addresses_from_text",
    "extract_social_links",
    "extract_social_links_from_text",
    "format_nip",
    "validate_nip_checksum",
    "normalize_company_name",
    "extract_company_base_name",
    "fuzzy_match",
    "calculate_name_match_score",
    "extract_email_domain",
    "get_company_domain_from_email",
    "is_public_email_domain",
    "normalize_domain",
    "RateLimiter",
]
