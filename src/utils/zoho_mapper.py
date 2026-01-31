"""
Mapper: NormalizedData -> pola Zoho CRM.

Konwertuje znormalizowane dane na format gotowy do CREATE/UPDATE w Zoho.
"""

from typing import Any, Optional

from ..models.lead_output import (
    GUSData,
    NormalizedData,
    ScrapedContactData,
)


def normalized_to_zoho_contact(
    data: NormalizedData,
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Mapuje NormalizedData na pola Zoho Contacts.

    Args:
        data: Znormalizowane dane osoby
        account_id: ID powiązanego Account (jeśli znany)

    Returns:
        Dict z polami gotowymi do CREATE w Zoho Contacts
    """
    result: dict[str, Any] = {}

    # Dane osobowe
    if data.first_name:
        result["First_Name"] = data.first_name
    if data.last_name:
        result["Last_Name"] = data.last_name
    if data.salutation:
        result["Salutation"] = data.salutation
    if data.title:
        result["Title"] = data.title

    # Kontakt
    if data.email:
        result["Email"] = data.email
    if data.phone_formatted:
        result["Phone"] = data.phone_formatted
    elif data.phone:
        result["Phone"] = data.phone
    if data.mobile:
        result["Mobile"] = data.mobile

    # Powiązanie z firmą
    if account_id:
        result["Account_Name"] = {"id": account_id}

    # Adres (opcjonalnie - jeśli kontakt ma własny adres)
    if data.street:
        result["Mailing_Street"] = data.street
    if data.city:
        result["Mailing_City"] = data.city
    if data.zip_code:
        result["Mailing_Zip"] = data.zip_code

    return result


def normalized_to_zoho_account(
    data: NormalizedData,
    gus_data: Optional[GUSData] = None,
    scraped_data: Optional[ScrapedContactData] = None,
    parent_account_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Mapuje NormalizedData na pola Zoho Accounts.

    Args:
        data: Znormalizowane dane firmy
        gus_data: Dane z GUS (autorytatywne)
        scraped_data: Dane zebrane podczas crawlowania
        parent_account_id: ID siedziby (jeśli to placówka)

    Returns:
        Dict z polami gotowymi do CREATE w Zoho Accounts
    """
    result: dict[str, Any] = {}

    # Nazwa firmy - preferuj GUS, potem normalized
    if gus_data and gus_data.found and gus_data.full_name:
        # GUS zwraca wielkimi literami - popraw
        result["Account_Name"] = gus_data.full_name.title()
    elif data.company_full_name:
        result["Account_Name"] = data.company_full_name
    elif data.company_name:
        result["Account_Name"] = data.company_name

    # NIP
    if data.nip:
        result["Firma_NIP"] = data.nip

    # REGON (z GUS)
    if gus_data and gus_data.found and gus_data.regon:
        result["REGON"] = gus_data.regon

    # Strona www i domena
    if scraped_data and scraped_data.domain:
        result["Domena_z_www"] = scraped_data.domain
        result["Website"] = f"https://{scraped_data.domain}"
    elif data.website:
        result["Website"] = data.website

    # Telefon firmowy (ze scrapingu)
    if scraped_data and scraped_data.phones:
        result["Phone"] = scraped_data.phones[0]

    # Powiązanie z siedzibą (jeśli to placówka)
    if parent_account_id:
        result["Parent_Account"] = {"id": parent_account_id}

    # Adres - dane z GUS są autorytatywne
    if gus_data and gus_data.found:
        billing_fields = gus_data.to_billing_fields()
        result.update(billing_fields)
    else:
        # Fallback na dane z leada
        if data.street:
            result["Billing_Street"] = data.street
        if data.city:
            result["Billing_City"] = data.city
        if data.zip_code:
            result["Billing_Code"] = data.zip_code

    return result


def scraped_to_zoho_contact_data(scraped: ScrapedContactData) -> ScrapedContactData:
    """
    Zwraca ScrapedContactData w formacie gotowym do zapisu.
    (Passthrough - dla kompatybilności API)
    """
    return scraped


def build_contact_create_data(
    data: NormalizedData,
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Buduje dane do CREATE Contact (OSOBA) w Zoho.

    UWAGA: scraped_data zawiera dane FIRMY (email kontaktowy, telefon z footera).
    Te dane NIE powinny trafiać do Contact - tylko do Account!
    Contact to osoba, nie firma.
    """
    return normalized_to_zoho_contact(data, account_id)


def build_account_create_data(
    data: NormalizedData,
    gus_data: Optional[GUSData] = None,
    scraped_data: Optional[ScrapedContactData] = None,
    parent_account_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Buduje pełne dane do CREATE Account w Zoho.
    Łączy dane znormalizowane, GUS i scraping.
    """
    return normalized_to_zoho_account(
        data=data,
        gus_data=gus_data,
        scraped_data=scraped_data,
        parent_account_id=parent_account_id,
    )
