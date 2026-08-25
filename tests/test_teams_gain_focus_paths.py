# -*- coding: utf-8 -*-
"""Teams の event_gainFocus の各分岐の振る舞いを固定する characterization テスト。

slack 側の tests/test_slack_gain_focus_paths.py と同じ役割。event_gainFocus は
分岐が多く、ヘルパーへ分割するリファクタで読み上げ内容が変わっていないことを
確認する安全網が必要になる。各経路が「何を読み上げるか」「obj.name に何を
書くか（点字ディスプレイに出るのはこれ）」「ネットワークフェッチを起動するか」
を固定する。

fixture は架空データ。実在の人名・URL・投稿本文は含まない。
"""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon", "appModules"))

for _mod_name in [
    "addonHandler", "appModuleHandler", "globalPluginHandler",
    "api", "braille", "nvwave", "tones",
    "speech", "ui", "controlTypes", "queueHandler", "logHandler",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = types.ModuleType(_mod_name)


def _ensure_attrs(owner, **defaults):
    for name, value in defaults.items():
        if not hasattr(owner, name):
            setattr(owner, name, value)


_lh = sys.modules["logHandler"]
if not hasattr(_lh, "log"):
    _lh.log = types.SimpleNamespace()
_ensure_attrs(
    _lh.log,
    info=lambda *a, **kw: None,
    warning=lambda *a, **kw: None,
    error=lambda *a, **kw: None,
    debug=lambda *a, **kw: None,
    debugWarning=lambda *a, **kw: None,
)

_ct = sys.modules["controlTypes"]
if not hasattr(_ct, "Role"):
    _ct.Role = types.SimpleNamespace()
_ensure_attrs(_ct.Role, **{
    name: name for name in (
        "LISTITEM", "LINK", "GRAPHIC", "BUTTON", "GROUP", "SECTION",
        "GROUPING", "STATICTEXT",
    )
})

_ensure_attrs(sys.modules["appModuleHandler"], AppModule=type("AppModule", (), {}))
_ensure_attrs(sys.modules["addonHandler"], initTranslation=lambda: None)

# shared.config imports NVDA's config module. A plain dict raises KeyError for
# the add-on's section, which is what makes get_config fall back to DEFAULTS --
# so these tests read the shipped defaults (summary after, link failure host).
if "config" not in sys.modules:
    _cfg = types.ModuleType("config")
    _cfg.conf = {}
    sys.modules["config"] = _cfg

import builtins
if "_" not in dir(builtins):
    builtins._ = lambda x: x

import msTeams
from shared.fetcher import TitleCache
from shared import state


class _GainFocusHarness(unittest.TestCase):
    """event_gainFocus を呼び、読み上げ内容とフェッチ起動を観測する土台。"""

    def setUp(self):
        msTeams.AppModule._title_cache = TitleCache()
        self.am = msTeams.AppModule()
        state.set_processing_enabled(True)
        self.addCleanup(state.set_processing_enabled, True)

    def _grouping(self, name):
        obj = MagicMock()
        obj.role = _ct.Role.GROUPING
        obj.name = name
        return obj

    def _run(self, obj):
        """event_gainFocus を実行し、観測結果を返す。"""
        spoken = []
        next_handler = MagicMock()

        speech_mock = MagicMock()
        speech_mock.speakMessage.side_effect = lambda text: spoken.append(text)

        with patch("msTeams.speech", speech_mock), \
                patch("msTeams.braille"), \
                patch("msTeams.api"), \
                patch("msTeams.queueHandler"), \
                patch("msTeams.threading.Thread") as thread_mock:
            self.am.event_gainFocus(obj, next_handler)

        return types.SimpleNamespace(
            spoken=spoken,
            thread_started=thread_mock.called,
            next_handler_calls=next_handler.call_count,
            name=obj.name,
        )


class TestPassThroughPaths(_GainFocusHarness):
    """読み上げを組み替えない経路。NVDA 標準の読み上げに任せる。"""

    def test_non_grouping_role_is_left_alone(self):
        obj = self._grouping("UserName1 テストメッセージです 2026年3月18日 10:29.")
        obj.role = _ct.Role.LISTITEM
        original = obj.name
        r = self._run(obj)
        self.assertEqual([], r.spoken)
        self.assertEqual(1, r.next_handler_calls)
        self.assertEqual(original, r.name)

    def test_empty_name_is_left_alone(self):
        obj = self._grouping("")
        r = self._run(obj)
        self.assertEqual([], r.spoken)
        self.assertEqual(1, r.next_handler_calls)

    def test_processing_disabled_is_left_alone(self):
        state.set_processing_enabled(False)
        obj = self._grouping("UserName1 テストメッセージです 2026年3月18日 10:29.")
        original = obj.name
        r = self._run(obj)
        self.assertEqual([], r.spoken)
        self.assertEqual(1, r.next_handler_calls)
        self.assertEqual(original, r.name)


class TestNoUrlPath(_GainFocusHarness):
    """URL を含まないメッセージ。その場で読み上げが完結する。"""

    def test_body_then_time(self):
        obj = self._grouping(
            "UserName1 送信済み テストメッセージです 2026年3月18日 10:29.")
        r = self._run(obj)
        self.assertEqual(
            ["UserName1 テストメッセージです. 2026年3月18日 10:29"], r.spoken)
        self.assertEqual(r.spoken[0], r.name)
        self.assertFalse(r.thread_started)

    def test_link_display_is_announced_as_a_link(self):
        obj = self._grouping(
            "サンプル 太郎（Sample Taro） Link サンプルイベント2025 "
            "Monday, April 27, 2026 6:05 PM.")
        r = self._run(obj)
        self.assertEqual(
            ["サンプル 太郎（Sample Taro）. Link: サンプルイベント2025. "
             "Monday, April 27, 2026 6:05 PM"],
            r.spoken)

    def test_emoji_run_is_summarized_after_the_body(self):
        # 装飾として並んだ絵文字は本文から外れ、まとめとして本文と時刻の間に
        # 入る。まとめのラベルが絵文字そのものになるのは現在の挙動で、この
        # リファクタで変えるものではない。
        obj = self._grouping(
            "UserName1 プロジェクト完了おめでとう \U0001F389\U0001F389\U0001F389"
            "\U0001F389 最高でした 2026年3月18日 10:29.")
        r = self._run(obj)
        self.assertEqual(
            ["UserName1 プロジェクト完了おめでとう 最高でした. "
             "メッセージの絵文字: \U0001F389\U0001F389\U0001F389\U0001F389"
             "1こ. 2026年3月18日 10:29"],
            r.spoken)

    def test_nothing_left_to_say_falls_through(self):
        obj = self._grouping("   ")
        r = self._run(obj)
        self.assertEqual([], r.spoken)
        self.assertEqual(1, r.next_handler_calls)


class TestUrlPath(_GainFocusHarness):
    """URL を含むメッセージ。本文を先に読み、タイトルは後から追う。"""

    URL = "https://example.com/page"

    def test_body_spoken_first_and_fetch_started(self):
        obj = self._grouping(
            "UserName2 リンク %s Vibration APIは最近話題 2026年3月6日 11:28."
            % self.URL)
        r = self._run(obj)
        self.assertEqual(1, len(r.spoken))
        self.assertIn("Vibration API", r.spoken[0])
        # 時刻と URL は即時読み上げに含めない（タイトルと一緒に後から読む）
        self.assertNotIn("2026年3月6日", r.spoken[0])
        self.assertNotIn("https://", r.spoken[0])
        self.assertTrue(r.thread_started)

    def test_body_only_url_announces_a_fetch_placeholder(self):
        obj = self._grouping("リンク %s 2026年3月6日 11:28." % self.URL)
        r = self._run(obj)
        self.assertEqual(["Teams. Fetching link titles..."], r.spoken)
        self.assertTrue(r.thread_started)

    def test_cached_title_is_announced_without_fetching(self):
        msTeams.AppModule._title_cache.put(self.URL, "サンプルページ - Example")
        obj = self._grouping(
            "UserName2 リンク %s 本文です 2026年3月6日 11:28." % self.URL)
        r = self._run(obj)
        self.assertFalse(r.thread_started)
        self.assertEqual(
            ["UserName2 本文です",
             "Link: サンプルページ - Example. 2026年3月6日 11:28"],
            r.spoken)

    def test_cached_failure_announces_the_host(self):
        msTeams.AppModule._title_cache.put(self.URL, None)
        obj = self._grouping(
            "UserName2 リンク %s 本文です 2026年3月6日 11:28." % self.URL)
        r = self._run(obj)
        self.assertFalse(r.thread_started)
        # 既定の link_failure_announce は host
        self.assertEqual(
            ["UserName2 本文です",
             "Link: example.com (Title unavailable). 2026年3月6日 11:28"],
            r.spoken)


if __name__ == "__main__":
    unittest.main()
