"""
SQLite cache dla NIP Finder V3.

Cache structure:
- Key: (company_name_normalized, city_normalized)
- Value: nip, confidence, strategy, validation_json, created_at
- TTL: 30 days (configurable)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from ..config import NIPFinderV3Settings, get_settings
from ..models import CacheEntry, ValidationResult
from ..utils import normalize_company_name

logger = logging.getLogger(__name__)


class NIPCache:
    """
    SQLite cache for NIP results.

    Features:
    - Async operations
    - TTL management (30 days default)
    - Freshness warnings (14 days)
    - Auto-cleanup of expired entries
    """

    def __init__(self, settings: Optional[NIPFinderV3Settings] = None):
        self.settings = settings or get_settings()
        self._db: Optional[aiosqlite.Connection] = None
        self._initialized = False

    async def _ensure_initialized(self):
        """Ensure database is initialized."""
        if not self._initialized:
            await self._initialize()
            self._initialized = True

    async def _initialize(self):
        """Initialize database and create schema."""
        # Ensure directory exists
        db_path = Path(self.settings.cache_db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connect to database
        self._db = await aiosqlite.connect(str(db_path))

        # Create table
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS nip_cache (
                company_name TEXT NOT NULL,
                city TEXT,
                nip TEXT,
                confidence REAL,
                strategy TEXT,
                validation_json TEXT,
                created_at TEXT,
                last_updated_at TEXT,
                PRIMARY KEY (company_name, city)
            )
        """)

        # Create indexes
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_nip ON nip_cache(nip)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at ON nip_cache(created_at)
        """)

        await self._db.commit()

        logger.info("Cache initialized: %s", db_path)

    async def close(self):
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            self._initialized = False
            logger.info("Cache closed")

    def _normalize_key(self, company_name: str, city: Optional[str]) -> tuple:
        """
        Normalize cache key.

        Args:
            company_name: Company name
            city: City

        Returns:
            Tuple (normalized_company_name, normalized_city)
        """
        norm_company = normalize_company_name(company_name)
        norm_city = city.lower().strip() if city else None
        return (norm_company, norm_city)

    async def get(
        self,
        company_name: str,
        city: Optional[str] = None,
    ) -> Optional[CacheEntry]:
        """
        Get cached NIP result.

        Args:
            company_name: Company name
            city: City

        Returns:
            CacheEntry if found and not expired, None otherwise
        """
        await self._ensure_initialized()

        key_company, key_city = self._normalize_key(company_name, city)

        async with self._db.execute(
            """
            SELECT company_name, city, nip, confidence, strategy,
                   validation_json, created_at, last_updated_at
            FROM nip_cache
            WHERE company_name = ? AND city IS ?
            """,
            (key_company, key_city),
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            logger.debug("Cache miss: %s, %s", company_name, city)
            return None

        # Parse row
        entry = CacheEntry(
            company_name=row[0],
            city=row[1],
            nip=row[2],
            confidence=row[3],
            strategy=row[4],
            validation_json=row[5],
            created_at=datetime.fromisoformat(row[6]),
            last_updated_at=datetime.fromisoformat(row[7]),
        )

        # Check if expired
        if entry.is_expired(ttl_days=self.settings.cache_ttl_days):
            logger.info("Cache expired: %s, %s (age: %d days)",
                       company_name, city, entry.age_days())
            # Delete expired entry
            await self.delete(company_name, city)
            return None

        logger.info("✅ Cache hit: %s, %s (age: %d days)",
                   company_name, city, entry.age_days())
        return entry

    async def set(
        self,
        company_name: str,
        city: Optional[str],
        nip: Optional[str],
        confidence: float,
        strategy: str,
        validation: Optional[ValidationResult],
    ):
        """
        Save result to cache.

        Args:
            company_name: Company name
            city: City
            nip: NIP (or None if not found)
            confidence: Confidence score
            strategy: Strategy used
            validation: Validation result
        """
        await self._ensure_initialized()

        key_company, key_city = self._normalize_key(company_name, city)

        # Serialize validation
        validation_json = validation.model_dump_json() if validation else "{}"

        # Current timestamp
        now = datetime.utcnow().isoformat()

        # Upsert
        await self._db.execute(
            """
            INSERT OR REPLACE INTO nip_cache
            (company_name, city, nip, confidence, strategy, validation_json,
             created_at, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (key_company, key_city, nip, confidence, strategy, validation_json, now, now),
        )

        await self._db.commit()

        logger.info("Cache saved: %s, %s -> NIP=%s", company_name, city, nip)

    async def delete(self, company_name: str, city: Optional[str]):
        """
        Delete entry from cache.

        Args:
            company_name: Company name
            city: City
        """
        await self._ensure_initialized()

        key_company, key_city = self._normalize_key(company_name, city)

        await self._db.execute(
            """
            DELETE FROM nip_cache
            WHERE company_name = ? AND city IS ?
            """,
            (key_company, key_city),
        )

        await self._db.commit()

        logger.debug("Cache deleted: %s, %s", company_name, city)

    async def clear_expired(self):
        """Delete all expired entries."""
        await self._ensure_initialized()

        cutoff = datetime.utcnow().isoformat()

        result = await self._db.execute(
            """
            DELETE FROM nip_cache
            WHERE julianday('now') - julianday(created_at) > ?
            """,
            (self.settings.cache_ttl_days,),
        )

        await self._db.commit()

        deleted = result.rowcount
        logger.info("Cache cleanup: deleted %d expired entries", deleted)

        return deleted

    async def stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dict with stats
        """
        await self._ensure_initialized()

        # Total entries
        async with self._db.execute("SELECT COUNT(*) FROM nip_cache") as cursor:
            row = await cursor.fetchone()
            total = row[0]

        # Found (nip IS NOT NULL)
        async with self._db.execute(
            "SELECT COUNT(*) FROM nip_cache WHERE nip IS NOT NULL"
        ) as cursor:
            row = await cursor.fetchone()
            found = row[0]

        # Not found (nip IS NULL)
        not_found = total - found

        # Expired
        async with self._db.execute(
            """
            SELECT COUNT(*) FROM nip_cache
            WHERE julianday('now') - julianday(created_at) > ?
            """,
            (self.settings.cache_ttl_days,),
        ) as cursor:
            row = await cursor.fetchone()
            expired = row[0]

        return {
            "total_entries": total,
            "found": found,
            "not_found": not_found,
            "expired": expired,
            "ttl_days": self.settings.cache_ttl_days,
        }
