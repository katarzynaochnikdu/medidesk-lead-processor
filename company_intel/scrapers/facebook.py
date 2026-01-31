"""
Facebook Scraper - pobieranie danych z Facebook Pages przez Apify.

Zbiera:
- Followers
- Posty i aktywność
- Status reklam
- Informacje kontaktowe
"""

import asyncio
from typing import Optional
from datetime import datetime

from .base import BaseScraper, ScraperResult
from ..models import SocialProfile, SocialPlatform


class FacebookScraper(BaseScraper):
    """
    Facebook Pages Scraper używający Apify Actor.
    
    Actor: apify/facebook-pages-scraper
    Docs: https://apify.com/apify/facebook-pages-scraper
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
            self.logger.info("Apify client initialized for Facebook")
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
        facebook_url: str,
    ) -> ScraperResult:
        """
        Scrapuje stronę Facebook.
        
        Args:
            facebook_url: URL strony Facebook (np. https://facebook.com/vitamedica)
        
        Returns:
            ScraperResult z SocialProfile
        """
        self.logger.info("Scraping Facebook: %s", facebook_url)
        
        if not self._init_apify():
            return ScraperResult(
                success=False,
                error="Apify client not available",
            )
        
        # Normalizuj URL
        if not facebook_url.startswith("http"):
            facebook_url = f"https://www.facebook.com/{facebook_url}"
        
        # Input dla Actora
        run_input = {
            "startUrls": [{"url": facebook_url}],
            "maxPosts": 0,  # Nie pobieraj postów (oszczędność)
            "maxPostComments": 0,
            "maxReviews": 0,
            "scrapeAbout": True,
            "scrapePosts": False,
            "scrapeReviews": False,
        }
        
        self.logger.debug("Apify input: %s", run_input)
        
        try:
            # Uruchom Actor
            run = await asyncio.to_thread(
                lambda: self._apify_client.actor(
                    self.settings.apify_facebook_actor_id
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
                self.logger.warning("No Facebook data returned")
                return ScraperResult(
                    success=False,
                    error="No data returned",
                )
            
            # Parsuj pierwszy wynik
            item = items[0]
            profile = self._parse_profile(item, facebook_url)
            
            # Koszt (pay per result)
            cost = 0.0066  # ~$6.60 per 1000
            
            self.logger.info(
                "Facebook scraped: followers=%s, ads=%s",
                profile.followers,
                profile.is_ads_active,
            )
            
            return ScraperResult(
                success=True,
                data={"profile": profile, "raw": item},
                cost_usd=cost,
                raw_response=run,
            )
            
        except Exception as e:
            self.logger.exception("Facebook scraping failed: %s", e)
            return ScraperResult(
                success=False,
                error=str(e),
            )
    
    def _parse_profile(self, item: dict, url: str) -> SocialProfile:
        """Parsuje dane Facebook do SocialProfile."""
        
        # Followers
        followers = None
        likes = item.get("likes")
        followers_count = item.get("followersCount") or item.get("followers")
        
        if followers_count:
            if isinstance(followers_count, str):
                # Parse "2.3K", "1.5M" etc.
                followers = self._parse_follower_count(followers_count)
            else:
                followers = int(followers_count)
        elif likes:
            followers = int(likes) if isinstance(likes, (int, float)) else None
        
        # Status reklam (jeśli dostępny)
        is_ads_active = item.get("isRunningAds")
        if is_ads_active is None:
            # Sprawdź w about
            about = item.get("about", {})
            if isinstance(about, dict):
                is_ads_active = about.get("isRunningAds")
        
        # Weryfikacja
        is_verified = item.get("isVerified", False)
        
        return SocialProfile(
            platform=SocialPlatform.FACEBOOK,
            url=url,
            followers=followers,
            posts_count=item.get("postsCount"),
            is_verified=is_verified,
            is_ads_active=is_ads_active,
            raw_data={
                "name": item.get("name"),
                "category": item.get("category"),
                "email": item.get("email"),
                "phone": item.get("phone"),
                "website": item.get("website"),
                "address": item.get("address"),
            },
        )
    
    def _parse_follower_count(self, text: str) -> Optional[int]:
        """Parsuje liczby typu '2.3K', '1.5M'."""
        import re
        
        text = text.strip().upper()
        
        match = re.match(r"([\d.,]+)\s*([KMB])?", text)
        if not match:
            return None
        
        number_str = match.group(1).replace(",", ".")
        multiplier_str = match.group(2)
        
        try:
            number = float(number_str)
        except ValueError:
            return None
        
        multipliers = {"K": 1000, "M": 1000000, "B": 1000000000}
        multiplier = multipliers.get(multiplier_str, 1)
        
        return int(number * multiplier)
