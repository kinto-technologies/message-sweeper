# -*- coding: utf-8 -*-
"""event_gainFocus / _announce_titles の各分岐を固定する characterization テスト。

Teams 側の NVDA イベント処理層は分岐が多く、テストが無いと Teams の表示仕様が
変わったときに「読み上げが静かに変わる」形で壊れる。各経路が

  ・何を読み上げるか
  ・nextHandler を呼ぶか
  ・ネットワークフェッチを起動するか

を固定して、その種の退行をここで捕まえる。tests/test_slack_gain_focus_paths.py
の Slack 版と同じ組み立て。

fixture は架空データ。実在の人名・URL・投稿本文は含まない。
"""
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon", "globalPlugins"))

for mod_name in [
    "addonHandler", "globalPluginHandler", "api", "braille", "nvwave",
    "tones", "speech", "ui", "controlTypes", "queueHandler", "logHandler",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

sys.modules["logHandler"].log = types.SimpleNamespace(
    info=lambda *a, **kw: None,
    debugWarning=lambda *a, **kw: None,
    warning=lambda *a, **kw: None,
)
# controlTypes.Role は他のテストモジュールも共有する。名前空間ごと差し替えると
# 先に入っていたロールを落として別テストを壊すので、足りないものだけ足す。
_ct_role = getattr(sys.modules["controlTypes"], "Role", None)
if _ct_role is None:
    _ct_role = types.SimpleNamespace()
    sys.modules["controlTypes"].Role = _ct_role
for _role_name in ("LISTITEM", "LINK", "GRAPHIC", "BUTTON", "GROUP",
                   "SECTION", "GROUPING", "STATICTEXT"):
    if not hasattr(_ct_role, _role_name):
        setattr(_ct_role, _role_name, _role_name)

_mock_gph = sys.modules["globalPluginHandler"]
if not hasattr(_mock_gph, "GlobalPlugin"):
    _mock_gph.GlobalPlugin = type("GlobalPlugin", (), {})

_mock_addon = sys.modules["addonHandler"]
_mock_addon.initTranslation = lambda: None
_mock_addon.getCodeAddon = lambda: types.SimpleNamespace(
    path=os.path.join(os.path.dirname(__file__), "..")
)

# shared.config は NVDA の config モジュールを import する。既に別のテスト
# モジュールがモックを入れている場合はそれを尊重する（差し替えると先に
# import した側の参照と食い違うため）。
if "config" not in sys.modules:
    _mock_config = types.ModuleType("config")

    class _MockConfigDict(dict):
        def __init__(self):
            super().__init__()
            self.spec = {}

    _mock_config.conf = _MockConfigDict()
    sys.modules["config"] = _mock_config

import builtins
if "_" not in dir(builtins):
    builtins._ = lambda x: x

from teamsMessageSweeper import GlobalPlugin
from shared.fetcher import TitleCache

# 架空の Teams メッセージ（日本語 UI）。末尾の日時が言語判定のトリガ。
JA_TIME = "2026年3月13日 13:51."
EN_TIME = "3/13/2026 1:51 PM."


def _fake_get_config(summary_position="after", link_failure="host",
                     toggle_sound=True, emoji_threshold=3):
    """shared.config.get_config の差し替え。キー名は config.py の定義に対応。"""
    values = {
        "summary_position": summary_position,
        "link_failure_announce": link_failure,
        "toggle_sound": toggle_sound,
        "emoji_threshold": emoji_threshold,
    }

    def _get(key):
        return values[key]

    return _get


class _TeamsFocusHarness(unittest.TestCase):
    """event_gainFocus を呼び、読み上げ内容とフェッチ起動を観測する土台。"""

    def setUp(self):
        GlobalPlugin._title_cache = TitleCache()
        GlobalPlugin._processing_enabled = True
        self.plugin = GlobalPlugin()

    def _grouping(self, name, role="GROUPING", app_name="ms-teams"):
        obj = MagicMock()
        obj.role = role
        obj.name = name
        obj.appModule.appName = app_name
        return obj

    def _run(self, name, role="GROUPING", app_name="ms-teams",
             fg_title="Microsoft Teams", summary_position="after",
             obj=None):
        """event_gainFocus を実行し、観測結果をまとめて返す。"""
        if obj is None:
            obj = self._grouping(name, role, app_name)
        spoken = []
        next_calls = []

        speech_mock = MagicMock()
        speech_mock.speakMessage.side_effect = lambda text: spoken.append(text)
        api_mock = MagicMock()
        api_mock.getForegroundObject.return_value = types.SimpleNamespace(
            name=fg_title
        )

        with patch("teamsMessageSweeper.speech", speech_mock), \
             patch("teamsMessageSweeper.api", api_mock), \
             patch("teamsMessageSweeper.braille"), \
             patch("teamsMessageSweeper.queueHandler"), \
             patch("teamsMessageSweeper.threading.Thread") as thread_mock, \
             patch("shared.config.get_config",
                   _fake_get_config(summary_position=summary_position)), \
             patch.object(GlobalPlugin, "_announce_titles") as announce:
            self.plugin.event_gainFocus(obj, lambda: next_calls.append("next"))

        return types.SimpleNamespace(
            spoken=spoken,
            next_called=bool(next_calls),
            thread_started=thread_mock.called,
            thread_kwargs=thread_mock.call_args.kwargs if thread_mock.called else {},
            announce_called=announce.called,
            announce_args=announce.call_args,
            obj=obj,
        )


class TestContextGuard(_TeamsFocusHarness):
    """Teams のメッセージ本体以外は素通しする（NVDA 既定の読み上げに任せる）。"""

    def test_disabled_passes_through(self):
        GlobalPlugin._processing_enabled = False
        r = self._run("サンプル太郎 こんにちは。 " + JA_TIME)
        self.assertTrue(r.next_called)
        self.assertEqual(r.spoken, [])

    def test_non_teams_app_passes_through(self):
        r = self._run("サンプル太郎 こんにちは。 " + JA_TIME, app_name="notepad")
        self.assertTrue(r.next_called)
        self.assertEqual(r.spoken, [])

    def test_webview_without_teams_window_title_passes_through(self):
        # msedgewebview2 は Teams 以外（スタートメニュー検索など）でも動くため、
        # 前面ウィンドウのタイトルで Teams かどうかを見分けている。
        r = self._run(
            "サンプル太郎 こんにちは。 " + JA_TIME,
            app_name="msedgewebview2",
            fg_title="ウィジェット",
        )
        self.assertTrue(r.next_called)
        self.assertEqual(r.spoken, [])

    def test_webview_with_teams_window_title_is_processed(self):
        r = self._run(
            "サンプル太郎 こんにちは。 " + JA_TIME,
            app_name="msedgewebview2",
            fg_title="チャット | Microsoft Teams",
        )
        self.assertEqual(len(r.spoken), 1)

    def test_missing_app_module_passes_through(self):
        obj = self._grouping("サンプル太郎 こんにちは。 " + JA_TIME)
        del obj.appModule  # appModule 参照で AttributeError になる状況
        r = self._run("", obj=obj)
        self.assertTrue(r.next_called)
        self.assertEqual(r.spoken, [])

    def test_non_grouping_role_passes_through(self):
        r = self._run("サンプル太郎 こんにちは。 " + JA_TIME, role="STATICTEXT")
        self.assertTrue(r.next_called)
        self.assertEqual(r.spoken, [])

    def test_empty_name_passes_through(self):
        r = self._run("")
        self.assertTrue(r.next_called)
        self.assertEqual(r.spoken, [])

    def test_name_without_speakable_content_passes_through(self):
        # 空白だけの accessible name。整形結果が空になるので読み上げない。
        r = self._run("   ")
        self.assertTrue(r.next_called)
        self.assertEqual(r.spoken, [])


class TestNoUrlPath(_TeamsFocusHarness):
    """URL を含まない通常メッセージの経路。その場で完結する。"""

    def test_announces_body_and_time(self):
        r = self._run("サンプル太郎 本日は晴天なり。 " + JA_TIME)

        self.assertEqual(len(r.spoken), 1)
        self.assertIn("本日は晴天なり", r.spoken[0])
        self.assertIn("2026年3月13日 13:51", r.spoken[0])
        self.assertTrue(r.next_called)
        self.assertFalse(r.thread_started)
        self.assertFalse(r.announce_called)

    def test_sets_obj_name_for_braille(self):
        r = self._run("サンプル太郎 本日は晴天なり。 " + JA_TIME)
        self.assertEqual(r.obj.name, r.spoken[0])

    def test_english_message_time_is_kept(self):
        r = self._run("Sample Taro Hello there. " + EN_TIME)
        self.assertIn("Hello there", r.spoken[0])
        self.assertIn("3/13/2026 1:51 PM", r.spoken[0])

    def test_attachment_link_display_text_is_announced_as_link(self):
        # URL を持たない添付リンク。Teams は "リンク" ラベル＋表示テキストで
        # 露出するので、URL リンクと同じ「Link: ...」形式に揃える。
        r = self._run("サンプル太郎 資料を共有します リンク 会議メモ " + JA_TIME)
        self.assertIn("Link: 会議メモ", r.spoken[0])
        self.assertIn("資料を共有します", r.spoken[0])

    def test_emoji_run_summary_appended_after_body(self):
        name = (
            "サンプル太郎 プロジェクト完了おめでとう "
            "\U0001F389\U0001F389\U0001F389\U0001F389 最高でした " + JA_TIME
        )
        r = self._run(name, summary_position="after")

        body_idx = r.spoken[0].index("最高でした")
        summary_idx = r.spoken[0].index("絵文字")
        self.assertLess(body_idx, summary_idx)
        # 本文からは連続ランが消え、サマリ側だけが絵文字を持つ。
        self.assertNotIn("\U0001F389", r.spoken[0][:summary_idx])

    def test_emoji_run_summary_can_be_placed_before_body(self):
        name = (
            "サンプル太郎 プロジェクト完了おめでとう "
            "\U0001F389\U0001F389\U0001F389\U0001F389 最高でした " + JA_TIME
        )
        r = self._run(name, summary_position="before")

        summary_idx = r.spoken[0].index("絵文字")
        body_idx = r.spoken[0].index("最高でした")
        self.assertLess(summary_idx, body_idx)

    def test_emoji_run_summary_suppressed_when_off(self):
        name = (
            "サンプル太郎 プロジェクト完了おめでとう "
            "\U0001F389\U0001F389\U0001F389\U0001F389 最高でした " + JA_TIME
        )
        r = self._run(name, summary_position="off")

        self.assertNotIn("\U0001F389", r.spoken[0])
        self.assertNotIn("絵文字", r.spoken[0])

    def test_isolated_emoji_survives(self):
        # ラン長 1 の絵文字は情報を持つので残す（週間予定などのケース）。
        r = self._run("サンプル太郎 月 \U0001F3E0 火 \U0001F3E2 " + JA_TIME)
        self.assertIn("\U0001F3E0", r.spoken[0])
        self.assertIn("\U0001F3E2", r.spoken[0])


class TestUrlPath(_TeamsFocusHarness):
    """URL を含むメッセージの経路。本文を先に読み、タイトルは後追いで読む。"""

    def test_uncached_url_starts_fetch_thread(self):
        name = (
            "サンプル太郎 リンク https://news.example.com/articles/abc123"
            " 気になる記事 " + JA_TIME
        )
        r = self._run(name)

        self.assertTrue(r.thread_started)
        self.assertFalse(r.announce_called)
        self.assertEqual(len(r.spoken), 1)
        self.assertIn("気になる記事", r.spoken[0])

    def test_time_is_deferred_to_the_title_announcement(self):
        # 時刻はタイトルと一緒に後から読む。先読みには含めない。
        name = (
            "サンプル太郎 リンク https://news.example.com/articles/abc123"
            " 気になる記事 " + JA_TIME
        )
        r = self._run(name)
        self.assertNotIn("2026年3月13日", r.spoken[0])

    def test_raw_url_is_not_spoken(self):
        name = (
            "サンプル太郎 リンク https://news.example.com/articles/abc123"
            " 気になる記事 " + JA_TIME
        )
        r = self._run(name)
        self.assertNotIn("https://news.example.com", r.spoken[0])

    def test_url_only_message_announces_fetching_placeholder(self):
        # 本文が無い（URL だけの）投稿では、無音で待たせず取得中を知らせる。
        name = "リンク https://news.example.com/articles/abc123 " + JA_TIME
        r = self._run(name)

        self.assertEqual(len(r.spoken), 1)
        self.assertIn("Fetching link titles", r.spoken[0])
        self.assertTrue(r.thread_started)

    def test_cached_url_skips_fetch_thread(self):
        url = "https://news.example.com/articles/cached123"
        GlobalPlugin._title_cache.put(url, "キャッシュ済みタイトル")
        name = "サンプル太郎 リンク " + url + " 気になる記事 " + JA_TIME

        r = self._run(name)

        self.assertFalse(r.thread_started)
        self.assertTrue(r.announce_called)
        # キャッシュ値がそのまま _announce_titles に渡ること
        self.assertEqual(
            r.announce_args.args[1], {url: "キャッシュ済みタイトル"}
        )

    def test_partially_cached_urls_still_fetch_the_missing_one(self):
        cached = "https://news.example.com/articles/cached123"
        GlobalPlugin._title_cache.put(cached, "キャッシュ済みタイトル")
        name = (
            "サンプル太郎 リンク " + cached
            + " と https://news.example.com/articles/fresh456 " + JA_TIME
        )
        r = self._run(name)

        self.assertTrue(r.thread_started)
        self.assertFalse(r.announce_called)


class TestFetchThreadBody(_TeamsFocusHarness):
    """バックグラウンドスレッドが実際に行う処理（取得・キャッシュ・再読み上げ）。"""

    def _capture_thread_target(self, name):
        """event_gainFocus を実行し、起動されたスレッドの target を返す。"""
        obj = self._grouping(name)
        speech_mock = MagicMock()
        api_mock = MagicMock()
        api_mock.getForegroundObject.return_value = types.SimpleNamespace(
            name="Microsoft Teams"
        )
        with patch("teamsMessageSweeper.speech", speech_mock), \
             patch("teamsMessageSweeper.api", api_mock), \
             patch("teamsMessageSweeper.braille"), \
             patch("teamsMessageSweeper.queueHandler"), \
             patch("teamsMessageSweeper.threading.Thread") as thread_mock, \
             patch("shared.config.get_config", _fake_get_config()):
            self.plugin.event_gainFocus(obj, lambda: None)
        return thread_mock.call_args.kwargs["target"]

    def test_page_title_is_fetched_cached_and_queued(self):
        url = "https://news.example.com/articles/abc123"
        target = self._capture_thread_target(
            "サンプル太郎 リンク " + url + " 気になる記事 " + JA_TIME
        )

        queue_mock = MagicMock()
        with patch("teamsMessageSweeper.fetch_page_title",
                   return_value="サンプル記事タイトル") as fetch_mock, \
             patch("teamsMessageSweeper.fetch_x_post_via_oembed") as oembed_mock, \
             patch("teamsMessageSweeper.queueHandler", queue_mock):
            target()

        fetch_mock.assert_called_once_with(url)
        self.assertFalse(oembed_mock.called)
        self.assertEqual(
            GlobalPlugin._title_cache.get(url), "サンプル記事タイトル"
        )
        # 読み上げは NVDA のイベントキュー経由で行う（別スレッドから直接
        # speech を触らない）。
        self.assertTrue(queue_mock.queueFunction.called)
        queued_args = queue_mock.queueFunction.call_args.args
        self.assertEqual(queued_args[1], self.plugin._announce_titles)
        self.assertEqual(queued_args[3], {url: "サンプル記事タイトル"})

    def test_x_post_uses_oembed_instead_of_page_title(self):
        url = "https://x.com/example_user/status/1234567890123456789"
        target = self._capture_thread_target(
            "サンプル太郎 リンク " + url + " 見てください " + JA_TIME
        )

        with patch("teamsMessageSweeper.fetch_page_title") as fetch_mock, \
             patch("teamsMessageSweeper.fetch_x_post_via_oembed",
                   return_value="架空のポスト本文") as oembed_mock, \
             patch("teamsMessageSweeper.queueHandler"):
            target()

        oembed_mock.assert_called_once_with(url)
        self.assertFalse(fetch_mock.called)
        self.assertEqual(GlobalPlugin._title_cache.get(url), "架空のポスト本文")


class TestAnnounceTitles(_TeamsFocusHarness):
    """タイトル取得後の読み上げと、点字ディスプレイ向けの本文差し替え。"""

    def _announce(self, parsed, url_title_map, immediate_text="本文",
                  link_failure="host", focus=None):
        spoken = []
        speech_mock = MagicMock()
        speech_mock.speakMessage.side_effect = lambda text: spoken.append(text)
        api_mock = MagicMock()
        api_mock.getFocusObject.return_value = focus
        braille_mock = MagicMock()

        with patch("teamsMessageSweeper.speech", speech_mock), \
             patch("teamsMessageSweeper.api", api_mock), \
             patch("teamsMessageSweeper.braille", braille_mock), \
             patch("shared.config.get_config",
                   _fake_get_config(link_failure=link_failure)):
            self.plugin._announce_titles(parsed, url_title_map, immediate_text)

        return types.SimpleNamespace(
            spoken=spoken,
            braille=braille_mock,
            focus=focus,
        )

    def test_announces_title_then_time(self):
        url = "https://news.example.com/articles/abc123"
        r = self._announce(
            {"urls": [url], "time": "2026年3月13日 13:51"},
            {url: "サンプル記事タイトル"},
        )

        self.assertEqual(len(r.spoken), 1)
        self.assertIn("Link: サンプル記事タイトル", r.spoken[0])
        self.assertIn("2026年3月13日 13:51", r.spoken[0])

    def test_failed_fetch_falls_back_to_host(self):
        url = "https://news.example.com/articles/abc123"
        r = self._announce(
            {"urls": [url], "time": ""}, {url: None}, link_failure="host"
        )
        self.assertIn("news.example.com", r.spoken[0])

    def test_silent_mode_with_no_title_and_no_time_speaks_nothing(self):
        url = "https://news.example.com/articles/abc123"
        r = self._announce(
            {"urls": [url], "time": ""}, {url: None}, link_failure="silent"
        )
        self.assertEqual(r.spoken, [])

    def test_focus_name_gets_the_combined_text_for_braille(self):
        url = "https://news.example.com/articles/abc123"
        focus = MagicMock()
        r = self._announce(
            {"urls": [url], "time": ""},
            {url: "サンプル記事タイトル"},
            immediate_text="気になる記事",
            focus=focus,
        )

        self.assertIn("気になる記事", focus.name)
        self.assertIn("Link: サンプル記事タイトル", focus.name)
        r.braille.handler.handleGainFocus.assert_called_once_with(focus)

    def test_link_text_stands_alone_when_nothing_was_spoken_first(self):
        url = "https://news.example.com/articles/abc123"
        focus = MagicMock()
        self._announce(
            {"urls": [url], "time": ""},
            {url: "サンプル記事タイトル"},
            immediate_text="",
            focus=focus,
        )
        self.assertEqual(focus.name, "Link: サンプル記事タイトル")

    def test_focus_update_failure_does_not_break_speech(self):
        # フォーカスが既に別の要素へ移っている場合など。読み上げは済んでいる
        # ので、点字側の更新失敗で例外を投げてはいけない。
        url = "https://news.example.com/articles/abc123"
        focus = MagicMock()
        type(focus).name = property(
            lambda self: "", lambda self, value: (_ for _ in ()).throw(
                RuntimeError("dead object")
            )
        )
        r = self._announce(
            {"urls": [url], "time": ""}, {url: "サンプル記事タイトル"},
            focus=focus,
        )
        self.assertEqual(len(r.spoken), 1)


class TestToggleProcessing(_TeamsFocusHarness):
    """NVDA+V の切り替え。既定はトーン、設定で音声通知にも切り替わる。"""

    def _toggle(self, toggle_sound=True):
        speech_mock = MagicMock()
        tones_mock = MagicMock()
        braille_mock = MagicMock()
        with patch("teamsMessageSweeper.speech", speech_mock), \
             patch("teamsMessageSweeper.tones", tones_mock), \
             patch("teamsMessageSweeper.braille", braille_mock), \
             patch("shared.config.get_config",
                   _fake_get_config(toggle_sound=toggle_sound)):
            self.plugin.script_toggleProcessing(None)
        return types.SimpleNamespace(
            speech=speech_mock, tones=tones_mock, braille=braille_mock
        )

    def test_toggle_off_then_on_with_tones(self):
        r = self._toggle()
        self.assertFalse(GlobalPlugin._processing_enabled)
        self.assertTrue(r.tones.beep.called)
        self.assertFalse(r.speech.speakMessage.called)
        self.assertTrue(r.braille.handler.message.called)

        r = self._toggle()
        self.assertTrue(GlobalPlugin._processing_enabled)

    def test_toggle_speaks_message_when_sound_disabled(self):
        r = self._toggle(toggle_sound=False)
        self.assertFalse(r.tones.beep.called)
        self.assertTrue(r.speech.speakMessage.called)

    def test_toggle_falls_back_to_tone_when_config_unavailable(self):
        speech_mock = MagicMock()
        tones_mock = MagicMock()
        with patch("teamsMessageSweeper.speech", speech_mock), \
             patch("teamsMessageSweeper.tones", tones_mock), \
             patch("teamsMessageSweeper.braille"), \
             patch("shared.config.get_config",
                   side_effect=RuntimeError("config not registered")):
            self.plugin.script_toggleProcessing(None)

        self.assertTrue(tones_mock.beep.called)
        self.assertFalse(speech_mock.speakMessage.called)


class TestNextHandlerFailures(_TeamsFocusHarness):
    """nextHandler が例外を投げても読み上げまで到達させる。

    NVDA 側の既定処理が失敗しても、こちらの整形済み読み上げは止めない。
    """

    def _run_with_failing_next(self, name, role="GROUPING"):
        obj = self._grouping(name, role)
        spoken = []
        speech_mock = MagicMock()
        speech_mock.speakMessage.side_effect = lambda text: spoken.append(text)
        api_mock = MagicMock()
        api_mock.getForegroundObject.return_value = types.SimpleNamespace(
            name="Microsoft Teams"
        )

        def _boom():
            raise RuntimeError("nextHandler failed")

        with patch("teamsMessageSweeper.speech", speech_mock), \
             patch("teamsMessageSweeper.api", api_mock), \
             patch("teamsMessageSweeper.braille"), \
             patch("teamsMessageSweeper.queueHandler"), \
             patch("teamsMessageSweeper.threading.Thread"), \
             patch("shared.config.get_config", _fake_get_config()), \
             patch.object(GlobalPlugin, "_announce_titles"):
            self.plugin.event_gainFocus(obj, _boom)
        return spoken

    def test_no_url_path_survives_next_handler_error(self):
        spoken = self._run_with_failing_next(
            "サンプル太郎 本日は晴天なり。 " + JA_TIME
        )
        self.assertEqual(len(spoken), 1)
        self.assertIn("本日は晴天なり", spoken[0])

    def test_url_path_survives_next_handler_error(self):
        spoken = self._run_with_failing_next(
            "サンプル太郎 リンク https://news.example.com/articles/abc123"
            " 気になる記事 " + JA_TIME
        )
        self.assertEqual(len(spoken), 1)
        self.assertIn("気になる記事", spoken[0])

    def test_non_grouping_path_survives_next_handler_error(self):
        spoken = self._run_with_failing_next(
            "サンプル太郎 本日は晴天なり。 " + JA_TIME, role="STATICTEXT"
        )
        self.assertEqual(spoken, [])


if __name__ == "__main__":
    unittest.main()
