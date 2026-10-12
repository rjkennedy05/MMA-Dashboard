from __future__ import annotations

import os
import unittest
from unittest.mock import patch

try:
    from .client import API_SPORTS_KEY_NAMES, resolve_api_sports_key
except ImportError:
    from client import API_SPORTS_KEY_NAMES, resolve_api_sports_key


class ApiSportsClientTests(unittest.TestCase):
    def test_recognizes_legacy_key_name(self):
        with patch.dict(os.environ, {"API_SPORTS_MMA_KEY": "legacy-key"}, clear=True):
            key, variable_name = resolve_api_sports_key()
        self.assertEqual(key, "legacy-key")
        self.assertEqual(variable_name, "API_SPORTS_MMA_KEY")

    def test_recognizes_alternate_key_name(self):
        with patch.dict(os.environ, {"APISPORTS_KEY": "alternate-key"}, clear=True):
            key, variable_name = resolve_api_sports_key()
        self.assertEqual(key, "alternate-key")
        self.assertEqual(variable_name, "APISPORTS_KEY")

    def test_returns_none_without_supported_key(self):
        with patch.dict(os.environ, {}, clear=True):
            key, variable_name = resolve_api_sports_key()
        self.assertIsNone(key)
        self.assertIsNone(variable_name)
        self.assertIn("API_SPORTS_KEY", API_SPORTS_KEY_NAMES)


if __name__ == "__main__":
    unittest.main()
