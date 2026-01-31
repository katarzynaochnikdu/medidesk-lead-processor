"""
Modele danych dla Company Intelligence Tool.

Struktura JSON odpowiadająca polom Zoho CRM.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


# === ENUMS ===

class PlatnikUslug(str, Enum):
    """Płatnik usług medycznych."""
    NFZ = "NFZ"
    KOMERCYJNE = "Komercyjne"
    UBEZPIECZENIE = "Ubezpieczenie"
    NONE = "none"


class Specjalizacja(str, Enum):
    """Typ specjalizacji placówki."""
    POZ = "POZ"
    PRZYCHODNIA_WIELOSPECJALISTYCZNA = "Przychodnia Wielospecjalistyczna"
    SZPITAL = "Szpital"
    PORADNIA_ZDROWIA_PSYCHICZNEGO = "Poradnia Zdrowia Psychicznego"
    REHABILITACJA = "Rehabilitacja"
    STOMATOLOGIA = "Stomatologia"
    DIAGNOSTYKA = "Diagnostyka"
    MEDYCYNA_ESTETYCZNA = "Medycyna Estetyczna"
    DIAGNOSTYKA_OBRAZOWA = "Diagnostyka Obrazowa"
    LABORATORIUM = "Laboratorium"
    WETERYNARIA = "Weterynaria"
    USLUGI_NIEMEDYCZNE = "Usługi Niemedyczne"
    NONE = "none"


class Wielospecjalistyczne(str, Enum):
    """Specjalizacje lekarskie."""
    CHIRURGIA_OGOLNA = "chirurgia ogólna"
    CHIRURGIA_PLASTYCZNA = "chirurgia plastyczna"
    GASTROENTEROLOGIA = "gastroenterologia"
    GINEKOLOGIA = "ginekologia/położnictwo/leczenie niepłodności"
    KARDIOLOGIA = "kardiologia"
    LARYNGOLOGIA = "laryngologia"
    OKULISTYKA = "okulistyka"
    ORTOPEDIA = "ortopedia"


class TypWlasnosci(str, Enum):
    """Typ własności placówki."""
    NONE = "-None-"
    PRYWATNY = "Prywatny (Private)"
    PARTNERSTWO = "Partnerstwo PP (Partnership)"
    PUBLICZNY = "Publiczny (Public)"


class KategoriaKonta(str, Enum):
    """Kategoria konta w CRM."""
    NONE = "-None-"
    PODMIOT_LECZNICZY = "Podmiot leczniczy (Inne)"
    PARTNER = "Partner"
    KONKURENCJA = "Konkurencja"
    PODDOSTAWCA = "Poddostawca"
    POZOSTALE = "Pozostałe"


class TypAdresu(str, Enum):
    """Typ adresu placówki."""
    NONE = "-None-"
    SIEDZIBA = "Siedziba (Lokalizacja rejestracyjna)"
    SIEDZIBA_I_FILIA = "Siedziba i Filia (Lokalizacja placówki i rejestracyjna)"
    FILIA = "Filia (Lokalizacja rejestrowa)"


class RecommendationLevel(str, Enum):
    """Poziom rekomendacji leada."""
    HOT_LEAD = "HOT_LEAD"
    LUKEWARM = "LUKEWARM"
    COLD = "COLD"


class SocialPlatform(str, Enum):
    """Platformy social media."""
    WEBSITE = "website"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    LINKEDIN = "linkedin"
    TIKTOK = "tiktok"
    X = "x"
    GOOGLE_MAPS = "google_maps"


# === MODELE DANYCH ===

class Kontakt(BaseModel):
    """Pojedynczy kontakt (telefon/email)."""
    typ: str = Field(..., description="Typ kontaktu: 'telefon' lub 'email'")
    wartosc: str = Field(..., description="Wartość kontaktu")
    opis: Optional[str] = Field(None, description="Opis kontaktu, np. 'Rejestracja'")
    
    def to_dict(self) -> dict:
        return {"typ": self.typ, "wartosc": self.wartosc, "opis": self.opis}


class Adres(BaseModel):
    """Adres placówki."""
    ulica: Optional[str] = Field(None, description="Ulica z numerem")
    kod: Optional[str] = Field(None, description="Kod pocztowy")
    miasto: Optional[str] = Field(None, description="Miasto")
    wojewodztwo: Optional[str] = Field(None, description="Województwo")
    
    # Prefiksy które NIE są ulicami
    _NON_STREET_PREFIXES = (
        "al.", "al ", "aleja", "alei",
        "pl.", "pl ", "plac", "placu",
        "os.", "os ", "osiedle", "osiedla",
        "rondo", "ronda",
        "park", "parku",
        "skwer", "skweru",
        "bulwar", "bulwaru",
        "pasaż", "pasażu",
        "szosa", "szosy",
        "droga", "drogi",
        "most", "mostu",
        "wyspa", "wyspy",
        "wybrzeże", "wybrzeża",
        "trakt", "traktu",
        "gen.", "gen ",  # Aleja Gen. Sikorskiego
        "ks.", "ks ",  # Księdza
        "św.", "św ",  # Świętego
        "zgrupowania",  # Zgrupowania AK
    )
    
    def _format_ulica(self) -> Optional[str]:
        """Formatuje ulicę z prefiksem 'ul.' jeśli to ulica."""
        if not self.ulica:
            return None
        
        ulica_lower = self.ulica.lower().strip()
        
        # Jeśli już ma prefiks "ul." - nie dodawaj
        if ulica_lower.startswith("ul.") or ulica_lower.startswith("ul "):
            return self.ulica
        
        # Jeśli to nie jest ulica (aleja, plac, etc.) - nie dodawaj
        for prefix in self._NON_STREET_PREFIXES:
            if ulica_lower.startswith(prefix):
                return self.ulica
        
        # To jest ulica - dodaj "ul."
        return f"ul. {self.ulica}"
    
    def to_dict(self) -> dict:
        return {
            "ulica": self._format_ulica(),
            "kod": self.kod,
            "miasto": self.miasto,
            "wojewodztwo": self.wojewodztwo,
        }
    
    def __str__(self) -> str:
        parts = [p for p in [self.ulica, self.kod, self.miasto] if p]
        return ", ".join(parts) if parts else ""


class Coordinates(BaseModel):
    """Współrzędne GPS (WGS84)."""
    lat: float = Field(..., description="Latitude (szerokość geograficzna)")
    lng: float = Field(..., description="Longitude (długość geograficzna)")
    
    def to_dict(self) -> dict:
        return {"lat": self.lat, "lng": self.lng}


class ReviewCitation(BaseModel):
    """Pojedynczy cytat z recenzji jako dowód."""
    text: str = Field(..., description="Fragment recenzji (cytat)")
    date: Optional[str] = Field(None, description="Data recenzji (ISO lub 'X dni temu')")
    author: Optional[str] = Field(None, description="Autor recenzji")
    rating: Optional[int] = Field(None, description="Ocena w gwiazdkach (1-5)")
    review_url: Optional[str] = Field(None, description="Link do recenzji")
    
    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "date": self.date,
            "author": self.author,
            "rating": self.rating,
            "review_url": self.review_url,
        }


class InsightWithCitations(BaseModel):
    """Skarga lub pochwała z cytatami jako dowodami."""
    insight: str = Field(..., description="Treść skargi/pochwały")
    count: int = Field(1, description="Liczba recenzji wspierających tę skargę/pochwałę")
    citations: list[ReviewCitation] = Field(default_factory=list, description="Cytaty z recenzji (max 3)")
    
    def to_dict(self) -> dict:
        return {
            "insight": self.insight,
            "count": self.count,
            "citations": [c.to_dict() for c in self.citations],
        }


class ReviewsInsights(BaseModel):
    """Insights z analizy recenzji Google Maps."""
    total_reviews_analyzed: int = Field(0, description="Liczba przeanalizowanych recenzji")
    avg_rating: Optional[float] = Field(None, description="Średnia ocena")
    
    # Top 3-5 najczęstszych tematów Z CYTATAMI
    top_complaints: list[InsightWithCitations] = Field(default_factory=list, description="Najczęstsze skargi z cytatami")
    top_praises: list[InsightWithCitations] = Field(default_factory=list, description="Najczęstsze pochwały z cytatami")
    
    # Główne tematy
    common_themes: list[str] = Field(default_factory=list, description="Główne tematy (obsługa, czystość, ceny, etc.)")
    
    # Podsumowanie AI
    summary: Optional[str] = Field(None, description="Krótkie podsumowanie (2-3 zdania)")
    
    # Confidence oparte na liczbie recenzji
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Pewność analizy (0-1)")
    
    def to_dict(self) -> dict:
        return {
            "total_reviews_analyzed": self.total_reviews_analyzed,
            "avg_rating": self.avg_rating,
            "top_complaints": [c.to_dict() for c in self.top_complaints],
            "top_praises": [p.to_dict() for p in self.top_praises],
            "common_themes": self.common_themes,
            "summary": self.summary,
            "confidence": self.confidence,
        }


class Placowka(BaseModel):
    """Pojedyncza placówka/filia."""
    typ_adresu: TypAdresu = Field(TypAdresu.NONE, description="Typ adresu")
    adres: Adres = Field(default_factory=Adres, description="Adres placówki")
    kontakty: list[Kontakt] = Field(default_factory=list, description="Lista kontaktów")
    godziny_otwarcia: Optional[str] = Field(None, description="Godziny otwarcia")
    coordinates: Optional[Coordinates] = Field(None, description="Współrzędne GPS (WGS84)")
    google_maps_place_id: Optional[str] = Field(None, description="Google Maps Place ID")
    google_rating: Optional[float] = Field(None, description="Ocena Google Maps")
    google_reviews_count: Optional[int] = Field(None, description="Liczba recenzji Google")
    reviews_insights: Optional[ReviewsInsights] = Field(None, description="Insights z recenzji")
    
    def to_dict(self) -> dict:
        return {
            "typ_adresu": self.typ_adresu.value if self.typ_adresu else None,
            "adres": self.adres.to_dict(),
            "kontakty": [k.to_dict() for k in self.kontakty],
            "godziny_otwarcia": self.godziny_otwarcia,
            "coordinates": self.coordinates.to_dict() if self.coordinates else None,
            "google_maps_place_id": self.google_maps_place_id,
            "google_rating": self.google_rating,
            "google_reviews_count": self.google_reviews_count,
            "reviews_insights": self.reviews_insights.to_dict() if self.reviews_insights else None,
        }


class SocialProfile(BaseModel):
    """Profil social media."""
    platform: SocialPlatform = Field(..., description="Platforma")
    url: Optional[str] = Field(None, description="URL profilu")
    followers: Optional[int] = Field(None, description="Liczba obserwujących")
    posts_count: Optional[int] = Field(None, description="Liczba postów")
    avg_engagement: Optional[float] = Field(None, description="Średnie zaangażowanie")
    last_post_date: Optional[datetime] = Field(None, description="Data ostatniego posta")
    is_verified: bool = Field(False, description="Czy profil zweryfikowany")
    is_ads_active: Optional[bool] = Field(None, description="Czy reklamy aktywne (FB)")
    raw_data: dict = Field(default_factory=dict, description="Surowe dane z API")
    
    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "url": self.url,
            "followers": self.followers,
            "posts_count": self.posts_count,
            "avg_engagement": self.avg_engagement,
            "last_post_date": self.last_post_date.isoformat() if self.last_post_date else None,
            "is_verified": self.is_verified,
            "is_ads_active": self.is_ads_active,
        }


class ActivityScore(BaseModel):
    """Wynik oceny aktywności placówki."""
    total: int = Field(0, ge=0, le=100, description="Łączny wynik 0-100")
    recommendation: RecommendationLevel = Field(
        RecommendationLevel.COLD, 
        description="Klasyfikacja leada"
    )
    breakdown: dict[str, int] = Field(
        default_factory=dict, 
        description="Rozbicie punktów per platforma"
    )
    signals: list[str] = Field(
        default_factory=list, 
        description="Lista sygnałów aktywności"
    )
    
    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "recommendation": self.recommendation.value,
            "breakdown": self.breakdown,
            "signals": self.signals,
        }


class KategoryzacjaAI(BaseModel):
    """Wynik kategoryzacji AI."""
    platnik_uslug: list[str] = Field(default_factory=list, description="Płatnicy usług")
    specjalizacja: list[str] = Field(default_factory=list, description="Specjalizacje")
    wielospecjalistyczne: list[str] = Field(default_factory=list, description="Specjalizacje lekarskie")
    typ_wlasnosci: Optional[str] = Field(None, description="Typ własności")
    kategoria_konta: Optional[str] = Field(None, description="Kategoria konta")
    branza: Optional[str] = Field(None, description="Branża (jeśli nie podmiot leczniczy)")
    ai_confidence: float = Field(0.0, ge=0.0, le=1.0, description="Pewność AI")
    ai_reasoning: Optional[str] = Field(None, description="Uzasadnienie AI")
    
    def to_dict(self) -> dict:
        return {
            "platnik_uslug": self.platnik_uslug,
            "specjalizacja": self.specjalizacja,
            "wielospecjalistyczne": self.wielospecjalistyczne,
            "typ_wlasnosci": self.typ_wlasnosci,
            "kategoria_konta": self.kategoria_konta,
            "branza": self.branza,
            "ai_confidence": self.ai_confidence,
            "ai_reasoning": self.ai_reasoning,
        }


class SocialMediaLinks(BaseModel):
    """Linki do social media."""
    website: Optional[str] = Field(None, description="Strona WWW")
    facebook: Optional[str] = Field(None, description="Facebook")
    instagram: Optional[str] = Field(None, description="Instagram")
    linkedin: Optional[str] = Field(None, description="LinkedIn")
    tiktok: Optional[str] = Field(None, description="TikTok")
    x: Optional[str] = Field(None, description="X/Twitter")
    
    def to_dict(self) -> dict:
        return {
            "website": self.website,
            "facebook": self.facebook,
            "instagram": self.instagram,
            "linkedin": self.linkedin,
            "tiktok": self.tiktok,
            "x": self.x,
        }
    
    def has_any(self) -> bool:
        """Sprawdza czy jest jakikolwiek link."""
        return any([
            self.website, self.facebook, self.instagram, 
            self.linkedin, self.tiktok, self.x
        ])


class DataValidation(BaseModel):
    """Wyniki cross-validation danych między źródłami."""
    contacts_match: bool = Field(True, description="Czy kontakty z WWW i Google Maps się zgadzają")
    contacts_discrepancies: list[str] = Field(default_factory=list, description="Lista niespójności w kontaktach")
    address_match: bool = Field(True, description="Czy adresy się zgadzają")
    address_discrepancies: list[str] = Field(default_factory=list, description="Lista niespójności w adresach")
    
    def to_dict(self) -> dict:
        return {
            "contacts_match": self.contacts_match,
            "contacts_discrepancies": self.contacts_discrepancies,
            "address_match": self.address_match,
            "address_discrepancies": self.address_discrepancies,
        }


class Metadata(BaseModel):
    """Metadane przetwarzania."""
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    sources_used: list[str] = Field(default_factory=list, description="Użyte źródła")
    processing_time_ms: int = Field(0, description="Czas przetwarzania w ms")
    cost_usd: float = Field(0.0, description="Koszt w USD")
    errors: list[str] = Field(default_factory=list, description="Błędy")
    warnings: list[str] = Field(default_factory=list, description="Ostrzeżenia")
    data_validation: Optional[DataValidation] = Field(None, description="Wyniki cross-validation")
    
    def to_dict(self) -> dict:
        return {
            "scraped_at": self.scraped_at.isoformat(),
            "sources_used": self.sources_used,
            "processing_time_ms": self.processing_time_ms,
            "cost_usd": self.cost_usd,
            "errors": self.errors,
            "warnings": self.warnings,
            "data_validation": self.data_validation.to_dict() if self.data_validation else None,
        }


class CompanyIntel(BaseModel):
    """Główny model danych firmy - pełny output."""
    
    # Identyfikacja i dane rejestrowe
    nip: Optional[str] = Field(None, description="NIP firmy")
    regon: Optional[str] = Field(None, description="REGON firmy")
    krs: Optional[str] = Field(None, description="Numer KRS (jeśli dotyczy)")
    nazwa_pelna: Optional[str] = Field(None, description="Pełna nazwa z rejestru")
    nazwa_zwyczajowa: Optional[str] = Field(None, description="Nazwa zwyczajowa/skrócona")
    
    # Adres siedziby z rejestru
    adres_siedziby: Optional[Adres] = Field(None, description="Adres siedziby z GUS/KRS")
    
    # Kategoryzacja AI
    kategoryzacja_ai: KategoryzacjaAI = Field(
        default_factory=KategoryzacjaAI,
        description="Wynik kategoryzacji AI"
    )
    
    # Social media
    social_media: SocialMediaLinks = Field(
        default_factory=SocialMediaLinks,
        description="Linki do social media"
    )
    social_profiles: list[SocialProfile] = Field(
        default_factory=list,
        description="Szczegółowe dane z profili social"
    )
    
    # Activity Score
    activity_score: ActivityScore = Field(
        default_factory=ActivityScore,
        description="Wynik oceny aktywności"
    )
    
    # Placówki (siedziba + filie)
    placowki: list[Placowka] = Field(
        default_factory=list,
        description="Lista placówek (siedziba + filie)"
    )
    
    # Metadane
    metadata: Metadata = Field(
        default_factory=Metadata,
        description="Metadane przetwarzania"
    )
    
    def to_dict(self) -> dict:
        """Konwertuje do dict (JSON-serializable)."""
        return {
            "company": {
                # Dane rejestrowe
                "nip": self.nip,
                "regon": self.regon,
                "krs": self.krs,
                "nazwa_pelna": self.nazwa_pelna,
                "nazwa_zwyczajowa": self.nazwa_zwyczajowa,
                "adres_siedziby": self.adres_siedziby.to_dict() if self.adres_siedziby else None,
                # Kategoryzacja i social
                "kategoryzacja_ai": self.kategoryzacja_ai.to_dict(),
            "social_media": self.social_media.to_dict(),
            "social_profiles": [p.to_dict() for p in self.social_profiles],
            "activity_score": self.activity_score.to_dict(),
                "placowki": [p.to_dict() for p in self.placowki],
                "metadata": self.metadata.to_dict(),
            }
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Konwertuje do JSON string."""
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    def save_json(self, path: str) -> None:
        """Zapisuje do pliku JSON."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())


# === INPUT MODELS ===

class CompanyIntelRequest(BaseModel):
    """Request do analizy firmy."""
    company_name: Optional[str] = Field(None, description="Nazwa firmy")
    nip: Optional[str] = Field(None, description="NIP firmy")
    city: Optional[str] = Field(None, description="Miasto")
    website: Optional[str] = Field(None, description="Strona WWW (jeśli znana)")
    social_links: Optional[SocialMediaLinks] = Field(None, description="Znane linki social")
    
    def to_dict(self) -> dict:
        return {
            "company_name": self.company_name,
            "nip": self.nip,
            "city": self.city,
            "website": self.website,
            "social_links": self.social_links.to_dict() if self.social_links else None,
        }
