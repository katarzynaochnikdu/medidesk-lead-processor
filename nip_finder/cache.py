"""
Cache dla wyników wyszukiwania NIP.
SQLite + aiosqlite dla async operations.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite

from .models import CacheEntry, ValidationResult

logger = logging.getLogger(__name__)


class NIPCache:
    """
    Cache wyników wyszukiwania NIP w SQLite.
    
    Schema:
    - company_name (key)
    - city (key, opcjonalne)
    - nip
    - confidence
    - found
    - created_at
    - last_validated_at
    - validation_json (JSON z ValidationResult)
    """
    
    def __init__(self, settings: Optional[object] = None):
        """
        Args:
            settings: NIPFinderSettings (opcjonalne)
        """
        self.settings = settings
        self.db_path = settings.nip_cache_db if settings else "nip_finder/cache.db"
        self.ttl_days = settings.nip_cache_ttl_days if settings else 30
        self._db: Optional[aiosqlite.Connection] = None
        self._initialized = False
    
    async def _ensure_initialized(self):
        """Lazy initialization - tworzy tabelę jeśli nie istnieje."""
        if self._initialized:
            return
        
        try:
            self._db = await aiosqlite.connect(self.db_path)
            
            # Utwórz tabelę
            await self._db.execute("""
                CREATE TABLE IF NOT EXISTS nip_cache (
                    company_name TEXT NOT NULL,
                    city TEXT,
                    nip TEXT,
                    confidence REAL NOT NULL,
                    found INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    last_validated_at TEXT,
                    validation_json TEXT,
                    PRIMARY KEY (company_name, city)
                )
            """)
            
            # Index dla szybszego wyszukiwania
            await self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_nip ON nip_cache(nip)
            """)
            
            await self._db.commit()
            
            self._initialized = True
            logger.info("[OK] Cache zainicjalizowany: %s", self.db_path)
            
        except Exception as e:
            logger.error("[ERROR] Błąd inicjalizacji cache: %s", e)
            raise
    
    async def get(
        self,
        company_name: str,
        city: Optional[str] = None,
    ) -> Optional[CacheEntry]:
        """
        Pobiera wpis z cache.
        
        Args:
            company_name: Nazwa firmy
            city: Miasto (opcjonalne)
        
        Returns:
            CacheEntry lub None jeśli nie znaleziono / wygasło
        """
        await self._ensure_initialized()
        
        # Normalizuj klucze
        company_name = company_name.strip().lower()
        city = city.strip().lower() if city else None
        
        try:
            cursor = await self._db.execute(
                """
                SELECT company_name, city, nip, confidence, found, 
                       created_at, last_validated_at, validation_json
                FROM nip_cache
                WHERE LOWER(company_name) = ? AND (LOWER(city) = ? OR (city IS NULL AND ? IS NULL))
                """,
                (company_name, city, city)
            )
            
            row = await cursor.fetchone()
            
            if not row:
                logger.debug("Cache MISS: %s (city: %s)", company_name, city or "brak")
                return None
            
            # Parsuj row
            created_at = datetime.fromisoformat(row[5])
            last_validated_at = datetime.fromisoformat(row[6]) if row[6] else None
            
            # Sprawdź TTL
            age_days = (datetime.utcnow() - created_at).days
            if age_days > self.ttl_days:
                logger.info("Cache EXPIRED: %s (age: %d days)", company_name, age_days)
                # Usuń wygasły wpis
                await self.delete(company_name, city)
                return None
            
            # Parsuj validation JSON
            validation_result = None
            if row[7]:
                try:
                    validation_dict = json.loads(row[7])
                    validation_result = ValidationResult(**validation_dict)
                except Exception as e:
                    logger.warning("Błąd parsowania validation JSON: %s", e)
            
            entry = CacheEntry(
                company_name=row[0],
                city=row[1],
                nip=row[2],
                confidence=row[3],
                found=bool(row[4]),
                created_at=created_at,
                last_validated_at=last_validated_at,
                validation_result=validation_result,
            )
            
            logger.info("Cache HIT: %s -> NIP=%s (age: %d days)", 
                       company_name, entry.nip or "brak", age_days)
            
            return entry
            
        except Exception as e:
            logger.error("Błąd odczytu cache: %s", e)
            return None
    
    async def set(
        self,
        company_name: str,
        city: Optional[str],
        nip: Optional[str],
        confidence: float,
        validation_result: Optional[ValidationResult] = None,
    ):
        """
        Zapisuje wpis do cache.
        
        Args:
            company_name: Nazwa firmy
            city: Miasto (opcjonalne)
            nip: NIP (może być None jeśli nie znaleziono)
            confidence: Confidence (0-1)
            validation_result: Wynik walidacji (opcjonalne)
        """
        await self._ensure_initialized()
        
        # Normalizuj klucze
        company_name_normalized = company_name.strip().lower()
        city_normalized = city.strip().lower() if city else None
        
        try:
            # Serialize validation
            validation_json = None
            if validation_result:
                validation_json = json.dumps(validation_result.model_dump())
            
            now = datetime.utcnow().isoformat()
            
            # UPSERT (INSERT OR REPLACE)
            await self._db.execute(
                """
                INSERT OR REPLACE INTO nip_cache 
                (company_name, city, nip, confidence, found, created_at, last_validated_at, validation_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company_name_normalized,
                    city_normalized,
                    nip,
                    confidence,
                    1 if nip else 0,
                    now,
                    now if validation_result else None,
                    validation_json,
                )
            )
            
            await self._db.commit()
            
            logger.info("[SAVE] Cache SET: %s (city: %s) -> NIP=%s", 
                       company_name, city or "brak", nip or "brak")
            
        except Exception as e:
            logger.error("[ERROR] Błąd zapisu cache: %s", e)
    
    async def delete(self, company_name: str, city: Optional[str] = None):
        """Usuwa wpis z cache."""
        await self._ensure_initialized()
        
        company_name = company_name.strip().lower()
        city = city.strip().lower() if city else None
        
        try:
            await self._db.execute(
                """
                DELETE FROM nip_cache
                WHERE LOWER(company_name) = ? AND (LOWER(city) = ? OR (city IS NULL AND ? IS NULL))
                """,
                (company_name, city, city)
            )
            await self._db.commit()
            
            logger.info("🗑️ Cache DELETE: %s (city: %s)", company_name, city or "brak")
            
        except Exception as e:
            logger.error("Błąd usuwania z cache: %s", e)
    
    async def clear_expired(self):
        """Usuwa wygasłe wpisy z cache."""
        await self._ensure_initialized()
        
        try:
            cutoff = (datetime.utcnow() - timedelta(days=self.ttl_days)).isoformat()
            
            cursor = await self._db.execute(
                "DELETE FROM nip_cache WHERE created_at < ?",
                (cutoff,)
            )
            await self._db.commit()
            
            deleted_count = cursor.rowcount
            logger.info("[CLEAN] Cache cleanup: usunieto %d wygaslych wpisow", deleted_count)
            
        except Exception as e:
            logger.error("Błąd czyszczenia cache: %s", e)
    
    async def stats(self) -> dict:
        """Zwraca statystyki cache."""
        await self._ensure_initialized()
        
        try:
            # Total entries
            cursor = await self._db.execute("SELECT COUNT(*) FROM nip_cache")
            total = (await cursor.fetchone())[0]
            
            # Found vs not found
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM nip_cache WHERE found = 1"
            )
            found_count = (await cursor.fetchone())[0]
            
            # Expired
            cutoff = (datetime.utcnow() - timedelta(days=self.ttl_days)).isoformat()
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM nip_cache WHERE created_at < ?",
                (cutoff,)
            )
            expired_count = (await cursor.fetchone())[0]
            
            return {
                "total_entries": total,
                "found": found_count,
                "not_found": total - found_count,
                "expired": expired_count,
                "ttl_days": self.ttl_days,
            }
            
        except Exception as e:
            logger.error("Błąd stats cache: %s", e)
            return {}
    
    async def close(self):
        """Zamknij połączenie z bazą."""
        if self._db:
            await self._db.close()
            logger.info("Cache closed")
