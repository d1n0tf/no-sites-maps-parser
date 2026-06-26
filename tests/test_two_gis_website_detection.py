from __future__ import annotations

import base64
import unittest

from src.providers import (
    extract_business_website_candidates,
    has_business_website_link,
)


class TwoGisWebsiteDetectionTests(unittest.TestCase):
    @staticmethod
    def build_v4_proxy_url(*targets: str) -> str:
        payload = "\n".join(targets).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii")
        return f"https://link.2gis.ru/4.2/TEST1234/{encoded}"

    def test_detects_site_hidden_behind_2gis_redirect(self) -> None:
        hrefs = [
            "http://link.2gis.ru/1.2/4C13CA91/online/20260601/project32/"
            "70000001061986082/null/example?http://fair.mos.ru",
            "https://vk.com/fairmos",
            "https://t.me/fairmos",
        ]

        self.assertTrue(has_business_website_link(hrefs))

    def test_detects_legacy_2gis_redirect_targets_with_query_params(self) -> None:
        hrefs = [
            "http://link.2gis.ru/1.2/FCC64F90/online/20260601/project32/"
            "70000001063551091/null/example?"
            "http://mozhayka.rvbar.ru/?utm_source=2gis&utm_medium=resto",
            "http://link.2gis.ru/1.2/49E1AF35/online/20260601/project32/"
            "70000001045623203/null/example?"
            "http://blabla.bar/?utm_source=2gis&utm_medium=prioritet",
            "http://link.2gis.ru/1.2/CE647B08/online/20260601/project32/"
            "70000001076499420/null/example?"
            "http://tvtower.ru/services/restaurant/?utm_source=2gis&utm_medium=2gis",
        ]

        self.assertTrue(has_business_website_link(hrefs))

        self.assertIn(
            "http://blabla.bar/?utm_source=2gis&utm_medium=prioritet",
            extract_business_website_candidates(hrefs[1]),
        )

    def test_ignores_social_and_2gis_service_links(self) -> None:
        hrefs = [
            "https://awards.2gis.ru/",
            "https://vk.com/rvbar.mozhayka",
            "https://t.me/book_reserve",
            "https://redirect.2gis.com/account/?firmId=70000001034739764",
        ]

        self.assertFalse(has_business_website_link(hrefs))

    def test_extracts_target_from_proxy_url(self) -> None:
        href = (
            "https://info2gis.tilda.ws/proxy18?"
            "target=https%3A%2F%2Fdizengof99.ru%2Fmenushabolovskaya&"
            "back=https%3A%2F%2F2gis.ru%2Fmoscow%2Fbranches%2F70000001021034069"
        )

        self.assertEqual(
            extract_business_website_candidates(href),
            [
                "https://dizengof99.ru/menushabolovskaya",
                "https://2gis.ru/moscow/branches/70000001021034069",
            ],
        )

    def test_counts_direct_business_site(self) -> None:
        hrefs = [
            "https://mozhayka.rvbar.ru/?utm_source=2gis&utm_medium=resto",
        ]

        self.assertTrue(has_business_website_link(hrefs))

    def test_extracts_target_from_new_proxy_path(self) -> None:
        href = self.build_v4_proxy_url(
            "http://blabla.bar/?utm_source=2gis&utm_medium=prioritet&utm_campaign=2gis_geo",
            "https://s1.bss.2gis.com/bss/3",
            "[]",
        )

        self.assertIn(
            "http://blabla.bar/?utm_source=2gis&utm_medium=prioritet&utm_campaign=2gis_geo",
            extract_business_website_candidates(href),
        )

    def test_detects_site_in_live_2gis_v4_contact_links(self) -> None:
        hrefs = [
            self.build_v4_proxy_url("https://t.me/BlaBlaBarmsk", "[]"),
            self.build_v4_proxy_url(
                "http://blabla.bar/?utm_source=2gis&utm_medium=prioritet&utm_campaign=2gis_geo",
                "https://s1.bss.2gis.com/bss/3",
                "[]",
            ),
            "mailto:info@blabla.bar",
        ]

        self.assertTrue(has_business_website_link(hrefs))

    def test_ignores_2gis_footer_links_in_card_container(self) -> None:
        hrefs = [
            "https://2gis.ru/moscow/directions/points/%7C37.704269%2C55.764633%3B70000001047594829",
            "https://redirect.2gis.com/account/?language=ru&id=32&firmId=70000001074654250",
            "http://redirect.2gis.com/adv/?language=ru&page=online_owner&id=32",
            "https://2gis.onelink.me/oJqA?af_js_web=true&deep_link_value=dgis://2gis.ru/moscow/firm/70000001047594829",
            "https://2gis.onelink.me/65w0?af_js_web=true&deep_link_value=dgis://2gis.ru/moscow/firm/70000001047594829",
            "tel:+79037299295",
        ]

        self.assertFalse(has_business_website_link(hrefs))


if __name__ == "__main__":
    unittest.main()
