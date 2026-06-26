from __future__ import annotations

import unittest

from src.providers import BaseMapsScraper


class FakeElement:
    def __init__(self, href: str) -> None:
        self.href = href


class FakeDriver:
    def __init__(self, pages: list[list[str]]) -> None:
        self.pages = [[FakeElement(href) for href in page] for page in pages]
        self.visible_page = 0
        self.executed_scripts: list[str] = []

    def find_elements(self, by: str, selector: str) -> list[FakeElement]:
        visible: list[FakeElement] = []
        for index in range(self.visible_page + 1):
            visible.extend(self.pages[index])
        return visible

    def execute_script(self, script: str, item: FakeElement) -> None:
        self.executed_scripts.append(script)
        if "scrollTop" not in script:
            return
        if self.visible_page < len(self.pages) - 1:
            self.visible_page += 1


class DelayedFakeDriver(FakeDriver):
    def __init__(self, pages: list[list[str]], scrolls_before_next_page: int) -> None:
        super().__init__(pages)
        self.scrolls_before_next_page = scrolls_before_next_page
        self.scrolls_since_new_page = 0

    def execute_script(self, script: str, item: FakeElement) -> bool:
        self.executed_scripts.append(script)
        if "scrollTop" not in script:
            return False

        if self.visible_page >= len(self.pages) - 1:
            return False

        self.scrolls_since_new_page += 1
        if self.scrolls_since_new_page >= self.scrolls_before_next_page:
            self.visible_page += 1
            self.scrolls_since_new_page = 0

        return True


class DummyScraper(BaseMapsScraper):
    provider_key = "google"

    def __init__(self, driver: FakeDriver) -> None:
        self.headless = True
        self.driver = driver
        self.wait = None

    def pause(self, start: float = 0.8, end: float = 1.3) -> None:
        return None

    def search_category_urls(self, city, search_term: str, max_results: int | None) -> list[str]:
        raise NotImplementedError

    def fetch_snapshot(self, detail_url: str, city):
        raise NotImplementedError

    def normalize_detail_url(self, detail_url: str) -> str:
        return detail_url


class CollectDetailUrlsTests(unittest.TestCase):
    def test_collects_more_than_first_visible_page_without_limit(self) -> None:
        scraper = DummyScraper(
            FakeDriver(
                [
                    ["https://example.test/1", "https://example.test/2"],
                    ["https://example.test/3", "https://example.test/4"],
                    ["https://example.test/5"],
                ]
            )
        )

        urls = scraper.collect_detail_urls(
            item_selector='a[href*="/firm/"]',
            max_results=None,
            extractor=lambda item: item.href,
        )

        self.assertEqual(
            urls,
            [
                "https://example.test/1",
                "https://example.test/2",
                "https://example.test/3",
                "https://example.test/4",
                "https://example.test/5",
            ],
        )
        self.assertTrue(any("scrollTop" in script for script in scraper.driver.executed_scripts))

    def test_keeps_limit_after_loading_additional_pages(self) -> None:
        scraper = DummyScraper(
            FakeDriver(
                [
                    ["https://example.test/1", "https://example.test/2"],
                    ["https://example.test/3", "https://example.test/4"],
                ]
            )
        )

        urls = scraper.collect_detail_urls(
            item_selector='a[href*="/firm/"]',
            max_results=3,
            extractor=lambda item: item.href,
        )

        self.assertEqual(
            urls,
            [
                "https://example.test/1",
                "https://example.test/2",
                "https://example.test/3",
            ],
        )

    def test_keeps_scrolling_while_list_moves_without_new_urls(self) -> None:
        scraper = DummyScraper(
            DelayedFakeDriver(
                [
                    ["https://example.test/1"],
                    ["https://example.test/2"],
                ],
                scrolls_before_next_page=6,
            )
        )

        urls = scraper.collect_detail_urls(
            item_selector='a[href*="/firm/"]',
            max_results=None,
            extractor=lambda item: item.href,
        )

        self.assertEqual(
            urls,
            [
                "https://example.test/1",
                "https://example.test/2",
            ],
        )


if __name__ == "__main__":
    unittest.main()
