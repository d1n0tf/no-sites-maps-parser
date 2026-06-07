from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .models import CityOption, CountryOption, VenueRecord


def clean_text(value: str) -> str:
    cleaned = (
        value.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "").strip()
    )
    return re.sub(r"\s+", " ", cleaned)


def prompt_choice(title: str, options: list[str]) -> int:
    print(f"\n{title}")
    for index, option in enumerate(options, start=1):
        print(f"{index}. {option}")

    while True:
        raw_value = input("\nВведите номер: ").strip()
        if raw_value.isdigit():
            chosen = int(raw_value)
            if 1 <= chosen <= len(options):
                return chosen - 1
        print("Нужно ввести номер из списка.")


def prompt_search_query(title: str) -> str:
    while True:
        raw_value = input(f"\n{title}\n> ").strip()
        if raw_value:
            return raw_value
        print("Нужно ввести название или его часть.")


def format_city_option(city: CityOption) -> str:
    if city.two_gis_base_url:
        return f"{city.label} (есть 2ГИС)"
    return f"{city.label} (без 2ГИС)"


def aggregate_records(records: list[VenueRecord]) -> pd.DataFrame:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for record in records:
        key = (
            clean_text(record.name).casefold(),
            clean_text(record.address).casefold(),
        )
        bucket = grouped.setdefault(
            key,
            {
                "Название": clean_text(record.name),
                "Адрес": clean_text(record.address),
                "Страна": record.country,
                "Город": record.city,
                "Источники": set(),
                "Поисковые запросы": set(),
                "Ссылки": [],
            },
        )
        bucket["Источники"].add(record.provider)
        bucket["Поисковые запросы"].add(record.search_query)
        links = bucket["Ссылки"]
        if record.source_url not in links:
            links.append(record.source_url)

    rows: list[dict[str, str]] = []
    for bucket in grouped.values():
        rows.append(
            {
                "Название": str(bucket["Название"]),
                "Адрес": str(bucket["Адрес"]),
                "Страна": str(bucket["Страна"]),
                "Город": str(bucket["Город"]),
                "Источники": ", ".join(sorted(bucket["Источники"])),
                "Поисковые запросы": ", ".join(sorted(bucket["Поисковые запросы"])),
                "Ссылки": " | ".join(bucket["Ссылки"]),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "Название",
                "Адрес",
                "Страна",
                "Город",
                "Источники",
                "Поисковые запросы",
                "Ссылки",
            ]
        )

    dataframe = pd.DataFrame(rows)
    return dataframe.sort_values(by=["Название", "Адрес"], kind="stable").reset_index(
        drop=True
    )


def save_results(
    dataframe: pd.DataFrame,
    output_dir: Path,
    country: CountryOption,
    city_key: str,
) -> Path:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = (
        output_dir / f"venues_without_sites_{country.key}_{city_key}_{timestamp}.csv"
    )
    dataframe.to_csv(file_path, index=False, encoding="utf-8-sig")
    return file_path


def render_preview(dataframe: pd.DataFrame, limit: int = 30) -> str:
    if dataframe.empty:
        return "Ничего не найдено."

    preview = dataframe.loc[:, ["Название", "Адрес"]].head(limit)
    return preview.to_string(index=False)
