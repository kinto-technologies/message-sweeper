# -*- coding: utf-8 -*-
"""Tests for Teams message parsing."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon", "appModules"))

for mod_name in [
    "addonHandler", "appModuleHandler", "globalPluginHandler",
    "api", "braille", "nvwave", "tones",
    "speech", "ui", "controlTypes", "queueHandler", "logHandler",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

sys.modules["logHandler"].log = types.SimpleNamespace(
    info=lambda *a, **kw: None,
    debugWarning=lambda *a, **kw: None,
)
sys.modules["controlTypes"].Role = types.SimpleNamespace(
    LISTITEM="LISTITEM", GROUPING="GROUPING"
)

_mock_amh = sys.modules["appModuleHandler"]
_mock_amh.AppModule = type("AppModule", (), {})

_mock_gph = sys.modules["globalPluginHandler"]
_mock_gph.GlobalPlugin = type("GlobalPlugin", (), {})

_mock_addon = sys.modules["addonHandler"]
_mock_addon.initTranslation = lambda: None
_mock_addon.getCodeAddon = lambda: types.SimpleNamespace(
    path=os.path.join(os.path.dirname(__file__), "..")
)

import builtins
if "_" not in dir(builtins):
    builtins._ = lambda x: x

from msTeams import parse_teams_message


class TestParseTeamsMessageJa(unittest.TestCase):
    def test_link_only(self):
        text = "UserName1 リンク https://example.com/page 2026年3月13日 13:51."
        result = parse_teams_message(text)
        self.assertEqual(result["urls"], ["https://example.com/page"])
        self.assertEqual(result["time"], "2026年3月13日 13:51")
        self.assertEqual(result["lang"], "ja")

    def test_link_with_text(self):
        text = "UserName2 リンク https://example.com/api Vibration APIは最近話題 2026年3月6日 11:28."
        result = parse_teams_message(text)
        self.assertEqual(result["urls"], ["https://example.com/api"])
        self.assertIn("Vibration API", result["body"])
        self.assertEqual(result["time"], "2026年3月6日 11:28")

    def test_sent_label(self):
        text = "UserName1 送信済み リンク https://example.com/wiki 2026年3月6日 13:46."
        result = parse_teams_message(text)
        self.assertEqual(result["urls"], ["https://example.com/wiki"])
        self.assertNotIn("送信済み", result["body"])

    def test_no_url_passthrough(self):
        text = "会議を開始しました。受信時刻: 金曜日 13:28."
        result = parse_teams_message(text)
        self.assertEqual(result["urls"], [])

    def test_meeting_summary_passthrough(self):
        text = "23 分 17 秒 の後の 03/06 13:51 に 会議が終了しました:, 定例Mtg, 2026年3月6日 13:30 - 13:45, 要約を表示するためのリンク"
        result = parse_teams_message(text)
        self.assertEqual(result["urls"], [])

    def test_confluence_link(self):
        text = "UserName3 /confluence login リンク https://example.atlassian.net/wiki/x/abc 2026年3月13日 13:51."
        result = parse_teams_message(text)
        self.assertEqual(result["urls"], ["https://example.atlassian.net/wiki/x/abc"])

    def test_nbsp_normalized(self):
        """Non-breaking spaces should be normalized to regular spaces."""
        text = "UserName1 送信済み 👍🎉✨ テストです 🚀🔥\xa0\xa0\xa0\xa0\xa0\xa0 \xa0 :thumbsup: :smile: :heart: 2026年3月18日 10:29."
        result = parse_teams_message(text)
        self.assertNotIn('\xa0', result["body"])
        self.assertEqual(result["time"], "2026年3月18日 10:29")

    def test_no_url_body_extracted(self):
        """Messages without URLs should still have body extracted."""
        text = "UserName1 送信済み テストメッセージです 2026年3月18日 10:29."
        result = parse_teams_message(text)
        self.assertIn("テストメッセージです", result["body"])
        self.assertNotIn("送信済み", result["body"])
        self.assertEqual(result["time"], "2026年3月18日 10:29")

    def test_no_url_emoji_body_extracted(self):
        """Messages with emoji but no URLs should have body extracted."""
        text = "UserName1 👍🎉✨ テストメッセージです 🚀🔥 2026年3月18日 10:56."
        result = parse_teams_message(text)
        self.assertIn("テストメッセージです", result["body"])
        self.assertIn("👍", result["body"])


class TestParseTeamsMessageEn(unittest.TestCase):
    def test_en_datetime_extracted(self):
        """英語 Teams の spelled-out 日時形式が正しく抽出される"""
        text = "サンプル 太郎（Sample Taro） Link サンプルイベント2025 Monday, April 27, 2026 6:05 PM."
        result = parse_teams_message(text)
        self.assertEqual(result["lang"], "en")
        self.assertEqual(result["time"], "Monday, April 27, 2026 6:05 PM")

    def test_en_link_label_to_link_display(self):
        """URL なし添付リンクの表示テキストが link_display に分離される"""
        text = "サンプル 太郎（Sample Taro） Link サンプルイベント2025 Monday, April 27, 2026 6:05 PM."
        result = parse_teams_message(text)
        self.assertNotIn("Link", result["body"])
        self.assertNotIn("サンプルイベント2025", result["body"])
        self.assertEqual(result["link_display"], "サンプルイベント2025")

    def test_en_link_label_with_ascii_title(self):
        """URL なし添付リンク（英語タイトル）の表示テキストが link_display に分離される"""
        text = "サンプル 次郎（Sample Jiro） Link スクリーンリーダー PC-Talker Monday, April 27, 2026 6:11 PM."
        result = parse_teams_message(text)
        self.assertNotIn("Link", result["body"])
        self.assertEqual(result["link_display"], "スクリーンリーダー PC-Talker")
        self.assertEqual(result["time"], "Monday, April 27, 2026 6:11 PM")

    def test_en_url_link_datetime_extracted(self):
        """URL 付き 'Link' メッセージでも日時が正しく抽出される"""
        text = "サンプル 花子（Sample Hanako） Link https://www.example.com/about Monday, May 11, 2026 5:51 PM."
        result = parse_teams_message(text)
        self.assertEqual(result["urls"], ["https://www.example.com/about"])
        self.assertEqual(result["time"], "Monday, May 11, 2026 5:51 PM")
        self.assertNotIn("https://", result["body"])

    def test_en_no_link_regular_message(self):
        """リンクなし通常メッセージで body が正しく抽出される"""
        text = "サンプル 花子（Sample Hanako） Fuchsia Monday, May 11, 2026 5:34 PM."
        result = parse_teams_message(text)
        self.assertIn("Fuchsia", result["body"])
        self.assertEqual(result["time"], "Monday, May 11, 2026 5:34 PM")

    def test_en_slash_date_format_still_works(self):
        """スラッシュ区切り日時形式 (既存) が引き続き動作する"""
        text = "UserName Link https://example.com/page 4/27/2026 6:05 PM."
        result = parse_teams_message(text)
        self.assertEqual(result["urls"], ["https://example.com/page"])
        self.assertEqual(result["time"], "4/27/2026 6:05 PM")


if __name__ == "__main__":
    unittest.main()
