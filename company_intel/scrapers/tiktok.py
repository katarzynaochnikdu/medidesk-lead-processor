"""
TikTok Scraper - pobieranie danych z profili TikTok przez Apify.

Zbiera:
- Followers
- Liczba filmów
- Hearts/likes
"""

import asyncio
from typing import Optional
from datetime import datetime

from .base import BaseScraper, ScraperResult
from ..models import SocialProfile, SocialPlatform


class TikTokScraper(BaseScraper):
    """
    TikTok Profile Scraper używający Apify Actor.
    
    Actor: clockworks/tiktok-scraper
    Docs: https://apify.com/clockworks/tiktok-scraper
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apify_client = None
        self._initialized = False
    
    def _init_apify(self) -> bool:
        """Lazy initialization Apify client."""
        if self._initialized:
            return self._apify_client is not None
        
        try:
            from apify_client import ApifyClient
            
            if not self.settings.has_apify_credentials:
                self.logger.warning("Brak Apify credentials - tryb offline")
                self._initialized = True
                return False
            
            self._apify_client = ApifyClient(self.settings.apify_api_token)
            self._initialized = True
            self.logger.info("Apify client initialized for TikTok")
            return True
            
        except ImportError:
            self.logger.error("Brak apify-client - zainstaluj: pip install apify-client")
            self._initialized = True
            return False
        except Exception as e:
            self.logger.error("Apify init error: %s", e)
            self._initialized = True
            return False
    
    async def _execute(
        self,
        tiktok_url: str,
    ) -> ScraperResult:
        """
        Scrapuje profil TikTok.
        
        Args:
            tiktok_url: URL profilu lub username (np. https://tiktok.com/@vitamedica lub vitamedica)
        
        Returns:
            ScraperResult z SocialProfile
        """
        self.logger.info("Scraping TikTok: %s", tiktok_url)
        
        if not self._init_apify():
            return ScraperResult(
                success=False,
                error="Apify client not available",
            )
        
        # Normalizuj URL
        username = self._extract_username(tiktok_url)
        full_url = f"https://www.tiktok.com/@{username}"
        
        # Input dla Actora
        run_input = {
            "profiles": [username],
            "resultsPerPage": 1,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
        }
        
        self.logger.debug("Apify input: %s", run_input)
        
        try:
            # Uruchom Actor
            run = await asyncio.to_thread(
                lambda: self._apify_client.actor(
                    self.settings.apify_tiktok_actor_id
                ).call(
                    run_input=run_input,
                    timeout_secs=self.settings.apify_actor_timeout_sec,
                )
            )
            
            if run.get("status") != "SUCCEEDED":
                self.logger.error("Actor failed: %s", run.get("status"))
                return ScraperResult(
                    success=False,
                    error=f"Actor failed: {run.get('status')}",
                    raw_response=run,
                )
            
            # Pobierz wyniki
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                return ScraperResult(
                    success=False,
                    error="No dataset ID",
                )
            
            items = await asyncio.to_thread(
                lambda: list(self._apify_client.dataset(dataset_id).iterate_items())
            )
            
            if not items:
                self.logger.warning("No TikTok data returned")
                return ScraperResult(
                    success=False,
                    error="No data returned - profile may not exist",
                )
            
            # Parsuj pierwszy wynik
            item = items[0]
            profile = self._parse_profile(item, full_url)
            
            # Koszt
            cost = 0.001  # ~$1 per 1000
            
            self.logger.info(
                "TikTok scraped: followers=%s, videos=%s",
                profile.followers,
                profile.posts_count,
            )
            
            return ScraperResult(
                success=True,
                data={"profile": profile, "raw": item},
                cost_usd=cost,
                raw_response=run,
            )
            
        except Exception as e:
            self.logger.exception("TikTok scraping failed: %s", e)
            return ScraperResult(
                success=False,
                error=str(e),
            )
    
    def _extract_username(self, url_or_username: str) -> str:
        """Wyciąga username z URL lub zwraca as-is."""
        import re
        
        # Jeśli to URL
        if "tiktok.com" in url_or_username:
            # https://tiktok.com/@username -> username
            match = re.search(r"tiktok\.com/@([^/?]+)", url_or_username)
            if match:
                return match.group(1)
        
        # Usuń @ jeśli jest
        return url_or_username.lstrip("@")
    
    def _parse_profile(self, item: dict, url: str) -> SocialProfile:
        """Parsuje dane TikTok do SocialProfile."""
        
        # Dane mogą być w różnych strukturach
        author_meta = item.get("authorMeta", {})
        
        # Followers
        followers = (
            author_meta.get("fans") or
            author_meta.get("followers") or
            item.get("fans") or
            item.get("followers")
        )
        
        # Videos count
        videos = (
            author_meta.get("video") or
            author_meta.get("videoCount") or
            item.get("videoCount")
        )
        
        # Hearts/likes
        hearts = (
            author_meta.get("heart") or
            author_meta.get("hearts") or
            item.get("hearts")
        )
        
        # Verified
        is_verified = (
            author_meta.get("verified") or
            item.get("verified", False)
        )
        
        return SocialProfile(
            platform=SocialPlatform.TIKTOK,
            url=url,
            followers=followers,
            posts_count=videos,
            is_verified=is_verified,
            is_ads_active=None,
            raw_data={
                "username": author_meta.get("name") or item.get("username"),
                "nickname": author_meta.get("nickName") or item.get("nickname"),
                "signature": author_meta.get("signature") or item.get("bio"),
                "hearts": hearts,
                "following": author_meta.get("following") or item.get("following"),
            },
        )
