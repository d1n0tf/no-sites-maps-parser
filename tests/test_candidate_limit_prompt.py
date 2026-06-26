from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from src.app import choose_max_results, non_negative_int
from src.utils import prompt_candidate_limit


class CandidateLimitPromptTests(unittest.TestCase):
    def test_empty_prompt_input_means_no_limit(self) -> None:
        with patch("builtins.input", return_value=""):
            self.assertIsNone(prompt_candidate_limit())

    def test_zero_prompt_input_means_no_limit(self) -> None:
        with patch("builtins.input", return_value="0"):
            self.assertIsNone(prompt_candidate_limit())

    def test_positive_prompt_input_sets_limit(self) -> None:
        with patch("builtins.input", return_value="25"):
            self.assertEqual(prompt_candidate_limit(), 25)

    def test_cli_zero_means_no_limit(self) -> None:
        self.assertIsNone(choose_max_results(0))

    def test_cli_positive_value_sets_limit(self) -> None:
        self.assertEqual(choose_max_results(10), 10)

    def test_cli_negative_value_is_rejected(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            non_negative_int("-1")


if __name__ == "__main__":
    unittest.main()
