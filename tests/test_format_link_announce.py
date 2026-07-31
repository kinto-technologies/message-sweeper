# -*- coding: utf-8 -*-
"""Tests for format_link_announce in shared.fetcher."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon"))

sys.modules.setdefault("logHandler", types.ModuleType("logHandler"))
sys.modules["logHandler"].log = types.SimpleNamespace(
    info=lambda *a, **kw: None,
    debugWarning=lambda *a, **kw: None,
)

from shared.fetcher import format_link_announce


TEMPLATES = {
    "title": "Link: {title}",
    "label": "Link: Title unavailable",
    "host": "Link: {host} (Title unavailable)",
    "url": "Link: {url}",
}


class TestFormatLinkAnnounceSuccess(unittest.TestCase):
    """A non-empty title is always rendered with the title template."""

    def test_title_mode_silent_with_title_still_renders(self):
        # When title exists, mode does not matter — caller already chose to announce.
        result = format_link_announce("https://example.com/", "Hello", "silent", TEMPLATES)
        self.assertEqual(result, "Link: Hello")

    def test_title_mode_host_with_title(self):
        result = format_link_announce("https://example.com/page", "Hello", "host", TEMPLATES)
        self.assertEqual(result, "Link: Hello")


class TestFormatLinkAnnounceFailureSilent(unittest.TestCase):
    def test_none_title_silent_returns_none(self):
        self.assertIsNone(format_link_announce("https://example.com/", None, "silent", TEMPLATES))

    def test_empty_title_silent_returns_none(self):
        self.assertIsNone(format_link_announce("https://example.com/", "", "silent", TEMPLATES))


class TestFormatLinkAnnounceFailureLabel(unittest.TestCase):
    def test_none_title_label_returns_label(self):
        self.assertEqual(
            format_link_announce("https://example.com/", None, "label", TEMPLATES),
            "Link: Title unavailable",
        )


class TestFormatLinkAnnounceFailureHost(unittest.TestCase):
    def test_none_title_host_uses_hostname(self):
        self.assertEqual(
            format_link_announce("https://example.com/page?q=1", None, "host", TEMPLATES),
            "Link: example.com (Title unavailable)",
        )

    def test_ipv4_hostname_used(self):
        self.assertEqual(
            format_link_announce("http://192.168.1.1/admin", None, "host", TEMPLATES),
            "Link: 192.168.1.1 (Title unavailable)",
        )

    def test_ipv6_hostname_used(self):
        # urlparse returns the IPv6 host without brackets.
        self.assertEqual(
            format_link_announce("http://[2001:db8::1]/", None, "host", TEMPLATES),
            "Link: 2001:db8::1 (Title unavailable)",
        )

    def test_port_stripped_from_host(self):
        self.assertEqual(
            format_link_announce("http://example.com:8080/", None, "host", TEMPLATES),
            "Link: example.com (Title unavailable)",
        )

    def test_malformed_url_falls_back_to_label(self):
        # No parseable host → fall back to label.
        self.assertEqual(
            format_link_announce("not-a-url", None, "host", TEMPLATES),
            "Link: Title unavailable",
        )


class TestFormatLinkAnnounceFailureUrl(unittest.TestCase):
    def test_none_title_url_uses_full_url(self):
        url = "https://example.com/long/path?q=1&r=2"
        self.assertEqual(
            format_link_announce(url, None, "url", TEMPLATES),
            f"Link: {url}",
        )


class TestFormatLinkAnnounceUnknownMode(unittest.TestCase):
    def test_unknown_mode_defaults_to_silent(self):
        # Defensive: unknown mode strings should not blow up.
        self.assertIsNone(
            format_link_announce("https://example.com/", None, "bogus", TEMPLATES)
        )


class TestFormatLinkAnnounceShortener(unittest.TestCase):
    """t.co (Twitter URL shortener) is announced as silent on title-fetch failure
    regardless of mode — these URLs carry no user-meaningful content."""

    def test_tco_silent_in_host_mode_when_title_missing(self):
        self.assertIsNone(
            format_link_announce("https://t.co/abc123", None, "host", TEMPLATES)
        )

    def test_tco_silent_in_label_mode_when_title_missing(self):
        self.assertIsNone(
            format_link_announce("https://t.co/abc123", None, "label", TEMPLATES)
        )

    def test_tco_silent_in_url_mode_when_title_missing(self):
        self.assertIsNone(
            format_link_announce("https://t.co/abc123", None, "url", TEMPLATES)
        )

    def test_tco_silent_with_empty_title(self):
        self.assertIsNone(
            format_link_announce("https://t.co/abc123", "", "host", TEMPLATES)
        )

    def test_tco_with_title_still_renders(self):
        # If t.co somehow returns a real title, we still announce it.
        self.assertEqual(
            format_link_announce("https://t.co/abc123", "Real Page", "host", TEMPLATES),
            "Link: Real Page",
        )

    def test_other_host_not_silenced_in_host_mode(self):
        # example.com — not a known shortener — still gets the host fallback.
        self.assertEqual(
            format_link_announce("https://example.com/", None, "host", TEMPLATES),
            "Link: example.com (Title unavailable)",
        )

    def test_tco_case_insensitive(self):
        # URLs are case-insensitive for hostnames — T.CO should also be silenced.
        self.assertIsNone(
            format_link_announce("https://T.CO/abc", None, "host", TEMPLATES)
        )


if __name__ == "__main__":
    unittest.main()
