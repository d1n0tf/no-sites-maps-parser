from __future__ import annotations

import re

from .models import CityOption, CountryOption

DEFAULT_SEARCH_TERMS: tuple[str, ...] = (
    "кафе",
    "ресторан",
    "кофейня",
    "бар",
    "пиццерия",
    "пекарня",
    "бургерная",
    "суши",
    "столовая",
    "фастфуд",
)

SEARCH_MODE_LABEL = "Все заведения общепита"

COUNTRIES: tuple[CountryOption, ...] = (
    CountryOption(
        key="russia",
        label="Россия",
        cities=(
            CityOption(
                "moscow",
                "Москва",
                "Москва",
                "https://2gis.ru/moscow",
                aliases=("мск", "msk", "moskva"),
            ),
            CityOption(
                "saint-petersburg",
                "Санкт-Петербург",
                "Санкт-Петербург",
                "https://2gis.ru/spb",
                aliases=("питер", "спб", "spb", "санкт петербург", "saint petersburg"),
            ),
            CityOption("kazan", "Казань", "Казань", "https://2gis.ru/kazan"),
            CityOption(
                "ekaterinburg",
                "Екатеринбург",
                "Екатеринбург",
                "https://2gis.ru/ekaterinburg",
                aliases=("екб", "ekb"),
            ),
            CityOption(
                "novosibirsk",
                "Новосибирск",
                "Новосибирск",
                "https://2gis.ru/novosibirsk",
                aliases=("нск", "nsk"),
            ),
        ),
    ),
    CountryOption(
        key="kazakhstan",
        label="Казахстан",
        cities=(
            CityOption("astana", "Астана", "Астана", "https://2gis.kz/astana"),
            CityOption("almaty", "Алматы", "Алматы", "https://2gis.kz/almaty"),
            CityOption("shymkent", "Шымкент", "Шымкент", "https://2gis.kz/shymkent"),
            CityOption(
                "karaganda",
                "Караганда",
                "Караганда",
                "https://2gis.kz/karaganda",
            ),
            CityOption("atyrau", "Атырау", "Атырау", "https://2gis.kz/atyrau"),
        ),
    ),
    CountryOption(
        key="belarus",
        label="Беларусь",
        cities=(
            CityOption("minsk", "Минск", "Минск", "https://2gis.by/minsk"),
        ),
    ),
    CountryOption(
        key="kyrgyzstan",
        label="Кыргызстан",
        cities=(
            CityOption("bishkek", "Бишкек", "Бишкек", "https://2gis.kg/bishkek"),
            CityOption("osh", "Ош", "Ош", "https://2gis.kg/osh"),
            CityOption("karakol", "Каракол", "Каракол", "https://2gis.kg/karakol"),
            CityOption("tokmok", "Токмок", "Токмок", "https://2gis.kg/tokmok"),
        ),
    ),
    CountryOption(
        key="uzbekistan",
        label="Узбекистан",
        cities=(
            CityOption("tashkent", "Ташкент", "Ташкент", "https://2gis.uz/tashkent"),
            CityOption(
                "samarkand",
                "Самарканд",
                "Самарканд",
                "https://2gis.uz/samarkand",
            ),
            CityOption("bukhara", "Бухара", "Бухара", "https://2gis.uz/bukhara"),
        ),
    ),
)

PROVIDER_LABELS: dict[str, str] = {
    "all": "Все источники",
    "google": "Google Maps",
    "yandex": "Яндекс.Карты",
    "2gis": "2ГИС",
}

TRANSLIT_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def normalize_lookup(value: str) -> str:
    return value.strip().casefold().replace("ё", "е")


def slugify_lookup(value: str) -> str:
    transliterated = "".join(TRANSLIT_MAP.get(char, char) for char in normalize_lookup(value))
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    return slug or "location"


def resolve_country(raw_value: str) -> CountryOption:
    lookup = normalize_lookup(raw_value)
    for country in COUNTRIES:
        if lookup in {normalize_lookup(country.key), normalize_lookup(country.label)}:
            return country
    available = ", ".join(country.key for country in COUNTRIES)
    raise ValueError(f"Неизвестная страна: {raw_value}. Доступно: {available}")


def resolve_city(country: CountryOption, raw_value: str) -> CityOption:
    lookup = normalize_lookup(raw_value)
    for city in country.cities:
        known_values = {
            normalize_lookup(city.key),
            normalize_lookup(city.label),
            *(normalize_lookup(alias) for alias in city.aliases),
        }
        if lookup in known_values:
            return city
    available = ", ".join(city.key for city in country.cities)
    raise ValueError(
        f"Неизвестный город для страны {country.label}: {raw_value}. "
        f"Доступно: {available}"
    )


def search_cities(country: CountryOption, raw_value: str, limit: int = 8) -> list[CityOption]:
    lookup = normalize_lookup(raw_value)
    ranked: list[tuple[int, CityOption]] = []

    for city in country.cities:
        haystacks = (
            city.label,
            city.key,
            city.query_name,
            *city.aliases,
        )
        normalized_haystacks = tuple(normalize_lookup(item) for item in haystacks)
        score = 0

        if lookup == normalize_lookup(city.label):
            score = 100
        elif lookup == normalize_lookup(city.key):
            score = 95
        elif lookup in normalized_haystacks:
            score = 90
        elif any(item.startswith(lookup) for item in normalized_haystacks):
            score = 75
        elif any(lookup in item for item in normalized_haystacks):
            score = 50

        if score:
            ranked.append((score, city))

    ranked.sort(key=lambda item: (-item[0], item[1].label))
    return [city for _, city in ranked[:limit]]


def build_custom_city(country: CountryOption, raw_value: str) -> CityOption:
    cleaned = raw_value.strip()
    label = cleaned.title() if cleaned.isascii() else cleaned
    return CityOption(
        key=slugify_lookup(label),
        label=label,
        query_name=f"{label}, {country.label}",
        two_gis_base_url=None,
    )
