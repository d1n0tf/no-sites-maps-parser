from __future__ import annotations

import unittest

from src.models import CityOption
from src.providers import TwoGisScraper


class FakeResultAnchor:
    def __init__(self, href: str) -> None:
        self.href = href

    def get_attribute(self, name: str) -> str:
        if name == "href":
            return self.href
        return ""


class FakeWait:
    def until(self, condition):
        return True


class FakeTwoGisDriver:
    def __init__(self, pages: dict[str, dict[str, object]]) -> None:
        self.pages = pages
        self.current_url = ""
        self.requested_url = ""
        self.visited_urls: list[str] = []

    def get(self, url: str) -> None:
        self.requested_url = url
        self.visited_urls.append(url)
        page = self.pages[url]
        self.current_url = str(page.get("actual_url", url))

    def find_elements(self, by: str, selector: str):
        page = self.pages[self.requested_url]
        if selector == TwoGisScraper.SEARCH_RESULT_SELECTOR:
            return [FakeResultAnchor(href) for href in page["results"]]
        return []


class FakeTwoGisScraper(TwoGisScraper):
    def __init__(self, driver: FakeTwoGisDriver) -> None:
        self.headless = True
        self.driver = driver
        self.wait = FakeWait()

    def pause(self, start: float = 0.8, end: float = 1.3) -> None:
        return None

    def _resolve_captcha_if_needed(self) -> None:
        return None

    def collect_detail_urls(self, item_selector, max_results, extractor):
        items = self.driver.find_elements(None, item_selector)
        urls = [extractor(item) for item in items if extractor(item)]
        if max_results is None:
            return urls
        return urls[:max_results]


class TwoGisPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.city = CityOption(
            key="moscow",
            label="Москва",
            query_name="Москва",
            two_gis_base_url="https://2gis.ru/moscow",
        )
        self.search_url = "https://2gis.ru/moscow/search/%D0%BA%D0%B0%D1%84%D0%B5%20%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0"
        self.page2_url = f"{self.search_url}/page/2"
        self.page3_url = f"{self.search_url}/page/3"

    def test_collects_all_urls_across_paginated_results(self) -> None:
        scraper = FakeTwoGisScraper(
            FakeTwoGisDriver(
                {
                    self.search_url: {
                        "results": [
                            "https://2gis.ru/moscow/firm/1",
                            "https://2gis.ru/moscow/firm/2",
                        ],
                    },
                    self.page2_url: {
                        "results": [
                            "https://2gis.ru/moscow/firm/3",
                            "https://2gis.ru/moscow/firm/4",
                        ],
                    },
                    self.page3_url: {
                        "results": ["https://2gis.ru/moscow/firm/5"],
                    },
                    f"{self.search_url}/page/4": {
                        "results": [],
                    },
                }
            )
        )

        urls = scraper.search_category_urls(self.city, "кафе", max_results=None)

        self.assertEqual(
            urls,
            [
                "https://2gis.ru/moscow/firm/1",
                "https://2gis.ru/moscow/firm/2",
                "https://2gis.ru/moscow/firm/3",
                "https://2gis.ru/moscow/firm/4",
                "https://2gis.ru/moscow/firm/5",
            ],
        )
        self.assertEqual(
            scraper.driver.visited_urls,
            [self.search_url, self.page2_url, self.page3_url, f"{self.search_url}/page/4"],
        )

    def test_respects_max_results_across_pages(self) -> None:
        scraper = FakeTwoGisScraper(
            FakeTwoGisDriver(
                {
                    self.search_url: {
                        "results": [
                            "https://2gis.ru/moscow/firm/1",
                            "https://2gis.ru/moscow/firm/2",
                        ],
                    },
                    self.page2_url: {
                        "results": [
                            "https://2gis.ru/moscow/firm/3",
                            "https://2gis.ru/moscow/firm/4",
                        ],
                    },
                    self.page3_url: {
                        "results": ["https://2gis.ru/moscow/firm/5"],
                    },
                }
            )
        )

        urls = scraper.search_category_urls(self.city, "кафе", max_results=3)

        self.assertEqual(
            urls,
            [
                "https://2gis.ru/moscow/firm/1",
                "https://2gis.ru/moscow/firm/2",
                "https://2gis.ru/moscow/firm/3",
            ],
        )
        self.assertEqual(
            scraper.driver.visited_urls,
            [self.search_url, self.page2_url],
        )

    def test_stops_when_2gis_redirects_past_last_page(self) -> None:
        scraper = FakeTwoGisScraper(
            FakeTwoGisDriver(
                {
                    self.search_url: {
                        "results": [
                            "https://2gis.ru/moscow/firm/1",
                            "https://2gis.ru/moscow/firm/2",
                        ],
                    },
                    self.page2_url: {
                        "results": [
                            "https://2gis.ru/moscow/firm/3",
                            "https://2gis.ru/moscow/firm/4",
                        ],
                    },
                    self.page3_url: {
                        "results": ["https://2gis.ru/moscow/firm/5"],
                    },
                    f"{self.search_url}/page/4": {
                        "actual_url": self.page3_url,
                        "results": ["https://2gis.ru/moscow/firm/5"],
                    },
                }
            )
        )

        urls = scraper.search_category_urls(self.city, "кафе", max_results=None)

        self.assertEqual(
            urls,
            [
                "https://2gis.ru/moscow/firm/1",
                "https://2gis.ru/moscow/firm/2",
                "https://2gis.ru/moscow/firm/3",
                "https://2gis.ru/moscow/firm/4",
                "https://2gis.ru/moscow/firm/5",
            ],
        )


if __name__ == "__main__":
    unittest.main()
