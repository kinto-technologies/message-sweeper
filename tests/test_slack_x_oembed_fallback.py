# -*- coding: utf-8 -*-
"""Slack 側で X URL のツリー抽出が失敗したときに oEmbed にフォールバックすることのテスト。

実機ログで確認した「Slack が unfurl カードを描画しない」状況
（同 URL を 1 時間以内に再投稿された場合や、Slack が X の取得に失敗した場合など）
で、Sweeper が tweet 本文を読めるようにする。
"""
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

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

from slack import AppModule
from shared.fetcher import TitleCache


class TestFetchUrlTitleDispatch(unittest.TestCase):
    """_fetch_url_title は X URL なら oEmbed、それ以外なら fetch_page_title に振り分ける。"""

    def setUp(self):
        self.am = AppModule()

    def test_x_url_with_status_uses_oembed(self):
        with patch("slack.fetch_x_post_via_oembed", return_value="ツイート本文") as oe, \
             patch("slack.fetch_page_title") as ft:
            result = self.am._fetch_url_title(
                "https://x.com/user/status/12345"
            )
        oe.assert_called_once_with("https://x.com/user/status/12345")
        ft.assert_not_called()
        self.assertEqual(result, "ツイート本文")

    def test_twitter_com_url_with_status_uses_oembed(self):
        with patch("slack.fetch_x_post_via_oembed", return_value="tweet body") as oe, \
             patch("slack.fetch_page_title") as ft:
            self.am._fetch_url_title(
                "https://twitter.com/user/status/67890"
            )
        oe.assert_called_once_with("https://twitter.com/user/status/67890")
        ft.assert_not_called()

    def test_non_x_url_uses_fetch_page_title(self):
        with patch("slack.fetch_x_post_via_oembed") as oe, \
             patch("slack.fetch_page_title", return_value="ページタイトル") as ft:
            result = self.am._fetch_url_title("https://example.com/page")
        ft.assert_called_once_with("https://example.com/page")
        oe.assert_not_called()
        self.assertEqual(result, "ページタイトル")

    def test_x_profile_url_without_status_uses_fetch_page_title(self):
        # TWITTER_PATTERN は /status/数字 を必須にしているのでプロフィールURLはマッチしない
        with patch("slack.fetch_x_post_via_oembed") as oe, \
             patch("slack.fetch_page_title", return_value=None) as ft:
            self.am._fetch_url_title("https://x.com/user")
        ft.assert_called_once_with("https://x.com/user")
        oe.assert_not_called()


class TestFetchAndSpeakUsesDispatcher(unittest.TestCase):
    """_fetch_and_speak は urls_to_fetch の各 URL に _fetch_url_title を使う。"""

    def setUp(self):
        self.am = AppModule()
        self.am._title_cache = TitleCache()

    def test_x_url_in_urls_to_fetch_invokes_oembed(self):
        url = "https://x.com/example_news/status/1234567890000000003"
        urls_to_fetch = [url]
        url_title_map = {}
        parsed = {"urls": [url], "lang": "ja"}

        with patch("slack.fetch_x_post_via_oembed", return_value="oEmbed 本文") as oe, \
             patch("slack.fetch_page_title") as ft, \
             patch.object(self.am, "_announce_links_and_meta"), \
             patch("slack.queueHandler"):
            self.am._fetch_and_speak(urls_to_fetch, url_title_map, parsed, "immediate")

        oe.assert_called_once_with(url)
        ft.assert_not_called()
        self.assertEqual(url_title_map[url], "oEmbed 本文")
        # キャッシュにも反映されているはず
        self.assertEqual(self.am._title_cache.get(url), "oEmbed 本文")

    def test_non_x_url_in_urls_to_fetch_invokes_fetch_page_title(self):
        url = "https://example.com/article"
        urls_to_fetch = [url]
        url_title_map = {}
        parsed = {"urls": [url], "lang": "ja"}

        with patch("slack.fetch_x_post_via_oembed") as oe, \
             patch("slack.fetch_page_title", return_value="記事タイトル") as ft, \
             patch.object(self.am, "_announce_links_and_meta"), \
             patch("slack.queueHandler"):
            self.am._fetch_and_speak(urls_to_fetch, url_title_map, parsed, "immediate")

        ft.assert_called_once_with(url)
        oe.assert_not_called()
        self.assertEqual(url_title_map[url], "記事タイトル")


class TestXUrlStaysInFetchListWhenTreeExtractionFails(unittest.TestCase):
    """ツリー抽出が None を返した X URL は BG フェッチ対象として残る。"""

    def setUp(self):
        # クラス変数の _title_cache を毎テスト初期化
        AppModule._title_cache = TitleCache()
        self.am = AppModule()

    def _make_listitem_obj(self, name, position_level=1):
        obj = MagicMock()
        obj.role = "LISTITEM"
        obj.name = name
        obj.firstChild = None  # ツリー走査は何も拾わず None を返す
        obj.positionInfo = {"level": position_level}
        return obj

    def test_x_url_no_unfurl_card_triggers_oembed_fallback(self):
        """実際の投稿を模したケース: obj.name に URL は含まれるが unfurl カードが無い。"""
        name = (
            "サンプル太郎/さんぷる/pc2 : 気になる記事 "
            "https://x.com/example_news/status/1234567890000000003。"
            " 時刻 16:44。 1 個の絵文字リアクション、 24 件の返信、 1 件のリンク。"
        )
        obj = self._make_listitem_obj(name)

        # threading.Thread をその場で同期実行に置き換え
        def _inline_thread(target=None, args=(), daemon=None, **kw):
            t = MagicMock()
            t.start = lambda: target(*args)
            return t

        with patch("slack._is_sweeper_enabled", return_value=True), \
             patch("slack._extract_x_preview_text_from_tree", return_value=None), \
             patch("slack._find_unfurl_titles_in_tree", return_value=[]), \
             patch("slack.threading.Thread", side_effect=_inline_thread), \
             patch("slack.fetch_x_post_via_oembed", return_value="oEmbed で取得した本文") as oe, \
             patch("slack.fetch_page_title") as ft, \
             patch("slack.speech"), patch("slack.braille"), patch("slack.api"), \
             patch("slack.queueHandler"):
            self.am.event_gainFocus(obj, lambda: None)

        oe.assert_called_once_with(
            "https://x.com/example_news/status/1234567890000000003"
        )
        ft.assert_not_called()
        self.assertEqual(
            AppModule._title_cache.get(
                "https://x.com/example_news/status/1234567890000000003"
            ),
            "oEmbed で取得した本文",
        )

    def test_x_url_with_successful_tree_extraction_skips_network(self):
        """ツリー抽出が成功する場合は oEmbed も fetch も呼ばれない。"""
        name = (
            "サンプル太郎/さんぷる/pc2 : 気になる記事 "
            "https://x.com/example_news/status/1234567890000000003。"
            " 時刻 16:44。"
        )
        obj = self._make_listitem_obj(name)

        with patch("slack._is_sweeper_enabled", return_value=True), \
             patch(
                 "slack._extract_x_preview_text_from_tree",
                 return_value="ツリーから取れた本文",
             ), \
             patch("slack._find_unfurl_titles_in_tree", return_value=[]), \
             patch("slack.threading.Thread") as thread_mock, \
             patch.object(AppModule, "_announce_links_and_meta"), \
             patch("slack.fetch_x_post_via_oembed") as oe, \
             patch("slack.fetch_page_title") as ft, \
             patch("slack.speech"), patch("slack.braille"), patch("slack.api"), \
             patch("slack.queueHandler"):
            self.am.event_gainFocus(obj, lambda: None)

        oe.assert_not_called()
        ft.assert_not_called()
        thread_mock.assert_not_called()  # BG フェッチ起動も無し
        self.assertEqual(
            AppModule._title_cache.get(
                "https://x.com/example_news/status/1234567890000000003"
            ),
            "ツリーから取れた本文",
        )


class TestXUrlFallsBackWhenTreeTitleIsAuthorLink(unittest.TestCase):
    """ツリーに 'on X' 作者リンクだけがある場合も oEmbed に到達する。

    実機ログ 2026-07-28（Slack 4.51.180）で確認したケース。
    _find_unfurl_titles_in_tree はカードの作者リンク
    "... (@handle) on X" を拾うが、_extract_x_preview_text_from_tree は
    本文を取れず None を返す。この状態で作者リンク名をタイトルとして
    読み上げて早期 return すると、oEmbed 経路に永久に到達しない。
    """

    URL = "https://x.com/example_news/status/1234567890000000003"

    def setUp(self):
        AppModule._title_cache = TitleCache()
        self.am = AppModule()

    def _make_listitem_obj(self, name):
        obj = MagicMock()
        obj.role = "LISTITEM"
        obj.name = name
        obj.firstChild = None
        obj.positionInfo = {"level": 1}
        return obj

    def test_author_link_title_does_not_block_oembed_fallback(self):
        name = (
            "サンプル太郎/Sample Taro : " + self.URL + "。"
            " 時刻 20:17。 1 件のリンク、 1 件の添付ファイル。"
        )
        obj = self._make_listitem_obj(name)

        def _inline_thread(target=None, args=(), daemon=None, **kw):
            t = MagicMock()
            t.start = lambda: target(*args)
            return t

        with patch("slack._is_sweeper_enabled", return_value=True), \
             patch("slack._extract_x_preview_text_from_tree", return_value=None), \
             patch(
                 "slack._find_unfurl_titles_in_tree",
                 return_value=["サンプル花子 (@example_qa) on X"],
             ), \
             patch("slack.threading.Thread", side_effect=_inline_thread), \
             patch("slack.fetch_x_post_via_oembed", return_value="oEmbed 本文") as oe, \
             patch("slack.fetch_page_title") as ft, \
             patch("slack.speech"), patch("slack.braille"), patch("slack.api"), \
             patch("slack.queueHandler"):
            self.am.event_gainFocus(obj, lambda: None)

        oe.assert_called_once_with(self.URL)
        ft.assert_not_called()
        self.assertEqual(AppModule._title_cache.get(self.URL), "oEmbed 本文")


if __name__ == "__main__":
    unittest.main()
