from __future__ import annotations

import unittest

from src.models import CityOption
from src.providers import TwoGisScraper


class FakeResultAnchor:
    def __init__(self, href: str, driver: FakeTwoGisDriver | None = None) -> None:
        self.href = href
        self.driver = driver

    def get_attribute(self, name: str) -> str:
        if name == "href":
            return self.href
        return ""

    def click(self) -> None:
        if self.driver is not None:
            self.driver.open_by_click(self.href)


class FakeWait:
    def until(self, condition):
        return True


class FakeTwoGisDriver:
    def __init__(self, pages: dict[str, dict[str, object]]) -> None:
        self.pages = pages
        self.current_url = ""
        self.page_source = ""
        self.requested_url = ""
        self.visited_urls: list[str] = []
        self.direct_urls: list[str] = []
        self.clicked_urls: list[str] = []

    def get(self, url: str) -> None:
        self.direct_urls.append(url)
        self._open(url, clicked=False)

    def open_by_click(self, url: str) -> None:
        self.clicked_urls.append(url)
        self._open(url, clicked=True)

    def _open(self, url: str, clicked: bool) -> None:
        self.requested_url = url
        self.visited_urls.append(url)
        page = self.pages[url]
        actual_url_key = "click_actual_url" if clicked else "actual_url"
        html_key = "click_html" if clicked else "html"
        self.current_url = str(page.get(actual_url_key, page.get("actual_url", url)))
        self.page_source = str(page.get(html_key, page.get("html", "")))

    def find_elements(self, by: str, selector: str):
        page = self.pages[self.requested_url]
        if selector == TwoGisScraper.SEARCH_RESULT_SELECTOR:
            return [FakeResultAnchor(href) for href in page["results"]]
        if selector == TwoGisScraper.SEARCH_PAGE_LINK_SELECTOR:
            links = page.get("page_links")
            if links is None:
                links = [url for url in self.pages if "/page/" in url]
            return [FakeResultAnchor(str(href), self) for href in links]
        return []

    def execute_script(self, script: str, item: FakeResultAnchor) -> None:
        if "click" in script:
            item.click()


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
        urls = []
        seen = set()
        for item in items:
            url = extractor(item)
            if not url:
                continue
            normalized_url = self.normalize_detail_url(url)
            if normalized_url in seen:
                continue
            seen.add(normalized_url)
            urls.append(normalized_url)

        for url in self._extract_page_source_detail_urls():
            normalized_url = self.normalize_detail_url(url)
            if normalized_url in seen:
                continue
            seen.add(normalized_url)
            urls.append(normalized_url)

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

    def test_collects_urls_from_2gis_page_source(self) -> None:
        scraper = FakeTwoGisScraper(
            FakeTwoGisDriver(
                {
                    self.search_url: {
                        "results": ["https://2gis.ru/moscow/firm/1?m=37.1,55.1/16"],
                        "html": (
                            '<script>{"items":["/moscow/firm/2?m=37.2,55.2/16",'
                            '"https:\\/\\/2gis.ru\\/moscow\\/firm\\/3\\/tab\\/info",'
                            '"https://example.test/moscow/firm/999"]}</script>'
                        ),
                    },
                    self.page2_url: {
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
            ],
        )

    def test_uses_pagination_click_after_direct_2gis_page_limit(self) -> None:
        page4_url = f"{self.search_url}/page/4"
        page5_url = f"{self.search_url}/page/5"
        page6_url = f"{self.search_url}/page/6"
        page7_url = f"{self.search_url}/page/7"
        scraper = FakeTwoGisScraper(
            FakeTwoGisDriver(
                {
                    self.search_url: {
                        "results": ["https://2gis.ru/moscow/firm/1"],
                        "html": '{"currentPage":1,"pages":7}',
                    },
                    self.page2_url: {
                        "results": ["https://2gis.ru/moscow/firm/2"],
                        "html": '{"currentPage":2,"pages":7}',
                    },
                    self.page3_url: {
                        "results": ["https://2gis.ru/moscow/firm/3"],
                        "html": '{"currentPage":3,"pages":7}',
                    },
                    page4_url: {
                        "results": ["https://2gis.ru/moscow/firm/4"],
                        "html": '{"currentPage":4,"pages":7}',
                    },
                    page5_url: {
                        "results": ["https://2gis.ru/moscow/firm/5"],
                        "html": '{"currentPage":5,"pages":7}',
                    },
                    page6_url: {
                        "actual_url": self.search_url,
                        "click_actual_url": self.search_url,
                        "results": ["https://2gis.ru/moscow/firm/6"],
                        "click_html": '{"currentPage":6,"pages":7}',
                    },
                    page7_url: {
                        "actual_url": self.search_url,
                        "click_actual_url": self.search_url,
                        "results": [],
                        "click_html": '{"currentPage":7,"pages":7}',
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
                "https://2gis.ru/moscow/firm/6",
            ],
        )
        self.assertIn(page6_url, scraper.driver.clicked_urls)
        self.assertNotIn(page6_url, scraper.driver.direct_urls)


if __name__ == "__main__":
    unittest.main()
