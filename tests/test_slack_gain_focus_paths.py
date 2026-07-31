# -*- coding: utf-8 -*-
"""event_gainFocus の各分岐の振る舞いを固定する characterization テスト。

event_gainFocus は分岐が多く未カバー行が多い。リファクタで読み上げ内容が
変わっていないことを確認するための安全網として、各経路が「何を読み上げるか」
「ネットワークフェッチを起動するか」を固定する。

fixture は架空データ。実在の人名・URL・投稿本文は含まない。
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
    warning=lambda *a, **kw: None,
)
sys.modules["controlTypes"].Role = types.SimpleNamespace(
    LISTITEM="LISTITEM",
    LINK="LINK",
    GRAPHIC="GRAPHIC",
    BUTTON="BUTTON",
    GROUP="GROUP",
    SECTION="SECTION",
    GROUPING="GROUPING",
    STATICTEXT="STATICTEXT",
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


class _GainFocusHarness(unittest.TestCase):
    """event_gainFocus を呼び、読み上げ内容とフェッチ起動を観測する土台。"""

    def setUp(self):
        AppModule._title_cache = TitleCache()
        self.am = AppModule()

    def _listitem(self, name):
        obj = MagicMock()
        obj.role = "LISTITEM"
        obj.name = name
        obj.firstChild = None
        obj.positionInfo = {"level": 1}
        return obj

    def _run(self, name, tree_titles=None, x_preview=None):
        """event_gainFocus を実行し (spoken_messages, thread_started) を返す。"""
        obj = self._listitem(name)
        spoken = []

        speech_mock = MagicMock()
        speech_mock.speakMessage.side_effect = lambda text: spoken.append(text)

        with patch("slack._is_sweeper_enabled", return_value=True), \
             patch("slack._find_unfurl_titles_in_tree",
                   return_value=list(tree_titles or [])), \
             patch("slack._extract_x_preview_text_from_tree",
                   return_value=x_preview), \
             patch("slack.threading.Thread") as thread_mock, \
             patch("slack.speech", speech_mock), \
             patch("slack.braille"), patch("slack.api"), \
             patch("slack.queueHandler"), \
             patch.object(AppModule, "_announce_links_and_meta") as announce:
            self.am.event_gainFocus(obj, lambda: None)

        return types.SimpleNamespace(
            spoken=spoken,
            thread_started=thread_mock.called,
            announce_called=announce.called,
            obj=obj,
        )


class TestTreeTitlePath(_GainFocusHarness):
    """本文に URL があり、ツリーから記事タイトルが取れる経路。

    実機で正常動作しているニュース記事リンクのケース。ネットワークに出ずに
    タイトルを読み上げ、その場で完結する。
    """

    def test_announces_tree_title_without_network_fetch(self):
        name = (
            "サンプル太郎/Sample Taro : https://news.example.com/articles/abc123"
            " 気になる記事。 時刻 16:42。 1 件のリンク。"
        )
        r = self._run(name, tree_titles=["サンプル記事タイトル - Example News"])

        self.assertEqual(len(r.spoken), 1)
        self.assertIn("Link: サンプル記事タイトル - Example News", r.spoken[0])
        self.assertIn("サンプル太郎/Sample Taro", r.spoken[0])
        self.assertFalse(r.thread_started)
        self.assertFalse(r.announce_called)

    def test_raw_url_is_not_spoken(self):
        name = (
            "サンプル太郎/Sample Taro : https://news.example.com/articles/abc123"
            " 気になる記事。 時刻 16:42。"
        )
        r = self._run(name, tree_titles=["サンプル記事タイトル - Example News"])
        self.assertNotIn("https://news.example.com", r.spoken[0])


class TestUnfurlOnlyPath(_GainFocusHarness):
    """unfurl タイトルのみで URL が無い経路。"""

    def test_announces_unfurl_title_and_metadata(self):
        name = (
            "サンプル太郎 : [ サンプル記事タイトル - Example News (リンク)]"
            " コメント本文です。 時刻 16:42。 2 件の返信。"
        )
        r = self._run(name)

        self.assertEqual(len(r.spoken), 1)
        self.assertIn("Link: サンプル記事タイトル - Example News", r.spoken[0])
        self.assertIn("コメント本文です", r.spoken[0])
        self.assertIn("2 件の返信", r.spoken[0])
        self.assertFalse(r.thread_started)

    def test_x_author_title_is_replaced_by_extracted_tweet_body(self):
        name = (
            "サンプル太郎 : [ サンプル花子 (@example_qa) on X (リンク)]"
            " 時刻 16:23。"
        )
        r = self._run(name, x_preview="ツリーから取れたツイート本文です。")

        # 作者リンク名は本文側にインライン展開されて残るが、
        # "Link:" として読まれるのは抽出したツイート本文であること。
        self.assertIn("Link: ツリーから取れたツイート本文です。", r.spoken[0])
        self.assertNotIn("Link: サンプル花子", r.spoken[0])

    def test_x_author_title_kept_when_extraction_fails(self):
        name = (
            "サンプル太郎 : [ サンプル花子 (@example_qa) on X (リンク)]"
            " 時刻 16:23。"
        )
        r = self._run(name, x_preview=None)
        self.assertIn("Link: サンプル花子 (@example_qa) on X", r.spoken[0])


class TestNoUrlPath(_GainFocusHarness):
    """URL も unfurl も無い通常メッセージの経路。"""

    def test_announces_body_and_metadata(self):
        name = "サンプル太郎 : こんにちは、本日は晴天なり。 時刻 10:00。 3 件の返信。"
        r = self._run(name)

        self.assertEqual(len(r.spoken), 1)
        self.assertIn("サンプル太郎", r.spoken[0])
        self.assertIn("こんにちは、本日は晴天なり", r.spoken[0])
        self.assertIn("3 件の返信", r.spoken[0])
        self.assertFalse(r.thread_started)
        self.assertFalse(r.announce_called)

    def test_sets_obj_name_for_braille(self):
        name = "サンプル太郎 : こんにちは。 時刻 10:00。"
        r = self._run(name)
        self.assertEqual(r.obj.name, r.spoken[0])


class TestCachedUrlPath(_GainFocusHarness):
    """キャッシュ済み URL はフェッチせず即座に announce に回る。"""

    def test_cached_title_skips_fetch_thread(self):
        url = "https://news.example.com/articles/cached123"
        AppModule._title_cache.put(url, "キャッシュ済みタイトル")
        name = "サンプル太郎 : " + url + " 気になる記事。 時刻 16:42。"

        r = self._run(name, tree_titles=[])

        self.assertFalse(r.thread_started)
        self.assertTrue(r.announce_called)

    def test_uncached_url_starts_fetch_thread(self):
        name = (
            "サンプル太郎 : https://news.example.com/articles/uncached456"
            " 気になる記事。 時刻 16:42。"
        )
        r = self._run(name, tree_titles=[])

        self.assertTrue(r.thread_started)
        self.assertFalse(r.announce_called)


if __name__ == "__main__":
    unittest.main()
