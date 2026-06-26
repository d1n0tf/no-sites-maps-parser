from __future__ import annotations

import base64
import binascii
import html
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
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .models import CityOption, VenueRecord, VenueSnapshot
from .utils import clean_text

CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)

ANTI_DETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""

HTTP_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
WEBSITE_EXCLUDED_DOMAINS = (
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


def find_chrome_binary() -> str | None:
    executable = which("chrome.exe")
    if executable:
        return executable

    for candidate in CHROME_CANDIDATES:
        if candidate.exists():
            return str(candidate)

    return None


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


def is_proxy_website_domain(host: str) -> bool:
    return any(_domain_matches(host, domain) for domain in WEBSITE_PROXY_DOMAINS)


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
    normalized_href = html.unescape(href).replace("\\/", "/").strip()
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

        while stagnant_rounds < 5:
            items = self.driver.find_elements(By.CSS_SELECTOR, item_selector)
            before = len(urls)

            for item in items:
                try:
                    url = extractor(item)
                except Exception:
                    continue

                if not url:
                    continue

                normalized_url = self.normalize_detail_url(url)
                if normalized_url in seen:
                    continue

                seen.add(normalized_url)
                urls.append(normalized_url)
                if max_results is not None and len(urls) >= max_results:
                    break

            if len(urls) == before:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            if items:
                self._scroll_results_container(items[-1])
                self.pause(1.0, 1.6)
            else:
                break

            if max_results is not None and len(urls) >= max_results:
                break

        return urls[:max_results] if max_results is not None else urls

    def _scroll_results_container(self, item: WebElement) -> None:
        self.driver.execute_script(
            """
            const item = arguments[0];
            if (!item) {
                return;
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

            item.scrollIntoView({ block: "end", inline: "nearest" });

            let container = item.parentElement;
            while (container && container !== document.body && container !== document.documentElement) {
                if (isScrollable(container)) {
                    container.scrollTop = container.scrollHeight;
                    return;
                }
                container = container.parentElement;
            }

            window.scrollBy(0, Math.max(Math.floor(window.innerHeight * 0.85), 320));
            """,
            item,
        )

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
        urls: list[str] = []
        seen: set[str] = set()
        visited_pages: set[str] = set()
        requested_page = 1

        while True:
            self.driver.get(self._build_search_page_url(search_url, requested_page))
            self.pause(4.5, 5.5)
            self._resolve_captcha_if_needed()

            current_page_url = self.normalize_detail_url(self.driver.current_url)
            if current_page_url in visited_pages:
                break

            if not self._wait_for_search_results():
                break
            visited_pages.add(current_page_url)

            current_page = self._extract_search_page_number(current_page_url)
            if current_page < requested_page:
                break

            remaining = None if max_results is None else max_results - len(urls)
            page_urls = self.collect_detail_urls(
                item_selector=self.SEARCH_RESULT_SELECTOR,
                max_results=remaining,
                extractor=self._extract_result_url,
            )

            added = 0
            for page_result_url in page_urls:
                normalized_url = self.normalize_detail_url(page_result_url)
                if normalized_url in seen:
                    continue

                seen.add(normalized_url)
                urls.append(normalized_url)
                added += 1

                if max_results is not None and len(urls) >= max_results:
                    return urls[:max_results]

            if added == 0:
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
        return detail_url.split("?", maxsplit=1)[0]

    def _extract_result_url(self, item: WebElement) -> str | None:
        return item.get_attribute("href")

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
