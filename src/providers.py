from __future__ import annotations

import base64
import binascii
import html
import os
import random
import re
import time
import urllib.parse
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from shutil import which

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .models import CityOption, VenueRecord, VenueSnapshot
from .utils import clean_text

CHROME_CANDIDATES = (
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/google-chrome-stable"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/chromium-browser"),
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)
CHROME_BINARY_ENV_VARS = ("CHROME_BINARY", "CHROME_PATH", "GOOGLE_CHROME_BIN")
CHROMEDRIVER_ENV_VARS = ("CHROMEDRIVER", "CHROMEDRIVER_PATH")
CHROME_EXECUTABLE_NAMES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
    "chrome.exe",
)
CHROMEDRIVER_EXECUTABLE_NAMES = ("chromedriver", "chromedriver.exe")

ANTI_DETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""

HTTP_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
JSON_ASCII_ESCAPE_RE = re.compile(r"\\u00([0-7][0-9a-fA-F])")
VERSION_PART_RE = re.compile(r"\d+(?:\.\d+)+")
WEBSITE_MARKER_RE = re.compile(r'"type"\s*:\s*"website"|type=["\']website["\']')
TWO_GIS_DOMAINS = (
    "2gis.ru",
    "2gis.com",
    "2gis.am",
    "2gis.ae",
    "2gis.az",
    "2gis.by",
    "2gis.ge",
    "2gis.kg",
    "2gis.kz",
    "2gis.tj",
    "2gis.uz",
)
WEBSITE_EXCLUDED_DOMAINS = TWO_GIS_DOMAINS + (
    "vk.com",
    "t.me",
    "telegram.me",
    "telegram.org",
    "wa.me",
    "whatsapp.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "max.ru",
    "ok.ru",
    "rutube.ru",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "info2gis.tilda.ws",
    "onelink.me",
)
WEBSITE_PROXY_DOMAINS = (
    "link.2gis.ru",
    "info2gis.tilda.ws",
)


class ProviderBlockedError(RuntimeError):
    """Raised when the provider shows a captcha or a hard block page."""


def provider_label(provider_key: str) -> str:
    labels = {
        "google": "Google Maps",
        "yandex": "Яндекс.Карты",
        "2gis": "2ГИС",
    }
    return labels[provider_key]


def _existing_file(path: str | Path | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    if candidate.is_file():
        return candidate
    return None


def _candidate_from_env(env_vars: tuple[str, ...]) -> Path | None:
    for env_var in env_vars:
        candidate = _existing_file(os.environ.get(env_var))
        if candidate:
            return candidate
    return None


def _candidate_from_path(names: tuple[str, ...]) -> Path | None:
    for name in names:
        executable = which(name)
        candidate = _existing_file(executable)
        if candidate:
            return candidate
    return None


def _cache_version(path: Path) -> tuple[int, ...]:
    for part in reversed(path.parts):
        if VERSION_PART_RE.fullmatch(part):
            return tuple(int(value) for value in part.split("."))
    return ()


def _selenium_cache_candidates(cache_name: str, executable_names: tuple[str, ...]) -> list[Path]:
    cache_dir = Path.home() / ".cache" / "selenium" / cache_name
    if not cache_dir.exists():
        return []

    candidates: list[Path] = []
    for executable_name in executable_names:
        candidates.extend(path for path in cache_dir.glob(f"**/{executable_name}") if path.is_file())
    return sorted(candidates, key=lambda path: (_cache_version(path), str(path)), reverse=True)


def find_chrome_binary() -> str | None:
    env_candidate = _candidate_from_env(CHROME_BINARY_ENV_VARS)
    if env_candidate:
        return str(env_candidate)

    path_candidate = _candidate_from_path(CHROME_EXECUTABLE_NAMES)
    if path_candidate:
        return str(path_candidate)

    for candidate in CHROME_CANDIDATES:
        existing_candidate = _existing_file(candidate)
        if existing_candidate:
            return str(existing_candidate)

    cached_candidates = _selenium_cache_candidates("chrome", CHROME_EXECUTABLE_NAMES)
    if cached_candidates:
        return str(cached_candidates[0])

    return None


def find_chromedriver_binary(chrome_binary: str | None = None) -> str | None:
    env_candidate = _candidate_from_env(CHROMEDRIVER_ENV_VARS)
    if env_candidate:
        return str(env_candidate)

    path_candidate = _candidate_from_path(CHROMEDRIVER_EXECUTABLE_NAMES)
    if path_candidate:
        return str(path_candidate)

    cached_candidates = _selenium_cache_candidates(
        "chromedriver",
        CHROMEDRIVER_EXECUTABLE_NAMES,
    )
    if not cached_candidates:
        return None

    chrome_version = _cache_version(Path(chrome_binary)) if chrome_binary else ()
    if chrome_version:
        for candidate in cached_candidates:
            if _cache_version(candidate) == chrome_version:
                return str(candidate)

    return str(cached_candidates[0])


def build_driver(headless: bool) -> webdriver.Chrome:
    options = Options()
    options.page_load_strategy = "eager"
    options.add_argument("--lang=ru-RU")
    options.add_argument("--window-size=1600,2200")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-search-engine-choice-screen")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")

    binary_location = find_chrome_binary()
    if binary_location:
        options.binary_location = binary_location

    chromedriver_location = find_chromedriver_binary(binary_location)
    if chromedriver_location:
        service = ChromeService(executable_path=chromedriver_location)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(45)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": ANTI_DETECT_SCRIPT},
    )
    return driver


def extract_multiline_value(text: str) -> str:
    parts = [clean_text(part) for part in text.splitlines() if clean_text(part)]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " ".join(parts[1:])


def _domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def is_excluded_website_domain(host: str) -> bool:
    return any(_domain_matches(host, domain) for domain in WEBSITE_EXCLUDED_DOMAINS)


def is_two_gis_domain(host: str) -> bool:
    return any(_domain_matches(host, domain) for domain in TWO_GIS_DOMAINS)


def is_proxy_website_domain(host: str) -> bool:
    return any(_domain_matches(host, domain) for domain in WEBSITE_PROXY_DOMAINS)


def normalize_markup_urls(markup: str) -> str:
    normalized_markup = html.unescape(markup).replace("\\/", "/")
    return JSON_ASCII_ESCAPE_RE.sub(
        lambda match: chr(int(match.group(1), 16)),
        normalized_markup,
    )


def extract_proxy_path_website_candidates(parsed_href: urllib.parse.ParseResult) -> list[str]:
    host = (parsed_href.hostname or "").casefold()
    path_segments = [segment for segment in parsed_href.path.split("/") if segment]
    if host != "link.2gis.ru" or len(path_segments) < 3 or not path_segments[0].startswith("4."):
        return []

    encoded_payload = urllib.parse.unquote(path_segments[2])
    padding = "=" * (-len(encoded_payload) % 4)
    try:
        decoded_payload = base64.urlsafe_b64decode(encoded_payload + padding).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return []

    return [
        line.rstrip(".,);")
        for line in decoded_payload.splitlines()
        if line.startswith(("http://", "https://"))
    ]


def extract_business_website_candidates(href: str) -> list[str]:
    normalized_href = normalize_markup_urls(href).strip()
    if not normalized_href.startswith(("http://", "https://")):
        return []

    parsed_href = urllib.parse.urlparse(normalized_href)
    direct_host = (parsed_href.hostname or "").casefold()
    candidates: list[str] = []

    if direct_host and not is_proxy_website_domain(direct_host):
        candidates.append(normalized_href)
    else:
        candidates.extend(extract_proxy_path_website_candidates(parsed_href))

    query_payload = html.unescape(parsed_href.query)
    if query_payload:
        decoded_query = urllib.parse.unquote(query_payload)
        if decoded_query.startswith(("http://", "https://")):
            candidates.append(decoded_query.rstrip(".,);"))

        if "=" in query_payload:
            query_pairs = urllib.parse.parse_qsl(query_payload, keep_blank_values=True)
            for _, value in query_pairs:
                decoded_value = urllib.parse.unquote(html.unescape(value))
                if decoded_value.startswith(("http://", "https://")):
                    candidates.append(decoded_value.rstrip(".,);"))

    fragment_payload = urllib.parse.unquote(html.unescape(parsed_href.fragment))
    if fragment_payload:
        for match in HTTP_URL_RE.findall(fragment_payload):
            candidates.append(match.rstrip(".,);"))

    deduplicated: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            deduplicated.append(candidate)
    return deduplicated


def has_business_website_link(hrefs: list[str]) -> bool:
    for href in hrefs:
        for candidate in extract_business_website_candidates(href):
            parsed_candidate = urllib.parse.urlparse(candidate)
            host = (parsed_candidate.hostname or "").casefold()
            if not host:
                continue
            if is_excluded_website_domain(host):
                continue
            return True
    return False


def extract_marked_website_links(markup: str) -> list[str]:
    normalized_markup = normalize_markup_urls(markup)
    candidates: list[str] = []
    seen: set[str] = set()

    for marker in WEBSITE_MARKER_RE.finditer(normalized_markup):
        start = max(0, marker.start() - 1200)
        end = min(len(normalized_markup), marker.end() + 1200)
        snippet = normalized_markup[start:end]

        for url in HTTP_URL_RE.findall(snippet):
            normalized_url = url.rstrip(".,);}")
            if normalized_url in seen:
                continue

            seen.add(normalized_url)
            candidates.append(normalized_url)

    return candidates


class BaseMapsScraper(ABC):
    provider_key: str

    def __init__(self, headless: bool) -> None:
        self.headless = headless
        self.driver = build_driver(headless=headless)
        self.wait = WebDriverWait(self.driver, 20)

    @property
    def label(self) -> str:
        return provider_label(self.provider_key)

    def close(self) -> None:
        self.driver.quit()

    def pause(self, start: float = 0.8, end: float = 1.3) -> None:
        time.sleep(random.uniform(start, end))

    def scrape(
        self,
        city: CityOption,
        country_label: str,
        search_terms: list[str],
        max_results: int | None,
    ) -> list[VenueRecord]:
        records: list[VenueRecord] = []
        cache: dict[str, VenueSnapshot | None] = {}

        for index, search_term in enumerate(search_terms, start=1):
            print(f"\n[{self.label}] Поисковый запрос {index}/{len(search_terms)}: {search_term}")
            try:
                detail_urls = self.search_category_urls(city, search_term, max_results)
            except ProviderBlockedError as error:
                print(f"  Пропускаю источник: {error}")
                break

            print(f"  Кандидатов на проверку: {len(detail_urls)}")
            for position, detail_url in enumerate(detail_urls, start=1):
                normalized_url = self.normalize_detail_url(detail_url)
                if normalized_url in cache:
                    snapshot = cache[normalized_url]
                else:
                    snapshot = self.fetch_snapshot(normalized_url, city)
                    cache[normalized_url] = snapshot
                    self.pause()

                if not snapshot or snapshot.has_website:
                    continue

                records.append(
                    VenueRecord(
                        name=snapshot.name,
                        address=snapshot.address,
                        country=country_label,
                        city=city.label,
                        provider=self.label,
                        search_query=search_term,
                        source_url=snapshot.source_url,
                    )
                )

                print(f"  [{position}/{len(detail_urls)}] Без сайта: {snapshot.name}")

        return records

    def collect_detail_urls(
        self,
        item_selector: str,
        max_results: int | None,
        extractor: Callable[[WebElement], str | None],
    ) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        stagnant_rounds = 0

        while stagnant_rounds < 8:
            items = self.driver.find_elements(By.CSS_SELECTOR, item_selector)
            before = len(urls)

            def add_url(url: str) -> None:
                normalized_url = self.normalize_detail_url(url)
                if normalized_url in seen:
                    return

                seen.add(normalized_url)
                urls.append(normalized_url)

            for item in items:
                try:
                    url = extractor(item)
                except Exception:
                    continue

                if not url:
                    continue

                add_url(url)
                if max_results is not None and len(urls) >= max_results:
                    break

            if max_results is None or len(urls) < max_results:
                for url in self._extract_page_source_detail_urls():
                    add_url(url)
                    if max_results is not None and len(urls) >= max_results:
                        break

            scrolled = False
            if items:
                scrolled = self._scroll_results_container(items[-1])
                self.pause(1.0, 1.6)
            else:
                break

            if len(urls) == before and not scrolled:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            if max_results is not None and len(urls) >= max_results:
                break

        return urls[:max_results] if max_results is not None else urls

    def _extract_page_source_detail_urls(self) -> list[str]:
        return []

    def _scroll_results_container(self, item: WebElement) -> bool:
        result = self.driver.execute_script(
            """
            const item = arguments[0];
            if (!item) {
                return false;
            }

            const scrollableOverflow = new Set(["auto", "scroll", "overlay"]);

            function isScrollable(element) {
                if (!element) {
                    return false;
                }

                const style = window.getComputedStyle(element);
                return (
                    (element.getAttribute("data-scroll") === "true" ||
                        scrollableOverflow.has(style.overflowY)) &&
                    element.scrollHeight > element.clientHeight + 8
                );
            }

            let container = item.parentElement;
            while (container && container !== document.body && container !== document.documentElement) {
                if (isScrollable(container)) {
                    const before = container.scrollTop;
                    item.scrollIntoView({ block: "end", inline: "nearest" });
                    const step = Math.max(Math.floor(container.clientHeight * 0.85), 320);
                    container.scrollTop = Math.min(container.scrollTop + step, container.scrollHeight);
                    if (Math.abs(container.scrollTop - before) <= 1) {
                        container.scrollTop = container.scrollHeight;
                    }
                    return Math.abs(container.scrollTop - before) > 1;
                }
                container = container.parentElement;
            }

            const before = window.scrollY;
            item.scrollIntoView({ block: "end", inline: "nearest" });
            window.scrollBy(0, Math.max(Math.floor(window.innerHeight * 0.85), 320));
            return Math.abs(window.scrollY - before) > 1;
            """,
            item,
        )
        return bool(result)

    @abstractmethod
    def search_category_urls(
        self,
        city: CityOption,
        search_term: str,
        max_results: int | None,
    ) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def fetch_snapshot(self, detail_url: str, city: CityOption) -> VenueSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def normalize_detail_url(self, detail_url: str) -> str:
        raise NotImplementedError


class GoogleMapsScraper(BaseMapsScraper):
    provider_key = "google"

    def search_category_urls(
        self,
        city: CityOption,
        search_term: str,
        max_results: int | None,
    ) -> list[str]:
        query = urllib.parse.quote(f"{search_term} {city.query_name}")
        self.driver.get(f"https://www.google.com/maps/search/{query}/?hl=ru")
        self._dismiss_consent()
        try:
            self.wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div[role="article"]'))
            )
        except TimeoutException:
            return []
        return self.collect_detail_urls(
            item_selector='div[role="article"]',
            max_results=max_results,
            extractor=self._extract_result_url,
        )

    def fetch_snapshot(self, detail_url: str, city: CityOption) -> VenueSnapshot | None:
        self.driver.get(detail_url)
        self._dismiss_consent()

        try:
            self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'button[data-item-id="address"]'))
            )
        except TimeoutException:
            return None

        names = [
            clean_text(element.text)
            for element in self.driver.find_elements(By.CSS_SELECTOR, "h1")
            if clean_text(element.text) and clean_text(element.text) != "Результаты"
        ]
        if not names:
            return None

        address = extract_multiline_value(
            self.driver.find_element(By.CSS_SELECTOR, 'button[data-item-id="address"]').text
        )
        if not address:
            return None

        has_website = bool(
            self.driver.find_elements(
                By.CSS_SELECTOR,
                'a[data-item-id="authority"], button[data-item-id="authority"]',
            )
        )

        return VenueSnapshot(
            name=names[-1],
            address=clean_text(address),
            source_url=self.driver.current_url,
            has_website=has_website,
        )

    def normalize_detail_url(self, detail_url: str) -> str:
        return detail_url

    def _extract_result_url(self, item: WebElement) -> str | None:
        anchor = item.find_element(By.CSS_SELECTOR, 'a[href*="/maps/place/"]')
        return anchor.get_attribute("href")

    def _dismiss_consent(self) -> None:
        for xpath in (
            "//button[.='Принять все']",
            "//button[.='Accept all']",
            "//button[.='I agree']",
        ):
            buttons = self.driver.find_elements(By.XPATH, xpath)
            if buttons:
                buttons[0].click()
                self.pause(1.0, 1.5)
                return


class YandexMapsScraper(BaseMapsScraper):
    provider_key = "yandex"
    ORG_URL_RE = re.compile(r"https://yandex\.com/maps/org/[^\"?#]+/\d+")

    def search_category_urls(
        self,
        city: CityOption,
        search_term: str,
        max_results: int | None,
    ) -> list[str]:
        query = urllib.parse.quote(f"{search_term} {city.query_name}")
        self.driver.get(f"https://yandex.com/maps/?text={query}")
        try:
            self.wait.until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, ".search-business-snippet-view")
                )
            )
        except TimeoutException:
            return []
        return self.collect_detail_urls(
            item_selector=".search-business-snippet-view",
            max_results=max_results,
            extractor=self._extract_result_url,
        )

    def fetch_snapshot(self, detail_url: str, city: CityOption) -> VenueSnapshot | None:
        self.driver.get(detail_url)

        try:
            self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".orgpage-header-view__header"))
            )
        except TimeoutException:
            return None

        name = clean_text(
            self.driver.find_element(By.CSS_SELECTOR, ".orgpage-header-view__header").text
        )
        address_links = self.driver.find_elements(
            By.CSS_SELECTOR, ".business-contacts-view__address-link"
        )
        if not name or not address_links:
            return None

        address = clean_text(address_links[0].text)
        has_website = bool(
            self.driver.find_elements(By.CSS_SELECTOR, ".business-urls-view__text")
        )

        return VenueSnapshot(
            name=name,
            address=address,
            source_url=self.driver.current_url,
            has_website=has_website,
        )

    def normalize_detail_url(self, detail_url: str) -> str:
        match = self.ORG_URL_RE.search(detail_url)
        return match.group(0) if match else detail_url

    def _extract_result_url(self, item: WebElement) -> str | None:
        for anchor in item.find_elements(By.CSS_SELECTOR, 'a[href*="/maps/org/"]'):
            href = anchor.get_attribute("href") or ""
            match = self.ORG_URL_RE.search(href)
            if match:
                return match.group(0)

        html = item.get_attribute("innerHTML") or ""
        match = self.ORG_URL_RE.search(html)
        return match.group(0) if match else None


class TwoGisScraper(BaseMapsScraper):
    provider_key = "2gis"
    SEARCH_RESULT_SELECTOR = 'a[href*="/firm/"]'
    SEARCH_PAGE_LINK_SELECTOR = 'a[href*="/search/"][href*="/page/"]'
    FIRM_PATH_RE = re.compile(
        r"(?P<host>https?://[^/\"'<>\s\\]+)?/"
        r"(?P<city>[^/\"'<>\s\\]+)/firm/(?P<id>\d+)"
        r"(?=[/?#\"'<>\s\\]|$)"
    )
    SEARCH_CURRENT_PAGE_RE = re.compile(r'"currentPage"\s*:\s*(\d+)')
    SEARCH_TOTAL_PAGES_RE = re.compile(r'"pages"\s*:\s*(\d+)')
    PAGE_NUMBER_RE = re.compile(r"/page/(\d+)(?:[/?#]|$)")

    def search_category_urls(
        self,
        city: CityOption,
        search_term: str,
        max_results: int | None,
    ) -> list[str]:
        if not city.two_gis_base_url:
            return []

        query = urllib.parse.quote(f"{search_term} {city.query_name}")
        search_url = f"{city.two_gis_base_url}/search/{query}"
        city_path = urllib.parse.urlparse(city.two_gis_base_url).path.strip("/")
        self._current_city_slug = city_path.split("/", maxsplit=1)[0]
        urls: list[str] = []
        seen: set[str] = set()
        visited_pages: set[int] = set()
        requested_page = 1

        while True:
            if requested_page <= 1 or not self._click_search_page_link(requested_page):
                self.driver.get(self._build_search_page_url(search_url, requested_page))
            self.pause(4.5, 5.5)
            self._resolve_captcha_if_needed()

            current_page_url = self.normalize_detail_url(self.driver.current_url)
            current_page = self._extract_current_search_page_number(current_page_url)
            if current_page in visited_pages:
                break

            if not self._wait_for_search_results():
                break
            visited_pages.add(current_page)

            if current_page < requested_page:
                break

            total_pages = self._extract_search_total_pages()
            remaining = None if max_results is None else max_results - len(urls)
            page_urls = self.collect_detail_urls(
                item_selector=self.SEARCH_RESULT_SELECTOR,
                max_results=remaining,
                extractor=self._extract_result_url,
            )

            def add_page_urls(result_urls: list[str]) -> int:
                added_count = 0
                for page_result_url in result_urls:
                    normalized_url = self.normalize_detail_url(page_result_url)
                    if normalized_url in seen:
                        continue

                    seen.add(normalized_url)
                    urls.append(normalized_url)
                    added_count += 1

                    if max_results is not None and len(urls) >= max_results:
                        break
                return added_count

            added = add_page_urls(page_urls)

            if added == 0:
                self.pause(2.5, 3.5)
                page_urls = self.collect_detail_urls(
                    item_selector=self.SEARCH_RESULT_SELECTOR,
                    max_results=remaining,
                    extractor=self._extract_result_url,
                )
                added = add_page_urls(page_urls)

            # total_suffix = f"/{total_pages}" if total_pages else ""
            # print(
            #     f"  [2ГИС] Страница {current_page}{total_suffix}: "
            #     f"новых карточек {added}, всего {len(urls)}"
            # )

            if max_results is not None and len(urls) >= max_results:
                return urls[:max_results]

            if added == 0:
                break

            if total_pages is not None and current_page >= total_pages:
                break

            requested_page = current_page + 1

        return urls[:max_results] if max_results is not None else urls

    def fetch_snapshot(self, detail_url: str, city: CityOption) -> VenueSnapshot | None:
        self.driver.get(detail_url)
        self.pause(3.5, 4.5)
        self._resolve_captcha_if_needed()

        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1")))
        except TimeoutException:
            return None

        name = clean_text(self.driver.find_element(By.CSS_SELECTOR, "h1").text)
        address = self._extract_address(city)
        if not name or not address:
            return None

        has_website = self._has_website_link()
        return VenueSnapshot(
            name=name,
            address=address,
            source_url=self.driver.current_url,
            has_website=has_website,
        )

    def normalize_detail_url(self, detail_url: str) -> str:
        normalized_detail_url = normalize_markup_urls(detail_url).strip()
        firm_url = self._normalize_firm_url(normalized_detail_url)
        if firm_url:
            return firm_url
        return normalized_detail_url.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0]

    def _extract_result_url(self, item: WebElement) -> str | None:
        return item.get_attribute("href")

    def _extract_page_source_detail_urls(self) -> list[str]:
        page_source = getattr(self.driver, "page_source", "")
        return self._extract_firm_urls_from_markup(page_source)

    def _extract_firm_urls_from_markup(self, markup: str) -> list[str]:
        normalized_markup = normalize_markup_urls(markup)
        urls: list[str] = []
        seen: set[str] = set()

        for match in self.FIRM_PATH_RE.finditer(normalized_markup):
            firm_url = self._normalize_firm_match(match)
            if not firm_url or firm_url in seen:
                continue

            seen.add(firm_url)
            urls.append(firm_url)

        return urls

    def _normalize_firm_url(self, url: str) -> str | None:
        match = self.FIRM_PATH_RE.search(url)
        if not match:
            return None
        return self._normalize_firm_match(match)

    def _normalize_firm_match(self, match: re.Match[str]) -> str | None:
        host = match.group("host") or ""
        city_slug = match.group("city")
        firm_id = match.group("id")
        expected_city_slug = getattr(self, "_current_city_slug", "")
        if expected_city_slug and city_slug != expected_city_slug:
            return None

        if host:
            parsed_host = urllib.parse.urlparse(host)
            hostname = (parsed_host.hostname or "").casefold()
            if not hostname or not is_two_gis_domain(hostname):
                return None
            origin = f"{parsed_host.scheme}://{parsed_host.netloc}"
        else:
            current_url = getattr(self.driver, "current_url", "")
            parsed_current_url = urllib.parse.urlparse(current_url)
            if not parsed_current_url.scheme or not parsed_current_url.netloc:
                return None
            origin = f"{parsed_current_url.scheme}://{parsed_current_url.netloc}"

        return f"{origin}/{city_slug}/firm/{firm_id}"

    def _wait_for_search_results(self) -> bool:
        try:
            self.wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, self.SEARCH_RESULT_SELECTOR))
            )
        except TimeoutException:
            return False
        return True

    def _build_search_page_url(self, search_url: str, page_number: int) -> str:
        if page_number <= 1:
            return search_url
        return f"{search_url}/page/{page_number}"

    def _click_search_page_link(self, page_number: int) -> bool:
        for anchor in self.driver.find_elements(By.CSS_SELECTOR, self.SEARCH_PAGE_LINK_SELECTOR):
            href = anchor.get_attribute("href") or ""
            if self._extract_search_page_number(href) != page_number:
                continue

            try:
                self.driver.execute_script(
                    """
                    arguments[0].scrollIntoView({ block: "center", inline: "nearest" });
                    arguments[0].click();
                    """,
                    anchor,
                )
            except Exception:
                try:
                    anchor.click()
                except Exception:
                    continue
            return True

        return False

    def _extract_current_search_page_number(self, current_url: str) -> int:
        url_page_number = self._extract_search_page_number(current_url)
        if url_page_number > 1:
            return url_page_number

        page_source = normalize_markup_urls(getattr(self.driver, "page_source", ""))
        match = self.SEARCH_CURRENT_PAGE_RE.search(page_source)
        if not match:
            return url_page_number
        return int(match.group(1))

    def _extract_search_total_pages(self) -> int | None:
        page_source = normalize_markup_urls(getattr(self.driver, "page_source", ""))
        match = self.SEARCH_TOTAL_PAGES_RE.search(page_source)
        if not match:
            return None
        return int(match.group(1))

    def _extract_search_page_number(self, current_url: str) -> int:
        match = self.PAGE_NUMBER_RE.search(current_url)
        if not match:
            return 1
        return int(match.group(1))

    def _extract_address(self, city: CityOption) -> str:
        geo_links = [
            clean_text(anchor.text)
            for anchor in self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/geo/"]')
            if clean_text(anchor.text)
        ]
        if geo_links:
            return clean_text(f"{geo_links[0]}, {city.label}")

        title = clean_text(self.driver.title.replace(" — 2ГИС", ""))
        parts = [clean_text(part) for part in title.split(",") if clean_text(part)]
        if len(parts) >= 3:
            return ", ".join(parts[2:])
        return title

    def _has_website_link(self) -> bool:
        hrefs = self._collect_card_hrefs()
        if hrefs and has_business_website_link(hrefs):
            return True

        for anchor in self.driver.find_elements(By.CSS_SELECTOR, 'a[href^="http"]'):
            outer_html = anchor.get_attribute("outerHTML") or ""
            if '"type":"website"' in outer_html or 'type="website"' in outer_html:
                href = anchor.get_attribute("href") or ""
                if has_business_website_link([href]):
                    return True

        marked_website_links = extract_marked_website_links(getattr(self.driver, "page_source", ""))
        if marked_website_links and has_business_website_link(marked_website_links):
            return True

        return False

    def _collect_card_hrefs(self) -> list[str]:
        hrefs: list[str] = []
        seen: set[str] = set()
        containers: list[WebElement] = []
        headings = self.driver.find_elements(By.CSS_SELECTOR, "h1")

        if headings:
            try:
                containers.append(
                    headings[0].find_element(By.XPATH, './ancestor::*[@data-scroll="true"][1]')
                )
            except Exception:
                pass

        containers.extend(self.driver.find_elements(By.CSS_SELECTOR, '[data-rack="true"]'))

        for container in containers:
            for anchor in container.find_elements(By.CSS_SELECTOR, "a[href]"):
                href = anchor.get_attribute("href") or ""
                if href and href not in seen:
                    seen.add(href)
                    hrefs.append(href)

        return hrefs

    def _resolve_captcha_if_needed(self) -> None:
        if "captcha.2gis" not in self.driver.current_url and "captcha" not in self.driver.title.lower():
            return

        if self.headless:
            raise ProviderBlockedError("2ГИС открыл капчу. Для него нужен обычный режим браузера.")

        print("\n[2ГИС] Открылось окно с капчей. Решите её в браузере и нажмите Enter.")
        input("Продолжить после капчи: ")

        if "captcha.2gis" in self.driver.current_url:
            raise ProviderBlockedError("Капча в 2ГИС не была решена.")


def create_scraper(provider_key: str, headless: bool) -> BaseMapsScraper:
    if provider_key == "google":
        return GoogleMapsScraper(headless=headless)
    if provider_key == "yandex":
        return YandexMapsScraper(headless=headless)
    if provider_key == "2gis":
        return TwoGisScraper(headless=headless)
    raise ValueError(f"Неизвестный источник: {provider_key}")
