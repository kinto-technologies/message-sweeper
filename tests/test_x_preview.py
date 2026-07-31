# -*- coding: utf-8 -*-
"""Tests for _extract_x_preview_text_from_tree."""
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

from slack import _extract_x_preview_text_from_tree


class MockObj:
    """Minimal mock of an NVDA accessibility object."""
    def __init__(self, role, name):
        self.role = role
        self.name = name
        self.firstChild = None
        self.next = None


def _chain(*objs):
    """Link objects as siblings (next pointer chain). Returns first."""
    for i in range(len(objs) - 1):
        objs[i].next = objs[i + 1]
    return objs[0]


def _make_x_preview_tree():
    """Build mock tree matching the real Slack X preview card structure."""
    root = MockObj("LISTITEM", "message")
    msg = MockObj("GROUP", "メッセージ")
    root.firstChild = msg

    ts        = MockObj("LINK",    "昨日 21:52:43")
    sender    = MockObj("BUTTON",  "サンプル太郎/Sample Taro")
    url_link  = MockObj("LINK",    "https://x.com/example_qa/status/1234567890000000001?s=46")
    comment   = MockObj(None,      "気になる記事 (あとで眺める)")
    author1   = MockObj("LINK",    "サンプル花子 (@example_qa) on X")
    author2   = MockObj("LINK",    "サンプル花子 (@example_qa) on X")
    tweet1    = MockObj(None,      "新しいツールを導入して、開発の生産性が大きく向上しました。")
    tweet2    = MockObj(None,      "以前は手作業だった工程を、自動化することで大幅に時間を短縮できました。")
    x_img     = MockObj("GRAPHIC", "X (formerly Twitter)")
    x_txt     = MockObj(None,      "X (formerly Twitter)")
    reactions = MockObj("GROUP",   "絵文字リアクション")

    msg.firstChild = _chain(ts, sender, url_link, comment, author1, author2,
                            tweet1, tweet2, x_img, x_txt, reactions)
    return root


class TestExtractXPreviewText(unittest.TestCase):
    def test_returns_tweet_body(self):
        root = _make_x_preview_tree()
        result = _extract_x_preview_text_from_tree(root)
        self.assertIn("新しいツールを導入して", result)
        self.assertIn("以前は手作業だった", result)

    def test_does_not_include_sender_comment(self):
        root = _make_x_preview_tree()
        result = _extract_x_preview_text_from_tree(root)
        self.assertNotIn("気になる記事 (あとで眺める)", result)

    def test_does_not_include_x_label(self):
        root = _make_x_preview_tree()
        result = _extract_x_preview_text_from_tree(root)
        self.assertNotIn("X (formerly Twitter)", result)

    def test_returns_none_when_no_author_link(self):
        root = MockObj("LISTITEM", "message")
        msg = MockObj("GROUP", "メッセージ")
        root.firstChild = msg
        msg.firstChild = MockObj("LINK", "https://x.com/user/status/123")
        result = _extract_x_preview_text_from_tree(root)
        self.assertIsNone(result)

    def test_returns_none_when_empty_tree(self):
        root = MockObj("LISTITEM", "message")
        result = _extract_x_preview_text_from_tree(root)
        self.assertIsNone(result)

    def test_collects_single_paragraph(self):
        root = MockObj("LISTITEM", "message")
        msg = MockObj("GROUP", "メッセージ")
        root.firstChild = msg

        author = MockObj("LINK",    "User (@handle) on X")
        tweet  = MockObj(None,      "これは1行のツイートです。")
        end    = MockObj("GRAPHIC", "X (formerly Twitter)")

        msg.firstChild = _chain(author, tweet, end)
        result = _extract_x_preview_text_from_tree(root)
        self.assertEqual(result, "これは1行のツイートです。")

    def test_does_not_collect_text_children_of_on_x_link(self):
        """Text children inside an 'on X' LINK must not bleed into the collected tweet body."""
        root = MockObj("LISTITEM", "message")
        msg = MockObj("GROUP", "メッセージ")
        root.firstChild = msg

        author = MockObj("LINK", "サンプル花子 (@example_ai) on X")
        # In NVDA's UIA tree, link elements can have a TEXT child with the link's own name.
        author.firstChild = MockObj(None, "サンプル花子 (@example_ai) on X")

        tweet = MockObj(None, "ツイート本文テキストです。")
        end   = MockObj("GRAPHIC", "X (formerly Twitter)")

        msg.firstChild = _chain(author, tweet, end)
        result = _extract_x_preview_text_from_tree(root)
        self.assertEqual(result, "ツイート本文テキストです。")
        self.assertNotIn("サンプル花子", result)

    def test_strips_slack_japanese_attribution_wrapper(self):
        """When Slack returns the whole card as a single node with attribution wrapper,
        strip 'Xユーザーの{name}さん: 「{tweet} / X」' to leave just the tweet text."""
        root = MockObj("LISTITEM", "message")
        msg = MockObj("GROUP", "メッセージ")
        root.firstChild = msg

        author = MockObj("LINK", "サンプルテック (@example_tech) on X")
        # Slack sometimes returns the entire tweet card as a single text node.
        card = MockObj(
            None,
            "Xユーザーのサンプルテックさん: 「新機能の設定がファイルで管理できるようになりました！ / X」"
        )
        end = MockObj("GRAPHIC", "X (formerly Twitter)")

        msg.firstChild = _chain(author, card, end)
        result = _extract_x_preview_text_from_tree(root)
        self.assertEqual(result, "新機能の設定がファイルで管理できるようになりました！")
        self.assertNotIn("Xユーザーの", result)
        self.assertNotIn("/ X", result)
        self.assertNotIn("「", result)
        self.assertNotIn("」", result)


class TestExtractXPreviewRequiresEndMarker(unittest.TestCase):
    """終了マーカーが見つからないまま走査が終わったら None を返す。

    Slack 4.51.180 では X カードの "X (formerly Twitter)" 要素がメッセージの
    subtree に現れない。終端が分からないと収集はカードの外まで走り、
    リアクションやアクションメニューを本文として返してしまう
    （実機ログ 2026-07-28 で確認）。境界が確定できない収集結果は信頼できない。
    """

    def test_returns_none_when_end_marker_missing(self):
        root = MockObj("LISTITEM", "message")
        msg = MockObj("GROUP", "メッセージ")
        root.firstChild = msg

        author = MockObj("LINK", "サンプル花子 (@example_qa) on X")
        # 本文もマーカーも無く、後続はメッセージ操作メニューだけ。
        menu1 = MockObj(None, "その他")
        menu2 = MockObj(None, "その他のアクション")
        menu3 = MockObj(None, "リアクションを追加...")
        menu4 = MockObj(None, "ブックマークする")

        msg.firstChild = _chain(author, menu1, menu2, menu3, menu4)
        self.assertIsNone(_extract_x_preview_text_from_tree(root))

    def test_returns_none_when_end_marker_missing_even_if_text_collected(self):
        """本文らしきテキストが取れていても、終端未確定なら採用しない。

        どこまでがカードでどこからが UI なのか区別できないため、
        oEmbed 経路に委ねる方が確実。
        """
        root = MockObj("LISTITEM", "message")
        msg = MockObj("GROUP", "メッセージ")
        root.firstChild = msg

        author = MockObj("LINK", "サンプル花子 (@example_qa) on X")
        tweet = MockObj(None, "ツイート本文らしきテキスト。")
        junk = MockObj(None, "29 件の絵文字リアクション、e 絵文字 でリアクションする")

        msg.firstChild = _chain(author, tweet, junk)
        self.assertIsNone(_extract_x_preview_text_from_tree(root))


class TestStripXBrandingSuffix(unittest.TestCase):
    """"/ X" 接尾辞の除去。正規表現をやめた際に境界を固定するため。"""

    def setUp(self):
        from slack import _strip_x_branding_suffix
        self.strip = _strip_x_branding_suffix

    def test_strips_suffix_with_closing_bracket(self):
        self.assertEqual(self.strip("ツイート本文 / X」"), "ツイート本文")

    def test_strips_suffix_without_closing_bracket(self):
        self.assertEqual(self.strip("ツイート本文 / X"), "ツイート本文")

    def test_keeps_body_ending_in_bare_x(self):
        """スラッシュを伴わない末尾の X は本文の一部なので消さない。"""
        self.assertEqual(self.strip("好きな記号は X"), "好きな記号は X")

    def test_keeps_body_without_suffix(self):
        self.assertEqual(self.strip("ふつうのツイート本文です。"), "ふつうのツイート本文です。")

    def test_tolerates_extra_whitespace_around_suffix(self):
        self.assertEqual(self.strip("ツイート本文   /   X   "), "ツイート本文")


class TestXCardBodyPattern(unittest.TestCase):
    """Tests for _X_CARD_BODY_PATTERN stripping tweet cards embedded in obj.name."""

    def setUp(self):
        from slack import _X_CARD_BODY_PATTERN
        self.pattern = _X_CARD_BODY_PATTERN

    def _strip(self, text):
        return self.pattern.sub('', text).strip()

    def test_strips_mid_body_tweet_card(self):
        body = "ちょっとテスト Xユーザーのサンプルテックさん: 「新機能の設定がファイルで管理できるようになりました！ / X」"
        self.assertEqual(self._strip(body), "ちょっとテスト")

    def test_strips_tweet_card_at_start(self):
        body = "Xユーザーのサンプルテックさん: 「tweet text🚀 / X」"
        self.assertEqual(self._strip(body), "")

    def test_leaves_normal_body_unchanged(self):
        body = "こんにちは！　これは普通のメッセージです。"
        self.assertEqual(self._strip(body), body)

    def test_leaves_x_url_only_body_unchanged(self):
        body = "ちょっとテスト https://x.com/example_tech/status/123"
        self.assertEqual(self._strip(body), body)


if __name__ == "__main__":
    unittest.main()
