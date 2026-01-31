"""
QueryBuilder - deterministyczny builder zapytań dla wyszukiwania NIP.

Buduje warianty zapytań w kolejności od najbardziej identyfikujących
do najbardziej ogólnych:
1. name + street + city + "nip"
2. name + city + "nip"
3. name + "nip"
4. name + city + keywords + "nip"
"""

import logging
from dataclasses import dataclass
from typing import Optional

from .models import ChaoticLeadParsed

logger = logging.getLogger(__name__)


@dataclass
class SearchQuery:
    """Pojedyncze zapytanie do wyszukiwarki."""
    query: str
    priority: int  # 1 = najwyższy priorytet
    strategy: str  # Opis strategii (do logów)
    elements_used: list[str]  # Jakie elementy użyto


class QueryBuilder:
    """
    Buduje warianty zapytań w konsekwentnej kolejności.
    
    Zasada: od najbardziej identyfikujących do najbardziej ogólnych.
    """
    
    def __init__(self, max_queries: int = 5):
        """
        Args:
            max_queries: Maksymalna liczba wariantów zapytań
        """
        self.max_queries = max_queries
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def build_nip_search_queries(
        self,
        parsed: ChaoticLeadParsed,
        gus_name: Optional[str] = None,
        gus_city: Optional[str] = None,
    ) -> list[SearchQuery]:
        """
        Buduje listę zapytań do wyszukiwania NIP.
        
        Gradacja (od najbardziej identyfikujących):
        1. name + street + city + "nip" (jeśli mamy ulicę)
        2. name + city + "nip" (jeśli mamy miasto)
        3. short_name + city + "nip" (krótka nazwa może być lepsza)
        4. name + "nip" (tylko nazwa)
        5. name + city + keywords + "nip" (z branżą jako doprecyzowanie)
        
        Args:
            parsed: Sparsowane dane wejściowe
            gus_name: Nazwa z GUS (jeśli dostępna)
            gus_city: Miasto z GUS (jeśli dostępne)
        
        Returns:
            Lista SearchQuery posortowana wg priorytetu
        """
        queries = []
        priority = 1
        
        # Użyj nazwy z inputu lub z GUS
        name = parsed.name or parsed.short_name
        short_name = parsed.short_name
        city = parsed.city or gus_city
        street = parsed.street
        keywords = parsed.keywords
        
        # Jeśli mamy GUS, użyj też tej nazwy
        if gus_name and gus_name != name:
            # Dodaj zapytanie z nazwą z GUS
            if city:
                queries.append(SearchQuery(
                    query=f'"{gus_name}" "{city}" nip',
                    priority=priority,
                    strategy="gus_name + city + nip",
                    elements_used=["gus_name", "city"],
                ))
                priority += 1
        
        # 1. name + street + city + "nip" (najsilniejsze)
        if name and street and city:
            queries.append(SearchQuery(
                query=f'"{name}" "{street}" "{city}" nip',
                priority=priority,
                strategy="name + street + city + nip",
                elements_used=["name", "street", "city"],
            ))
            priority += 1
        
        # 2. name + city + "nip"
        if name and city:
            queries.append(SearchQuery(
                query=f'"{name}" "{city}" nip',
                priority=priority,
                strategy="name + city + nip",
                elements_used=["name", "city"],
            ))
            priority += 1
        
        # 3. short_name + city + "nip" (krótka nazwa może być lepsza dla marketingowych nazw)
        if short_name and city and short_name != name:
            queries.append(SearchQuery(
                query=f'"{short_name}" "{city}" nip',
                priority=priority,
                strategy="short_name + city + nip",
                elements_used=["short_name", "city"],
            ))
            priority += 1
        
        # 4. name + "nip" (tylko nazwa)
        if name:
            queries.append(SearchQuery(
                query=f'"{name}" nip',
                priority=priority,
                strategy="name + nip",
                elements_used=["name"],
            ))
            priority += 1
        
        # 5. short_name + "nip" (krótka nazwa)
        if short_name and short_name != name:
            queries.append(SearchQuery(
                query=f'"{short_name}" nip',
                priority=priority,
                strategy="short_name + nip",
                elements_used=["short_name"],
            ))
            priority += 1
        
        # 6. name + city + keywords + "nip" (z branżą jako doprecyzowanie)
        if name and city and keywords:
            keyword_str = " ".join(keywords[:2])  # Max 2 słowa kluczowe
            queries.append(SearchQuery(
                query=f'"{name}" "{city}" {keyword_str} nip',
                priority=priority,
                strategy="name + city + keywords + nip",
                elements_used=["name", "city", "keywords"],
            ))
            priority += 1
        
        # Ogranicz do max_queries
        queries = queries[:self.max_queries]
        
        self.logger.info(
            "[QUERY_BUILDER] Built %d queries for '%s' (city=%s, street=%s)",
            len(queries),
            name or short_name or "?",
            city or "?",
            street[:20] if street else "?",
        )
        
        for q in queries:
            self.logger.debug(
                "  [%d] %s: %s",
                q.priority,
                q.strategy,
                q.query[:60],
            )
        
        return queries
    
    def build_website_search_queries(
        self,
        parsed: ChaoticLeadParsed,
        gus_name: Optional[str] = None,
        gus_city: Optional[str] = None,
    ) -> list[SearchQuery]:
        """
        Buduje listę zapytań do wyszukiwania strony WWW.
        
        Używane gdy mamy NIP ale nie mamy strony WWW.
        
        Gradacja:
        1. name_input + city_gus + "strona"
        2. name_input + city_gus
        3. name_gus + city_gus
        4. short_name + city
        
        Args:
            parsed: Sparsowane dane wejściowe
            gus_name: Nazwa z GUS
            gus_city: Miasto z GUS
        
        Returns:
            Lista SearchQuery posortowana wg priorytetu
        """
        queries = []
        priority = 1
        
        name = parsed.name or parsed.short_name
        short_name = parsed.short_name
        city = parsed.city or gus_city
        
        # 1. name_input + city_gus + "strona"
        if name and city:
            queries.append(SearchQuery(
                query=f'"{name}" "{city}" strona internetowa',
                priority=priority,
                strategy="name + city + strona",
                elements_used=["name", "city"],
            ))
            priority += 1
        
        # 2. name_input + city_gus
        if name and city:
            queries.append(SearchQuery(
                query=f'"{name}" "{city}"',
                priority=priority,
                strategy="name + city",
                elements_used=["name", "city"],
            ))
            priority += 1
        
        # 3. name_gus + city_gus (jeśli inna niż input)
        if gus_name and city and gus_name != name:
            queries.append(SearchQuery(
                query=f'"{gus_name}" "{city}"',
                priority=priority,
                strategy="gus_name + city",
                elements_used=["gus_name", "city"],
            ))
            priority += 1
        
        # 4. short_name + city
        if short_name and city and short_name != name:
            queries.append(SearchQuery(
                query=f'"{short_name}" "{city}"',
                priority=priority,
                strategy="short_name + city",
                elements_used=["short_name", "city"],
            ))
            priority += 1
        
        # 5. name only
        if name:
            queries.append(SearchQuery(
                query=f'"{name}"',
                priority=priority,
                strategy="name_only",
                elements_used=["name"],
            ))
            priority += 1
        
        queries = queries[:self.max_queries]
        
        self.logger.info(
            "[QUERY_BUILDER] Built %d website queries for '%s'",
            len(queries),
            name or short_name or "?",
        )
        
        return queries
    
    def build_zoho_search_keys(
        self,
        parsed: ChaoticLeadParsed,
    ) -> dict:
        """
        Buduje klucze do wyszukiwania w Zoho.
        
        Returns:
            Dict z kluczami: phone, email, domain, name, city
        """
        keys = {
            "phone": None,
            "email": None,
            "domain": None,
            "name": None,
            "city": None,
        }
        
        if parsed.phone:
            # Normalizuj telefon - tylko 9 cyfr
            import re
            digits = re.sub(r'\D', '', parsed.phone)
            keys["phone"] = digits[-9:] if len(digits) >= 9 else None
        
        if parsed.email:
            keys["email"] = parsed.email.lower()
            # Wyciągnij domenę
            if "@" in parsed.email:
                keys["domain"] = parsed.email.split("@")[1].lower()
        
        if parsed.website:
            # Normalizuj domenę
            domain = parsed.website.lower()
            domain = domain.replace("https://", "").replace("http://", "")
            domain = domain.replace("www.", "")
            domain = domain.split("/")[0]
            keys["domain"] = domain
        
        if parsed.name:
            keys["name"] = parsed.name
        
        if parsed.city:
            keys["city"] = parsed.city
        
        self.logger.info(
            "[QUERY_BUILDER] Zoho keys: phone=%s, email=%s, domain=%s",
            keys["phone"][:4] + "..." if keys["phone"] else None,
            keys["email"][:10] + "..." if keys["email"] else None,
            keys["domain"],
        )
        
        return keys
