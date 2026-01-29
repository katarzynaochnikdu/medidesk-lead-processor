"""
NIP Finder - moduł do wyszukiwania NIP firm na podstawie minimalnych danych.

Wykorzystuje Apify Actors do scrapingu Google/stron + Vertex AI do inteligentnej ekstrakcji.
"""

__version__ = "0.1.0"
__author__ = "Medidesk"

from .orchestrator import NIPFinder
from .models import NIPRequest, NIPResult

__all__ = ["NIPFinder", "NIPRequest", "NIPResult"]
