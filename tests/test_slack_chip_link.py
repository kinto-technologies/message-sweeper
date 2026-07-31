# -*- coding: utf-8 -*-
"""Tests for Slack "link chip" recovery.

Slack renders some link messages with the link's accessible *name* set to a
schemeless / mid-truncated display URL (e.g. "example.com/topic/…/page?id=00")
while the real href lives in the LINK node's *value*. These tests cover:

- URL_DISPLAY_PATTERN telling schemeless URL displays apart from real titles
- parse_slack_message diverting such chips out of unfurl_titles
- _resolve_chip_link_hrefs recovering the full href from the accessibility tree
- the "open in new window" link being filtered out of announced titles
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon", "appModules"))

for mod_name in [
    "addonHandler", "appModuleHandler", "api", "braille", "nvwave",
    "speech", "ui", "controlTypes", "queueHandler", "logHandler",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

sys.modules["logHandler"].log = types.SimpleNamespace(
    info=lambda *a, **kw: None,
    debugWarning=lambda *a, **kw: None,
)
sys.modules["controlTypes"].Role = types.SimpleNamespace(
    LISTITEM="LISTITEM", LINK="LINK", GRAPHIC="GRAPHIC",
    BUTTON="BUTTON", GROUP="GROUP",
)

_mock_amh = sys.modules["appModuleHandler"]
_mock_amh.AppModule = type("AppModule", (), {})

_mock_addon = sys.modules["addonHandler"]
_mock_addon.initTranslation = lambda: None
_mock_addon.getCodeAddon = lambda: types.SimpleNamespace(
    path=os.path.join(os.path.dirname(__file__), "..")
)

import builtins
if "_" not in dir(builtins):
    builtins._ = lambda x: x

from shared.patterns import URL_DISPLAY_PATTERN, _UNFURL_FILTER_STRINGS
from slack import parse_slack_message, _resolve_chip_link_hrefs, _merge_chip_links


class MockObj:
    """Minimal mock of an NVDA accessibility object (with a value attr)."""
    def __init__(self, role, name, value=None):
        self.role = role
        self.name = name
        self.value = value
        self.firstChild = None
        self.next = None


def _chain(*objs):
    for i in range(len(objs) - 1):
        objs[i].next = objs[i + 1]
    return objs[0]


class TestUrlDisplayPattern(unittest.TestCase):
    def test_matches_schemeless_host_and_path(self):
        self.assertTrue(URL_DISPLAY_PATTERN.match("news.example.com/topic/1000000002?source=rss"))

    def test_matches_mid_truncated_display(self):
        self.assertTrue(URL_DISPLAY_PATTERN.match("sports.example.com/topic/…/page?id=00"))

    def test_matches_trailing_truncated_display(self):
        self.assertTrue(
            URL_DISPLAY_PATTERN.match(
                "alerts.example.com/region/jp/detail/1000000003?…"
            )
        )

    def test_matches_host_only(self):
        self.assertTrue(URL_DISPLAY_PATTERN.match("example.com/item/1000000004"))

    def test_does_not_match_real_title(self):
        self.assertFalse(
            URL_DISPLAY_PATTERN.match(
                "サンプルニュース - 見出しテキストの例 - ニュースサイト"
            )
        )

    def test_does_not_match_x_card(self):
        self.assertFalse(
            URL_DISPLAY_PATTERN.match("(1) XユーザーのExample Techさん: 「tweet / X」")
        )


class TestParseDivertsChipDisplays(unittest.TestCase):
    def test_chip_url_display_goes_to_chip_link_displays_not_titles(self):
        name = (
            "サンプル一郎/Sample Ichiro : "
            "[ sports.example.com/topic/…/page?id=00 (リンク)] サンプル太郎。 "
            "時刻 02:31。 2 個の絵文字リアクション、 1 件のリンク。"
        )
        result = parse_slack_message(name)
        self.assertIn("sports.example.com/topic/…/page?id=00", result["chip_link_displays"])
        self.assertNotIn("sports.example.com/topic/…/page?id=00", result["unfurl_titles"])

    def test_chip_display_removed_from_body(self):
        name = (
            "サンプル一郎/Sample Ichiro : "
            "[ sports.example.com/topic/…/page?id=00 (リンク)] サンプル太郎。 "
            "時刻 02:31。 1 件のリンク。"
        )
        result = parse_slack_message(name)
        self.assertNotIn("sports.example.com", result["body"])
        self.assertIn("サンプル太郎", result["body"])


class TestResolveChipLinkHrefs(unittest.TestCase):
    def _build_tree(self):
        """Mirror the real Slack tree: shallow chip LINK (name=display, value=href),
        a permalink timestamp LINK, and deeper title LINKs."""
        root = MockObj("LISTITEM", "message")
        ts = MockObj(
            "LINK", "今日 02:31:56 ",
            value="https://example.slack.com/archives/C0EXAMPLE03/p3333333333333333",
        )
        sender = MockObj("BUTTON", "サンプル一郎/Sample Ichiro")
        chip = MockObj(
            "LINK", "sports.example.com/topic/…/page?id=00",
            value="https://sports.example.com/topic/category/0000/item/1000000001/page?id=00",
        )
        title = MockObj(
            "LINK", "サンプルニュース - 見出しテキストの例 - ニュースサイト",
            value="https://sports.example.com/topic/category/0000/item/1000000001/page?id=00",
        )
        root.firstChild = _chain(ts, sender, chip, title)
        return root

    def test_resolves_display_to_full_href(self):
        root = self._build_tree()
        result = _resolve_chip_link_hrefs(root, ["sports.example.com/topic/…/page?id=00"])
        self.assertEqual(
            result.get("sports.example.com/topic/…/page?id=00"),
            "https://sports.example.com/topic/category/0000/item/1000000001/page?id=00",
        )

    def test_does_not_return_permalink_href(self):
        root = self._build_tree()
        result = _resolve_chip_link_hrefs(root, ["sports.example.com/topic/…/page?id=00"])
        for href in result.values():
            self.assertNotIn("slack.com/archives", href)

    def test_unresolved_display_absent_from_result(self):
        root = self._build_tree()
        result = _resolve_chip_link_hrefs(root, ["nonexistent.example.com/x"])
        self.assertNotIn("nonexistent.example.com/x", result)


class TestMergeChipLinks(unittest.TestCase):
    def test_resolved_href_added_to_urls(self):
        parsed = {"urls": [], "unfurl_titles": [],
                  "chip_link_displays": ["sports.example.com/topic/…/page?id=00"]}
        _merge_chip_links(parsed, {
            "sports.example.com/topic/…/page?id=00":
                "https://sports.example.com/topic/category/0000/item/1000000001/page?id=00",
        })
        self.assertEqual(
            parsed["urls"],
            ["https://sports.example.com/topic/category/0000/item/1000000001/page?id=00"],
        )
        self.assertEqual(parsed["unfurl_titles"], [])

    def test_unresolved_display_falls_back_to_title(self):
        parsed = {"urls": [], "unfurl_titles": [],
                  "chip_link_displays": ["sports.example.com/topic/…/page?id=00"]}
        _merge_chip_links(parsed, {})
        self.assertEqual(parsed["urls"], [])
        self.assertIn("sports.example.com/topic/…/page?id=00", parsed["unfurl_titles"])

    def test_does_not_duplicate_existing_url(self):
        href = "https://news.example.com/topic/1000000002?source=rss"
        parsed = {"urls": [href], "unfurl_titles": [],
                  "chip_link_displays": ["news.example.com/topic/1000000002?source=rss"]}
        _merge_chip_links(parsed, {"news.example.com/topic/1000000002?source=rss": href})
        self.assertEqual(parsed["urls"], [href])


class TestResolveChipLinkHrefsResilience(unittest.TestCase):
    """The tree walk touches live NVDA objects whose attribute access can raise
    or nest arbitrarily deep. It must degrade gracefully (return what it found,
    never propagate) rather than break focus announcement."""

    WANTED = "chip.example.com/x"
    HREF = "https://chip.example.com/x"

    def _chip(self):
        return MockObj("LINK", self.WANTED, value=self.HREF)

    def test_does_not_descend_beyond_max_depth(self):
        """A chip buried deeper than max_depth (10) is not resolved: the walk
        stops instead of recursing without bound."""
        root = MockObj("LISTITEM", "root")
        node = root
        for _ in range(12):  # nest well past max_depth=10
            child = MockObj("GROUP", "wrapper")
            node.firstChild = child
            node = child
        node.firstChild = self._chip()
        result = _resolve_chip_link_hrefs(root, [self.WANTED])
        self.assertNotIn(self.WANTED, result)

    def test_returns_gracefully_when_firstchild_raises(self):
        """A node whose firstChild access raises yields an empty result, no
        exception."""
        class RaisingFirstChild:
            role = "LISTITEM"
            name = "root"
            value = None
            next = None
            @property
            def firstChild(self):
                raise RuntimeError("tree detached")

        result = _resolve_chip_link_hrefs(RaisingFirstChild(), [self.WANTED])
        self.assertEqual(result, {})

    def test_skips_child_whose_role_raises(self):
        """A sibling whose role access raises is skipped; a later valid chip is
        still resolved."""
        class RaisingRole:
            name = ""
            value = None
            firstChild = None
            def __init__(self, nxt):
                self._next = nxt
            @property
            def role(self):
                raise RuntimeError("dead object")
            @property
            def next(self):
                return self._next

        root = MockObj("LISTITEM", "root")
        root.firstChild = RaisingRole(self._chip())
        result = _resolve_chip_link_hrefs(root, [self.WANTED])
        self.assertEqual(result.get(self.WANTED), self.HREF)

    def test_stops_when_next_raises_but_keeps_prior_find(self):
        """If advancing to the next sibling raises, the walk stops but keeps
        what it already resolved."""
        class RaisingNext:
            role = "LINK"
            firstChild = None
            def __init__(self, name, value):
                self.name = name
                self.value = value
            @property
            def next(self):
                raise RuntimeError("sibling gone")

        root = MockObj("LISTITEM", "root")
        root.firstChild = RaisingNext(self.WANTED, self.HREF)
        result = _resolve_chip_link_hrefs(root, [self.WANTED])
        self.assertEqual(result.get(self.WANTED), self.HREF)

    def test_link_role_falls_back_to_legacy_attribute(self):
        """On NVDA builds without controlTypes.Role.LINK, the resolver falls
        back to the legacy ROLE_LINK constant."""
        import controlTypes
        original_role = controlTypes.Role
        controlTypes.Role = types.SimpleNamespace()  # no LINK -> AttributeError
        controlTypes.ROLE_LINK = "LINK"
        try:
            root = MockObj("LISTITEM", "root")
            root.firstChild = self._chip()
            result = _resolve_chip_link_hrefs(root, [self.WANTED])
            self.assertEqual(result.get(self.WANTED), self.HREF)
        finally:
            controlTypes.Role = original_role
            del controlTypes.ROLE_LINK


class TestOpenInNewWindowFiltered(unittest.TestCase):
    def test_open_in_new_window_is_a_filter_string(self):
        self.assertIn("新しいウィンドウで開く", _UNFURL_FILTER_STRINGS)


if __name__ == "__main__":
    unittest.main()
