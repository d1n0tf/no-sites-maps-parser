from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CityOption:
    key: str
    label: str
    query_name: str
    two_gis_base_url: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CountryOption:
    key: str
    label: str
    cities: tuple[CityOption, ...]


@dataclass(frozen=True)
class VenueSnapshot:
    name: str
    address: str
    source_url: str
    has_website: bool


@dataclass(frozen=True)
class VenueRecord:
    name: str
    address: str
    country: str
    city: str
    provider: str
    search_query: str
    source_url: str
