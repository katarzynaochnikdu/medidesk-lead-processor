"""
NIP Finder V3 - Advanced NIP search engine.

Main classes:
- NIPFinderV3: Main orchestrator
- NIPRequest, NIPResult: Request/Response models
"""

from .config import NIPFinderV3Settings, get_settings
from .core.orchestrator import NIPFinderV3
from .models import (
    BatchNIPRequest,
    BatchNIPResult,
    NIPRequest,
    NIPResult,
    SearchStrategy,
    ValidationResult,
)

__version__ = "3.0.0-ultimate"

__all__ = [
    "NIPFinderV3",
    "NIPFinderV3Settings",
    "get_settings",
    "NIPRequest",
    "NIPResult",
    "BatchNIPRequest",
    "BatchNIPResult",
    "ValidationResult",
    "SearchStrategy",
]
