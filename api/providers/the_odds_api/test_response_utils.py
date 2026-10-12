from __future__ import annotations

import unittest

try:
    from .response_utils import decode_utf8_json, resolve_regions
except ImportError:
    from response_utils import decode_utf8_json, resolve_regions


class ResponseUtilsTests(unittest.TestCase):
    def test_defaults_to_all_supported_regions(self) -> None:
        self.assertEqual(resolve_regions(None), "us,uk,eu,au")

    def test_filters_and_deduplicates_regions(self) -> None:
        self.assertEqual(
            resolve_regions(" eu,us,invalid,EU "),
            "eu,us",
        )

    def test_decodes_fighter_names_as_utf8(self) -> None:
        decoded = decode_utf8_json(
            '[{"name":"Łukasz Koziorzębski"}]'.encode("utf-8")
        )
        self.assertEqual(decoded[0]["name"], "Łukasz Koziorzębski")


if __name__ == "__main__":
    unittest.main()
