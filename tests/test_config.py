# tests/test_config.py
# -*- coding: utf-8 -*-
"""Tests for shared.config settings module."""
import sys
import os
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon'))

# Mock NVDA's config module
_mock_config = types.ModuleType("config")
_mock_config_data = {}

class _MockConfigDict(dict):
    """Simulates config.conf with spec registration."""
    def __init__(self):
        super().__init__()
        self.spec = {}
    def __getitem__(self, key):
        if key not in self:
            super().__setitem__(key, dict(self.spec.get(key, {})))
        return super().__getitem__(key)

_mock_conf = _MockConfigDict()
_mock_config.conf = _mock_conf
sys.modules["config"] = _mock_config

from shared.config import (
    get_config, set_config, DEFAULTS,
    CONF_SECTION,
    CONF_KEY_EMOJI_THRESHOLD, CONF_KEY_SUMMARY_POSITION,
    CONF_KEY_TOGGLE_SOUND,
)


class TestConfigDefaults(unittest.TestCase):
    def setUp(self):
        # Reset config before each test
        if CONF_SECTION in _mock_conf:
            del _mock_conf[CONF_SECTION]

    def test_defaults_exist(self):
        self.assertIn("emoji_threshold", DEFAULTS)
        self.assertIn("summary_position", DEFAULTS)

    def test_default_values(self):
        self.assertEqual(DEFAULTS["emoji_threshold"], 3)
        self.assertEqual(DEFAULTS["summary_position"], "after")

    def test_get_config_returns_defaults(self):
        self.assertEqual(get_config(CONF_KEY_EMOJI_THRESHOLD), 3)
        self.assertEqual(get_config(CONF_KEY_SUMMARY_POSITION), "after")

    def test_set_and_get_config(self):
        set_config(CONF_KEY_EMOJI_THRESHOLD, 10)
        self.assertEqual(get_config(CONF_KEY_EMOJI_THRESHOLD), 10)

    def test_set_summary_position_off(self):
        set_config(CONF_KEY_SUMMARY_POSITION, "off")
        self.assertEqual(get_config(CONF_KEY_SUMMARY_POSITION), "off")

    def test_toggle_sound_default(self):
        self.assertIn(CONF_KEY_TOGGLE_SOUND, DEFAULTS)
        self.assertTrue(DEFAULTS[CONF_KEY_TOGGLE_SOUND])

    def test_get_toggle_sound_returns_default(self):
        self.assertTrue(get_config(CONF_KEY_TOGGLE_SOUND))

    def test_set_toggle_sound_false(self):
        set_config(CONF_KEY_TOGGLE_SOUND, False)
        self.assertFalse(get_config(CONF_KEY_TOGGLE_SOUND))

    def test_link_failure_announce_default(self):
        from shared.config import CONF_KEY_LINK_FAILURE_ANNOUNCE
        self.assertIn(CONF_KEY_LINK_FAILURE_ANNOUNCE, DEFAULTS)
        self.assertEqual(DEFAULTS[CONF_KEY_LINK_FAILURE_ANNOUNCE], "host")

    def test_get_link_failure_announce_returns_default(self):
        from shared.config import CONF_KEY_LINK_FAILURE_ANNOUNCE
        self.assertEqual(get_config(CONF_KEY_LINK_FAILURE_ANNOUNCE), "host")

    def test_set_link_failure_announce_silent(self):
        from shared.config import CONF_KEY_LINK_FAILURE_ANNOUNCE
        set_config(CONF_KEY_LINK_FAILURE_ANNOUNCE, "silent")
        self.assertEqual(get_config(CONF_KEY_LINK_FAILURE_ANNOUNCE), "silent")


if __name__ == "__main__":
    unittest.main()
