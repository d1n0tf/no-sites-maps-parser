from __future__ import annotations

import argparse
from pathlib import Path

from .config import (
    COUNTRIES,
    DEFAULT_SEARCH_TERMS,
    PROVIDER_LABELS,
    SEARCH_MODE_LABEL,
    build_custom_city,
    resolve_city,
    resolve_country,
    search_cities,
)
from .providers import create_scraper
from .utils import (
    aggregate_records,
    format_city_option,
    prompt_candidate_limit,
    prompt_choice,
    prompt_search_query,
    render_preview,
    save_results,
)


def non_negative_int(value: str) -> int:
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("нужно ввести целое число") from error

    if parsed_value < 0:
        raise argparse.ArgumentTypeError("лимит не может быть отрицательным")
    return parsed_value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Собирает заведения без сайта из Google Maps, Яндекс.Карт и 2ГИС."
    )
    parser.add_argument("--country", help="Код страны, например: russia, kazakhstan, belarus")
    parser.add_argument(
        "--location",
        "--city",
        dest="location",
        help="Город или населенный пункт. Можно код или обычное название.",
    )
    parser.add_argument(
        "--provider",
        choices=("all", "google", "yandex", "2gis"),
        help="Источник данных",
    )
    parser.add_argument(
        "--queries",
        "--categories",
        dest="queries",
        nargs="*",
        help="Свои поисковые запросы. Если не заданы, используется широкий режим по всем заведениям общепита.",
    )
    parser.add_argument(
        "--max-results",
        type=non_negative_int,
        help="Лимит карточек на каждый поисковый запрос и источник. 0 = без лимита.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Скрытый режим браузера. Для 2ГИС всё равно будет использован обычный режим.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Папка для CSV-файлов.",
    )
    return parser


def choose_country_and_city(args: argparse.Namespace):
    if args.country:
        country = resolve_country(args.country)
    else:
        country_index = prompt_choice(
            "Выберите страну:",
            [country.label for country in COUNTRIES],
        )
        country = COUNTRIES[country_index]

    if args.location:
        try:
            city = resolve_city(country, args.location)
        except ValueError:
            city = build_custom_city(country, args.location)
    else:
        query = prompt_search_query(
            f"Введите город или населенный пункт в стране {country.label}"
        )
        matches = search_cities(country, query)

        if matches:
            options = [format_city_option(city) for city in matches]
            options.append(f'Использовать "{query}" как введено')
            city_index = prompt_choice("Выберите подходящий вариант:", options)
            if city_index == len(matches):
                city = build_custom_city(country, query)
            else:
                city = matches[city_index]
        else:
            print(
                f'По локальному списку не нашёл "{query}". Использую это название как свободный ввод.'
            )
            city = build_custom_city(country, query)

    return country, city


def choose_provider(provider_arg: str | None) -> str:
    if provider_arg:
        return provider_arg

    options = ["Все источники", "Google Maps", "Яндекс.Карты", "2ГИС"]
    choice = prompt_choice("Выберите источник:", options)
    return ("all", "google", "yandex", "2gis")[choice]


def provider_sequence(provider_key: str) -> list[str]:
    if provider_key == "all":
        return ["google", "yandex", "2gis"]
    return [provider_key]


def choose_max_results(max_results_arg: int | None) -> int | None:
    if max_results_arg is None:
        return prompt_candidate_limit()
    return max_results_arg if max_results_arg > 0 else None


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    provider_key = choose_provider(args.provider)
    country, city = choose_country_and_city(args)
    search_terms = [term.strip() for term in (args.queries or DEFAULT_SEARCH_TERMS) if term.strip()]
    max_results = choose_max_results(args.max_results)

    print("=" * 72)
    print("ПАРСЕР ЗАВЕДЕНИЙ БЕЗ САЙТА")
    print("=" * 72)
    print(f"Страна: {country.label}")
    print(f"Населенный пункт: {city.label}")
    print(f"Источник: {PROVIDER_LABELS[provider_key]}")
    if args.queries:
        print(f"Поисковые запросы: {', '.join(search_terms)}")
    else:
        print(f"Режим поиска: {SEARCH_MODE_LABEL}")
        print(f"Внутренние запросы: {', '.join(search_terms)}")
    if max_results is None:
        print("Лимит на запрос: без лимита")
    else:
        print(f"Лимит на запрос: {max_results}")

    if provider_key == "2gis" and city.two_gis_base_url is None:
        print(
            "\n[2ГИС] Для этого населенного пункта нет готовой привязки в конфиге. "
            "Запустите Google Maps или Яндекс.Карты, либо добавьте этот пункт в конфиг."
        )
        return

    if city.two_gis_base_url is None and provider_key == "all":
        print(
            "\n[2ГИС] Для этого населенного пункта нет готовой привязки в конфиге, "
            "поэтому 2ГИС будет пропущен."
        )

    records = []
    for current_provider in provider_sequence(provider_key):
        if current_provider == "2gis" and city.two_gis_base_url is None:
            continue

        headless = args.headless and current_provider != "2gis"
        if args.headless and current_provider == "2gis":
            print("\n[2ГИС] Переключаюсь в обычный режим браузера: скрытый режим часто ловит капчу.")

        scraper = create_scraper(current_provider, headless=headless)
        try:
            provider_records = scraper.scrape(
                city=city,
                country_label=country.label,
                search_terms=search_terms,
                max_results=max_results,
            )
            records.extend(provider_records)
            print(f"\n[{scraper.label}] Найдено заведений без сайта: {len(provider_records)}")
        finally:
            scraper.close()

    dataframe = aggregate_records(records)
    print("\n" + "=" * 72)
    print(f"Уникальных заведений без сайта: {len(dataframe)}")
    print("=" * 72)
    print(render_preview(dataframe))

    output_path = save_results(
        dataframe=dataframe,
        output_dir=Path(args.output_dir),
        country=country,
        city_key=city.key,
    )
    if dataframe.empty:
        print("\nРезультатов нет, но пустой CSV всё равно сохранён.")
    print(f"\nРезультат сохранён: {output_path}")


if __name__ == "__main__":
    main()
