"""
Activity Scorer - oblicza score aktywności placówki na podstawie danych social.

Scoring:
- Google Maps rating >= 4.5: +15 pkt
- Google Maps > 50 recenzji: +10 pkt
- Facebook > 1k followers: +10 pkt
- Facebook post < 30 dni: +10 pkt
- Facebook reklamy aktywne: +15 pkt
- Instagram > 500 followers: +10 pkt
- Instagram post < 14 dni: +10 pkt
- LinkedIn profil istnieje: +5 pkt (TODO)
- TikTok profil istnieje: +5 pkt
- Strona WWW z SSL: +5 pkt
- Wiele filii (3+): +5 pkt

Klasyfikacja:
- 70-100: HOT_LEAD
- 40-69: LUKEWARM
- 0-39: COLD
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from ..config import CompanyIntelSettings, get_settings
from ..models import (
    ActivityScore,
    RecommendationLevel,
    SocialProfile,
    SocialPlatform,
    Placowka,
    CompanyIntel,
)


logger = logging.getLogger(__name__)


class ActivityScorer:
    """
    Oblicza Activity Score dla placówki.
    
    Score 0-100 na podstawie aktywności online.
    """
    
    def __init__(self, settings: Optional[CompanyIntelSettings] = None):
        self.settings = settings or get_settings()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def calculate(
        self,
        social_profiles: list[SocialProfile],
        placowki: list[Placowka],
        website_url: Optional[str] = None,
    ) -> ActivityScore:
        """
        Oblicza Activity Score.
        
        Args:
            social_profiles: Lista profili social media
            placowki: Lista placówek (dla Google Maps data)
            website_url: URL strony WWW
        
        Returns:
            ActivityScore z rozbiciem punktów
        """
        self.logger.info("Calculating activity score...")
        
        total = 0
        breakdown = {}
        signals = []
        
        # === GOOGLE MAPS ===
        google_score = 0
        best_rating = None
        total_reviews = 0
        
        for placowka in placowki:
            if placowka.google_rating:
                if best_rating is None or placowka.google_rating > best_rating:
                    best_rating = placowka.google_rating
            if placowka.google_reviews_count:
                total_reviews += placowka.google_reviews_count
        
        if best_rating and best_rating >= self.settings.score_google_maps_rating_threshold:
            google_score += 15
            signals.append(f"Google Maps {best_rating}/5")
        
        if total_reviews >= self.settings.score_google_maps_reviews_threshold:
            google_score += 10
            signals.append(f"Google {total_reviews} recenzji")
        
        breakdown["google_maps"] = google_score
        total += google_score
        
        # === FACEBOOK ===
        fb_score = 0
        fb_profile = self._get_profile(social_profiles, SocialPlatform.FACEBOOK)
        
        if fb_profile:
            if fb_profile.followers and fb_profile.followers >= self.settings.score_facebook_followers_threshold:
                fb_score += 10
                followers_str = self._format_followers(fb_profile.followers)
                signals.append(f"Facebook {followers_str} followers")
            
            if fb_profile.last_post_date:
                try:
                    # Handle timezone-aware vs naive datetime
                    now = datetime.utcnow()
                    last_post = fb_profile.last_post_date
                    if last_post.tzinfo is not None:
                        last_post = last_post.replace(tzinfo=None)
                    days_since = (now - last_post).days
                    if days_since <= 30:
                        fb_score += 10
                        signals.append(f"FB post < 30 dni")
                except Exception:
                    pass
            
            if fb_profile.is_ads_active:
                fb_score += 15
                signals.append("Reklamy FB aktywne")
        
        breakdown["facebook"] = fb_score
        total += fb_score
        
        # === INSTAGRAM ===
        ig_score = 0
        ig_profile = self._get_profile(social_profiles, SocialPlatform.INSTAGRAM)
        
        if ig_profile:
            if ig_profile.followers and ig_profile.followers >= self.settings.score_instagram_followers_threshold:
                ig_score += 10
                followers_str = self._format_followers(ig_profile.followers)
                signals.append(f"Instagram {followers_str} followers")
            
            if ig_profile.last_post_date:
                try:
                    # Handle timezone-aware vs naive datetime
                    now = datetime.utcnow()
                    last_post = ig_profile.last_post_date
                    if last_post.tzinfo is not None:
                        last_post = last_post.replace(tzinfo=None)
                    days_since = (now - last_post).days
                    if days_since <= 14:
                        ig_score += 10
                        signals.append("IG aktywny < 14 dni")
                except Exception:
                    pass
        
        breakdown["instagram"] = ig_score
        total += ig_score
        
        # === TIKTOK ===
        tt_score = 0
        tt_profile = self._get_profile(social_profiles, SocialPlatform.TIKTOK)
        
        if tt_profile and tt_profile.url:
            tt_score += 5
            if tt_profile.followers:
                followers_str = self._format_followers(tt_profile.followers)
                signals.append(f"TikTok {followers_str}")
            else:
                signals.append("TikTok obecny")
        
        breakdown["tiktok"] = tt_score
        total += tt_score
        
        # === WEBSITE ===
        web_score = 0
        if website_url:
            if website_url.startswith("https://"):
                web_score += 5
                signals.append("SSL aktywny")
        
        breakdown["website"] = web_score
        total += web_score
        
        # === SIEĆ PLACÓWEK ===
        if len(placowki) >= 3:
            breakdown["network"] = 5
            total += 5
            signals.append(f"Sieć {len(placowki)} placówek")
        
        # === KLASYFIKACJA ===
        if total >= 70:
            recommendation = RecommendationLevel.HOT_LEAD
        elif total >= 40:
            recommendation = RecommendationLevel.LUKEWARM
        else:
            recommendation = RecommendationLevel.COLD
        
        result = ActivityScore(
            total=min(total, 100),  # Cap at 100
            recommendation=recommendation,
            breakdown=breakdown,
            signals=signals,
        )
        
        self.logger.info(
            "Activity score: %d (%s) - %s",
            result.total,
            result.recommendation.value,
            ", ".join(signals[:5]),
        )
        
        return result
    
    def _get_profile(
        self,
        profiles: list[SocialProfile],
        platform: SocialPlatform,
    ) -> Optional[SocialProfile]:
        """Znajduje profil dla platformy."""
        for p in profiles:
            if p.platform == platform:
                return p
        return None
    
    def _format_followers(self, count: int) -> str:
        """Formatuje liczbę followers."""
        if count >= 1000000:
            return f"{count/1000000:.1f}M"
        elif count >= 1000:
            return f"{count/1000:.1f}K"
        else:
            return str(count)
