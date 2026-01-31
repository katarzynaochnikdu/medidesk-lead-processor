"""
Instagram Scraper - pobieranie danych z profili Instagram przez Apify.

Zbiera:
- Followers
- Posty i engagement
- Bio i kontakty
"""

import asyncio
from typing import Optional
from datetime import datetime

from .base import BaseScraper, ScraperResult
from ..models import SocialProfile, SocialPlatform


class InstagramScraper(BaseScraper):
    """
    Instagram Profile Scraper używający Apify Actor.
    
    Actor: apify/instagram-profile-scraper
    Docs: https://apify.com/apify/instagram-profile-scraper
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
            self.logger.info("Apify client initialized for Instagram")
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
        instagram_url: str,
    ) -> ScraperResult:
        """
        Scrapuje profil Instagram.
        
        Args:
            instagram_url: URL profilu lub username (np. https://instagram.com/vitamedica lub vitamedica)
        
        Returns:
            ScraperResult z SocialProfile
        """
        self.logger.info("Scraping Instagram: %s", instagram_url)
        
        if not self._init_apify():
            return ScraperResult(
                success=False,
                error="Apify client not available",
            )
        
        # Normalizuj URL / username
        username = self._extract_username(instagram_url)
        full_url = f"https://www.instagram.com/{username}/"
        
        # Input dla Actora
        run_input = {
            "usernames": [username],
            "resultsLimit": 1,
        }
        
        self.logger.debug("Apify input: %s", run_input)
        
        try:
            # Uruchom Actor
            run = await asyncio.to_thread(
                lambda: self._apify_client.actor(
                    self.settings.apify_instagram_actor_id
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
                self.logger.warning("No Instagram data returned")
                return ScraperResult(
                    success=False,
                    error="No data returned - profile may be private",
                )
            
            # Parsuj pierwszy wynik
            item = items[0]
            profile = self._parse_profile(item, full_url)
            
            # Koszt (pay per event, bardzo tanie)
            cost = 0.01
            
            self.logger.info(
                "Instagram scraped: followers=%s, posts=%s, verified=%s",
                profile.followers,
                profile.posts_count,
                profile.is_verified,
            )
            
            return ScraperResult(
                success=True,
                data={"profile": profile, "raw": item},
                cost_usd=cost,
                raw_response=run,
            )
            
        except Exception as e:
            self.logger.exception("Instagram scraping failed: %s", e)
            return ScraperResult(
                success=False,
                error=str(e),
            )
    
    def _extract_username(self, url_or_username: str) -> str:
        """Wyciąga username z URL lub zwraca as-is."""
        import re
        
        # Jeśli to URL
        if "instagram.com" in url_or_username:
            # https://instagram.com/username/ -> username
            match = re.search(r"instagram\.com/([^/?]+)", url_or_username)
            if match:
                return match.group(1)
        
        # Usuń @ jeśli jest
        return url_or_username.lstrip("@")
    
    def _parse_profile(self, item: dict, url: str) -> SocialProfile:
        """Parsuje dane Instagram do SocialProfile."""
        
        # Followers
        followers = item.get("followersCount")
        if followers is None:
            # Alternatywne nazwy pól
            followers = item.get("followers") or item.get("follower_count")
        
        # Posts
        posts_count = item.get("postsCount")
        if posts_count is None:
            posts_count = item.get("posts") or item.get("mediaCount")
        
        # Engagement (jeśli dostępny)
        avg_engagement = None
        if followers and posts_count:
            # Można obliczyć z ostatnich postów
            latest_posts = item.get("latestPosts", [])
            if latest_posts:
                total_likes = sum(p.get("likesCount", 0) for p in latest_posts[:10])
                total_comments = sum(p.get("commentsCount", 0) for p in latest_posts[:10])
                post_count = min(len(latest_posts), 10)
                if post_count > 0 and followers > 0:
                    avg_engagement = ((total_likes + total_comments) / post_count) / followers * 100
        
        # Ostatni post
        last_post_date = None
        latest_posts = item.get("latestPosts", [])
        if latest_posts:
            first_post = latest_posts[0]
            timestamp = first_post.get("timestamp") or first_post.get("takenAt")
            if timestamp:
                try:
                    if isinstance(timestamp, str):
                        last_post_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    elif isinstance(timestamp, (int, float)):
                        last_post_date = datetime.fromtimestamp(timestamp)
                except Exception:
                    pass
        
        return SocialProfile(
            platform=SocialPlatform.INSTAGRAM,
            url=url,
            followers=followers,
            posts_count=posts_count,
            avg_engagement=round(avg_engagement, 2) if avg_engagement else None,
            last_post_date=last_post_date,
            is_verified=item.get("isVerified", False),
            is_ads_active=None,  # Instagram nie udostępnia tej informacji
            raw_data={
                "username": item.get("username"),
                "fullName": item.get("fullName"),
                "biography": item.get("biography"),
                "externalUrl": item.get("externalUrl"),
                "isBusinessAccount": item.get("isBusinessAccount"),
                "businessCategory": item.get("businessCategory"),
            },
        )
