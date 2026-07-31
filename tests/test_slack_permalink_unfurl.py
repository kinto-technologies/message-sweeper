# -*- coding: utf-8 -*-
"""Tests for _extract_slack_permalink_unfurl_text."""
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
    LISTITEM="LISTITEM",
    LINK="LINK",
    GRAPHIC="GRAPHIC",
    BUTTON="BUTTON",
    GROUP="GROUP",
    GROUPING="GROUPING",
    SECTION="SECTION",
    STATICTEXT="STATICTEXT",
    BLOCKQUOTE="BLOCKQUOTE",
    TEXTFRAME="TEXTFRAME",
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

from slack import _extract_slack_permalink_unfurl_text


class MockObj:
    def __init__(self, role, name="", value=""):
        self.role = role
        self.name = name
        self.value = value
        self.firstChild = None
        self.next = None


def _chain(*objs):
    for i in range(len(objs) - 1):
        objs[i].next = objs[i + 1]
    return objs[0]


def _make_broken_case_tree():
    """Mock the bug-case tree (captured from an NVDA log).

    obj > SECTION (d=1) > SECTION (d=2) holding the message; one of the
    d=2 children is the embedded permalink LINK, followed by an empty
    SECTION spacer, then the card SECTION.
    """
    obj = MockObj("LISTITEM")

    permalink_url = "https://example.slack.com/archives/C0EXAMPLE01/p1111111111111111"
    permalink_link = MockObj("LINK", name=permalink_url, value=permalink_url)
    permalink_link.firstChild = MockObj("STATICTEXT", name=permalink_url)

    spacer = MockObj("SECTION")  # firstChild stays None -> empty spacer

    # --- Card SECTION (d=2 in the dump) ---
    card = MockObj("SECTION")

    # d=3 SECTION > BUTTON sender > TEXTFRAME > STATICTEXT
    sender_btn = MockObj("BUTTON", name="サンプル太郎/Sample Taro")
    tf = MockObj("TEXTFRAME")
    tf.firstChild = MockObj("STATICTEXT", name="サンプル太郎/Sample Taro")
    sender_btn.firstChild = tf
    sender_sec = MockObj("SECTION")
    sender_sec.firstChild = sender_btn

    # d=3 SECTION > {mention LINKs, body STATICTEXT}
    mention1 = MockObj("LINK", name="@サンプル花子/Sample Hanako")
    mention1.firstChild = MockObj("STATICTEXT", name="@サンプル花子/Sample Hanako")
    mention2 = MockObj("LINK", name="@サンプル次郎/Sample Jiro")
    mention2.firstChild = MockObj("STATICTEXT", name="@サンプル次郎/Sample Jiro")
    mention3 = MockObj("LINK", name="@サンプル三郎/Sample Saburo")
    mention3.firstChild = MockObj("STATICTEXT", name="@サンプル三郎/Sample Saburo")
    body_line = MockObj("STATICTEXT", name="本日は晴天なり")
    body_sec = MockObj("SECTION")
    body_sec.firstChild = _chain(mention1, mention2, mention3, body_line)

    # d=3 BLOCKQUOTE > STATICTEXT
    quote_text = MockObj("STATICTEXT", name="吾輩は猫である")
    quote = MockObj("BLOCKQUOTE")
    quote.firstChild = quote_text

    # d=3 SECTION > STATICTEXT (continuation)
    cont_text = MockObj("STATICTEXT", name="名前はまだ無い")
    cont_sec = MockObj("SECTION")
    cont_sec.firstChild = cont_text

    # d=3 SECTION > footer
    footer_marker = MockObj("STATICTEXT", name="プライベートの会話から")
    footer_channel = MockObj("SECTION")  # empty channel
    footer_pipe = MockObj("STATICTEXT", name=" | ")
    footer_time = MockObj("STATICTEXT", name="今日の08:52")
    footer_sec = MockObj("SECTION")
    footer_sec.firstChild = _chain(footer_marker, footer_channel, footer_pipe, footer_time)

    card.firstChild = _chain(sender_sec, body_sec, quote, cont_sec, footer_sec)

    # Comment text above the card (the focused user's own writing) — sibling.
    user_comment_url = MockObj("LINK", name="@team", value="https://example.slack.com/admin/user_groups")
    user_comment_url.firstChild = MockObj("STATICTEXT", name="@team")
    user_comment_text = MockObj("STATICTEXT", name="本日は晴天なり。")

    # d=2 children of the outer SECTION: [user_comment_url, user_comment_text, permalink_link, spacer, card]
    outer = MockObj("SECTION")
    outer.firstChild = _chain(user_comment_url, user_comment_text, permalink_link, spacer, card)

    top = MockObj("SECTION")
    top.firstChild = outer
    obj.firstChild = top
    return obj, permalink_url


def _make_broken_case_tree_en():
    """Mock the bug-case tree under English Slack UI (captured from an NVDA log).

    Differences from JA UI:
    - Card container role is GROUPING (not SECTION).
    - No empty-SECTION spacer between the permalink LINK and the card.
    - Sender wrapper is STATICTEXT '' > STATICTEXT 'name'
      (instead of TEXTFRAME > STATICTEXT 'name').
    - Footer marker is 'From a private conversation'.
    - "Show more" button name is English.
    """
    obj = MockObj("LISTITEM")

    permalink_url = "https://example.slack.com/archives/C0EXAMPLE01/p1111111111111111"
    permalink_link = MockObj("LINK", name=permalink_url, value=permalink_url)
    permalink_link.firstChild = MockObj("STATICTEXT", name=permalink_url)

    # --- Card GROUPING (immediate next sibling, no spacer) ---
    card = MockObj("GROUPING")

    # Sender section: GROUPING > BUTTON > STATICTEXT '' > STATICTEXT 'name'
    inner_static = MockObj("STATICTEXT", name="")
    inner_static.firstChild = MockObj("STATICTEXT", name="サンプル太郎/Sample Taro")
    sender_btn = MockObj("BUTTON", name="サンプル太郎/Sample Taro")
    sender_btn.firstChild = inner_static
    sender_sec = MockObj("GROUPING")
    sender_sec.firstChild = sender_btn

    # Body section with mentions + first body line
    mention1 = MockObj("LINK", name="@サンプル花子/Sample Hanako")
    mention1.firstChild = MockObj("STATICTEXT", name="@サンプル花子/Sample Hanako")
    mention2 = MockObj("LINK", name="@サンプル次郎/Sample Jiro")
    mention2.firstChild = MockObj("STATICTEXT", name="@サンプル次郎/Sample Jiro")
    mention3 = MockObj("LINK", name="@サンプル三郎/Sample Saburo")
    mention3.firstChild = MockObj("STATICTEXT", name="@サンプル三郎/Sample Saburo")
    body_line = MockObj("STATICTEXT", name="本日は晴天なり")
    body_sec = MockObj("GROUPING")
    body_sec.firstChild = _chain(mention1, mention2, mention3, body_line)

    # Quote (BLOCKQUOTE in JA, GROUPING in EN according to dump)
    quote_text = MockObj("STATICTEXT", name="吾輩は猫である")
    quote = MockObj("GROUPING")
    quote.firstChild = quote_text

    # Continuation
    cont_text = MockObj("STATICTEXT", name="名前はまだ無い")
    cont_sec = MockObj("GROUPING")
    cont_sec.firstChild = cont_text

    # Footer (English marker)
    footer_marker = MockObj("STATICTEXT", name="From a private conversation")
    footer_channel = MockObj("GROUPING")
    footer_pipe = MockObj("STATICTEXT", name=" | ")
    footer_time = MockObj("STATICTEXT", name="Today at 8:52 AM")
    footer_sec = MockObj("GROUPING")
    footer_sec.firstChild = _chain(footer_marker, footer_channel, footer_pipe, footer_time)

    card.firstChild = _chain(sender_sec, body_sec, quote, cont_sec, footer_sec)

    # Outer wrapper holding [permalink_link, card] as direct siblings (no spacer in EN UI).
    outer = MockObj("GROUPING")
    outer.firstChild = _chain(permalink_link, card)

    obj.firstChild = outer
    return obj, permalink_url


def _make_own_permalink_tree():
    """Tree containing only the listitem's own permalink LINK (name is a
    timestamp string, not the URL itself). Should NOT trigger extraction."""
    obj = MockObj("LISTITEM")
    # Slack uses a timestamp string as the LINK name for the listitem's
    # own permalink — name does not start with 'http'.
    own_link = MockObj(
        "LINK", name="今日 09:12:32 ",
        value="https://example.slack.com/archives/C0EXAMPLE02/p2222222222222222",
    )
    own_link.firstChild = MockObj("STATICTEXT", name="09:12")

    body_text = MockObj("STATICTEXT", name="これは本文です。")

    outer = MockObj("SECTION")
    outer.firstChild = _chain(own_link, body_text)
    top = MockObj("SECTION")
    top.firstChild = outer
    obj.firstChild = top
    return obj


def _make_no_permalink_tree():
    """Tree without any Slack permalink — should return empty dict."""
    obj = MockObj("LISTITEM")
    body_text = MockObj("STATICTEXT", name="ただのメッセージ。")
    outer = MockObj("SECTION")
    outer.firstChild = body_text
    top = MockObj("SECTION")
    top.firstChild = outer
    obj.firstChild = top
    return obj


class TestExtractSlackPermalinkUnfurlText(unittest.TestCase):
    def setUp(self):
        # Other test files (e.g. test_x_preview.py) overwrite controlTypes.Role
        # with a smaller SimpleNamespace at import time. Re-install our roles
        # before each test so order-of-discovery doesn't matter.
        sys.modules["controlTypes"].Role = types.SimpleNamespace(
            LISTITEM="LISTITEM",
            LINK="LINK",
            GRAPHIC="GRAPHIC",
            BUTTON="BUTTON",
            GROUP="GROUP",
            GROUPING="GROUPING",
            SECTION="SECTION",
            STATICTEXT="STATICTEXT",
            BLOCKQUOTE="BLOCKQUOTE",
            TEXTFRAME="TEXTFRAME",
        )

    def test_extracts_sender_time_body_from_broken_case(self):
        obj, url = _make_broken_case_tree()
        result = _extract_slack_permalink_unfurl_text(obj)
        self.assertIn(url, result)
        info = result[url]
        self.assertEqual(info["sender"], "サンプル太郎/Sample Taro")
        self.assertEqual(info["time"], "今日の08:52")
        self.assertIn("本日は晴天なり", info["body"])
        self.assertIn("吾輩は猫である", info["body"])
        self.assertIn("名前はまだ無い", info["body"])

    def test_body_includes_mentions_in_card(self):
        obj, url = _make_broken_case_tree()
        result = _extract_slack_permalink_unfurl_text(obj)
        body = result[url]["body"]
        self.assertIn("@サンプル花子/Sample Hanako", body)
        self.assertIn("@サンプル次郎/Sample Jiro", body)
        self.assertIn("@サンプル三郎/Sample Saburo", body)

    def test_body_excludes_footer_marker_and_separator(self):
        obj, url = _make_broken_case_tree()
        result = _extract_slack_permalink_unfurl_text(obj)
        body = result[url]["body"]
        self.assertNotIn("プライベートの会話から", body)
        self.assertNotIn("|", body)

    def test_own_permalink_is_ignored(self):
        obj = _make_own_permalink_tree()
        result = _extract_slack_permalink_unfurl_text(obj)
        self.assertEqual(result, {})

    def test_no_permalink_returns_empty(self):
        obj = _make_no_permalink_tree()
        result = _extract_slack_permalink_unfurl_text(obj)
        self.assertEqual(result, {})

    # --- English UI tests ---

    def test_extracts_sender_time_body_from_broken_case_en(self):
        obj, url = _make_broken_case_tree_en()
        result = _extract_slack_permalink_unfurl_text(obj)
        self.assertIn(url, result)
        info = result[url]
        self.assertEqual(info["sender"], "サンプル太郎/Sample Taro")
        self.assertEqual(info["time"], "Today at 8:52 AM")
        self.assertIn("本日は晴天なり", info["body"])
        self.assertIn("吾輩は猫である", info["body"])

    def test_en_body_excludes_footer_marker_and_separator(self):
        obj, url = _make_broken_case_tree_en()
        result = _extract_slack_permalink_unfurl_text(obj)
        body = result[url]["body"]
        self.assertNotIn("From a private conversation", body)
        self.assertNotIn("|", body)

    def test_en_body_includes_mentions(self):
        obj, url = _make_broken_case_tree_en()
        result = _extract_slack_permalink_unfurl_text(obj)
        body = result[url]["body"]
        self.assertIn("@サンプル花子/Sample Hanako", body)
        self.assertIn("@サンプル次郎/Sample Jiro", body)
        self.assertIn("@サンプル三郎/Sample Saburo", body)

    def test_en_sender_extracted_through_nested_empty_statictext(self):
        """English Slack wraps the sender in STATICTEXT '' > STATICTEXT 'name'.
        The collector must recurse into the empty wrapper to find the name."""
        obj, url = _make_broken_case_tree_en()
        result = _extract_slack_permalink_unfurl_text(obj)
        # Sender comes out as the first STATICTEXT (the inner one) — not "".
        self.assertEqual(result[url]["sender"], "サンプル太郎/Sample Taro")


if __name__ == "__main__":
    unittest.main()
