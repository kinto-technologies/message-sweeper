# -*- coding: utf-8 -*-
"""Tests for i18n message parsing."""
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

from shared.patterns import _detect_lang, TWITTER_PATTERN, URL_PATTERN
from shared.cleaner import clean_message_body
from shared.fetcher import _title_from_github_url
from slack import parse_slack_message, _get_level_from_obj


class TestDetectLang(unittest.TestCase):
    def test_japanese_metadata(self):
        text = "こんにちは。 時刻 12:10。 1 件のリンク"
        self.assertEqual(_detect_lang(text), "ja")

    def test_english_metadata(self):
        text = "Hello. 2:01 PM. 1 link."
        self.assertEqual(_detect_lang(text), "en")

    def test_no_metadata_defaults_to_en(self):
        text = "just a plain message"
        self.assertEqual(_detect_lang(text), "en")

    def test_japanese_with_reactions(self):
        text = "メッセージ。 時刻 14:30。 2 個の絵文字リアクション"
        self.assertEqual(_detect_lang(text), "ja")

    def test_japanese_notification_format(self):
        """通知一覧の時刻形式 （HH:MM） でも日本語と判定される"""
        text = (
            "サンプル花子/Sample Hanakoさんが #dev-team であなたをメンションしました。"
            "本文テスト。（11:18）。  レベル1"
        )
        self.assertEqual(_detect_lang(text), "ja")


    def test_japanese_link_only_message(self):
        """リンクのみメッセージ: ] の直後に時刻が来るケースでも日本語判定される"""
        text = "サンプル太郎 : [ https://example.com/ (リンク)] 時刻 22:05。 1 件のリンク。"
        self.assertEqual(_detect_lang(text), "ja")

    def test_japanese_fallback_keyword(self):
        """metadata_suffix未マッチでも日本語キーワードで判定"""
        text = "サンプル太郎 : テスト 時刻 12:00"
        self.assertEqual(_detect_lang(text), "ja")


class TestParseSlackMessageJa(unittest.TestCase):
    def test_full_message_with_metadata(self):
        text = "Yamada: こんにちは。 時刻 12:10。 1 件のリンク。 2 個の絵文字リアクション。 3 件の返信"
        result = parse_slack_message(text)
        self.assertEqual(result["lang"], "ja")
        self.assertEqual(result["sender"], "Yamada")
        self.assertEqual(result["time"], "12:10")
        self.assertEqual(result["link_count"], "1")
        self.assertIn("リアクション", result["reactions"])
        self.assertIn("返信", result["replies"])

    def test_unfurl_japanese(self):
        text = "Yamada: 記事を見て [ タイトル (リンク)]。 時刻 12:10"
        result = parse_slack_message(text)
        self.assertEqual(result["unfurl_titles"], ["タイトル"])
        self.assertIn("記事を見て", result["body"])

    def test_body_trailing_kuten_stripped_after_unfurl_removal(self):
        """unfurl ブロック除去後に本文末尾の。が残らないこと（区切り文字と重複防止）"""
        text = "Taro: メッセージです。 [ タイトル (リンク)] 時刻 10:00"
        result = parse_slack_message(text)
        self.assertFalse(result["body"].endswith("。"),
                         f"body should not end with 。, got: {result['body']!r}")

    def test_link_only_message_parsed_correctly(self):
        """リンクのみメッセージで unfurl が正しく解析され、括弧が残らない"""
        text = "サンプル太郎 : [ https://example.com/page (リンク)] 時刻 22:05。 1 件のリンク。"
        result = parse_slack_message(text)
        self.assertEqual(result["lang"], "ja")
        self.assertEqual(result["sender"], "サンプル太郎")
        self.assertEqual(result["time"], "22:05")
        self.assertEqual(result["link_count"], "1")
        self.assertIn("https://example.com/page", result["urls"])
        self.assertNotIn("[", result["body"])
        self.assertNotIn("(リンク)", result["body"])

    def test_time_is_captured_whole_with_and_without_trailing_kuten(self):
        """時刻は「。」で閉じる形と文末で終わる形の両方で全体が取れること。

        時刻パターンは `時刻\\s+(.+?)(?:。|$)` の形で、遅延量指定子が「。」か
        文末まで伸びることを前提にしている。文末で終わる分岐にテストが無かった
        ため、ここで両方を固定する。SonarQube の python:S6019（遅延量指定子が
        1文字しかマッチしない）はこの形に対する誤検知で、下の assert が
        5文字取れていることがその反証になる。
        """
        with_kuten = parse_slack_message("Taro: 本日は晴天なり。 時刻 12:10。 1 件のリンク")
        self.assertEqual(with_kuten["time"], "12:10")

        at_end = parse_slack_message("Taro: 本日は晴天なり。 時刻 12:10")
        self.assertEqual(at_end["time"], "12:10")

    def test_mention_japanese(self):
        text = "Yamadaさんが #general であなたをメンションしました。 メッセージ本文。 時刻 12:10"
        result = parse_slack_message(text)
        self.assertEqual(result["sender"], "Yamada")
        self.assertIn("Yamada", result["mention_info"])
        self.assertIn("general", result["mention_info"])

    def test_notification_mention_with_emoji(self):
        """通知一覧のメンション形式で絵文字が除去される"""
        text = (
            "サンプル花子/Sample Hanakoさんが #dev-team であなたをメンションしました。"
            "拡声器 絵文字 テスト本文 blob 絵文字 wave 絵文字 hello 絵文字 foo 絵文字 bar 絵文字。"
            "（11:18）。  レベル1"
        )
        result = parse_slack_message(text)
        self.assertEqual(result["lang"], "ja")
        self.assertEqual(result["sender"], "サンプル花子/Sample Hanako")
        self.assertIn("dev-team", result["mention_info"])

    def test_notification_metadata_parsed(self):
        """通知一覧の （HH:MM） 形式で時刻が抽出される"""
        text = (
            "サンプル花子/Sample Hanakoさんが #dev-team であなたをメンションしました。"
            "テスト本文。（11:18）。  レベル1"
        )
        result = parse_slack_message(text)
        self.assertEqual(result["time"], "11:18")

    def test_forwarded_header_ja(self):
        """Japanese forwarded message header should be reformatted."""
        text = "Yamada: 申し込んでみました さんが 3月13日 に #announcements で作成 : 本文です。 時刻 17:28。"
        result = parse_slack_message(text)
        self.assertIn("#announcements からの転送", result["body"])
        self.assertIn("申し込んでみました", result["body"])
        self.assertNotIn("さんが", result["body"])
        self.assertNotIn("で作成", result["body"])

    def test_real_forwarded_message_ja(self):
        """Real Japanese forwarded message from log should be reformatted."""
        text = (
            "サンプル太郎/Sample Taro/work-pc : "
            "申し込んでみました さんが 3月13日 に #announcements で作成 : "
            "本日は晴天なり。 "
            "時刻 17:28。 1 件のリアクション"
        )
        result = parse_slack_message(text)
        self.assertEqual(result["sender"], "サンプル太郎/Sample Taro/work-pc")
        self.assertIn("#announcements からの転送", result["body"])
        self.assertIn("申し込んでみました", result["body"])
        self.assertNotIn("さんが", result["body"])

    def test_forwarded_header_ja_with_author(self):
        """Japanese forwarded message with original author name should be reformatted."""
        text = (
            "サンプル太郎/Sample Taro/work-pc : "
            "本日は晴天なり サンプル次郎(さんぷるじろう)さんが 3月13日 に #sample-office で作成 : "
            "ご確認をお願いします。 "
            "時刻 18:19。 1 件のリアクション"
        )
        result = parse_slack_message(text)
        self.assertEqual(result["sender"], "サンプル太郎/Sample Taro/work-pc")
        self.assertIn("#sample-office からの転送", result["body"])
        self.assertIn("本日は晴天なり", result["body"])
        self.assertNotIn("さんが", result["body"])
        self.assertNotIn("で作成", result["body"])

    def test_attachment_ja_single(self):
        """Japanese message with a single file attachment should capture the count."""
        text = "サンプル太郎/Sample Taro/work-pc : テストです。 時刻 16:37。 1 件の添付ファイル。"
        result = parse_slack_message(text)
        self.assertEqual(result["sender"], "サンプル太郎/Sample Taro/work-pc")
        self.assertEqual(result["body"], "テストです")
        self.assertEqual(result["time"], "16:37")
        self.assertEqual(result["attachments"], "1")

    def test_attachment_ja_multiple(self):
        """Japanese message with multiple attachments should capture the count."""
        text = "Yamada: 資料です。 時刻 10:00。 3 件の添付ファイル。"
        result = parse_slack_message(text)
        self.assertEqual(result["attachments"], "3")

    def test_metadata_parsed_when_body_ends_with_paren(self):
        """本文が ) で終わるメッセージで時刻・リアクションが正しく抽出される（順序バグ再現）"""
        text = (
            "Yamada : 本文テキスト+1 絵文字) "
            "時刻 10:21。 4 個の絵文字リアクション、 1 件のリンク。"
        )
        result = parse_slack_message(text)
        self.assertEqual(result["time"], "10:21")
        self.assertNotIn("時刻", result["body"])
        self.assertNotIn("リアクション", result["body"])

    def test_metadata_parsed_when_body_ends_with_paren_real_case(self):
        """実際のNVDAテキスト形式で順序バグが再現・修正されることを確認"""
        text = (
            "サンプル太郎/Sample Taro 4/29休 : "
            "本文テキスト (本日は晴天なり+1 絵文字) "
            "時刻 10:21。 4 個の絵文字リアクション、 1 件のリンク。  レベル1"
        )
        result = parse_slack_message(text)
        self.assertEqual(result["time"], "10:21")
        self.assertNotIn("時刻", result["body"])
        self.assertNotIn("リアクション", result["body"])


class TestGetLevelFromObj(unittest.TestCase):
    """Tree level is announced by NVDA from positionInfo, not from message name.
    Sweeper cancels NVDA's auto-speech, so it must re-emit the level itself."""

    def test_level_extracted_from_positioninfo(self):
        obj = types.SimpleNamespace(
            positionInfo={"level": 1, "similarItemsInGroup": 5, "indexInGroup": 2}
        )
        self.assertEqual(_get_level_from_obj(obj), "1")

    def test_level_higher_value(self):
        obj = types.SimpleNamespace(positionInfo={"level": 3})
        self.assertEqual(_get_level_from_obj(obj), "3")

    def test_no_level_key(self):
        obj = types.SimpleNamespace(positionInfo={"similarItemsInGroup": 5})
        self.assertEqual(_get_level_from_obj(obj), "")

    def test_positioninfo_none(self):
        obj = types.SimpleNamespace(positionInfo=None)
        self.assertEqual(_get_level_from_obj(obj), "")

    def test_no_positioninfo_attr(self):
        obj = types.SimpleNamespace()
        self.assertEqual(_get_level_from_obj(obj), "")


class TestParseSlackMessageEn(unittest.TestCase):
    def test_full_message_with_metadata(self):
        text = "Yamada: Hello world. 2:01 PM. 1 link. 2 reactions."
        result = parse_slack_message(text)
        self.assertEqual(result["lang"], "en")
        self.assertEqual(result["sender"], "Yamada")
        self.assertEqual(result["time"], "2:01 PM")
        self.assertEqual(result["link_count"], "1")

    def test_unfurl_english(self):
        text = "Yamada: Check this [ Article (link)]. 2:01 PM."
        result = parse_slack_message(text)
        self.assertEqual(result["unfurl_titles"], ["Article"])
        self.assertIn("Check this", result["body"])

    def test_metadata_after_unfurl_block_en(self):
        """英語Slackでunfurlブロック直後（] の後）に時刻が来る場合のメタデータ解析"""
        text = (
            "サンプル太郎/Sample Taro/pc1: 英語のポストのテストです。"
            " [ XユーザーのExampleAppsさん: 「本日は晴天なり"
            " https://t.co/EXAMPLE0001」 / X (link)] 5:03 PM. 1 link, 1 attachment."
        )
        result = parse_slack_message(text)
        self.assertEqual(result["time"], "5:03 PM")
        self.assertEqual(result["link_count"], "1")
        self.assertEqual(result["attachments"], "1")
        self.assertNotIn("5:03 PM", result["body"])
        self.assertNotIn("1 link", result["body"])

    def test_mention_english(self):
        text = "Yamada mentioned you in #general: Hello. 2:01 PM."
        result = parse_slack_message(text)
        self.assertEqual(result["sender"], "Yamada")
        self.assertIn("Yamada", result["mention_info"])
        self.assertIn("general", result["mention_info"])

    def test_mention_english_thread(self):
        text = "Yamada mentioned you in thread in #general: Hello. 2:01 PM."
        result = parse_slack_message(text)
        self.assertEqual(result["sender"], "Yamada")
        self.assertIn("Yamada", result["mention_info"])
        self.assertIn("general", result["mention_info"])

    def test_replies_english(self):
        text = "Yamada: Hello. 2:01 PM. 3 replies."
        result = parse_slack_message(text)
        self.assertIn("3", result["replies"])

    def test_no_metadata_message(self):
        text = "Yamada: just a plain message"
        result = parse_slack_message(text)
        self.assertEqual(result["lang"], "en")
        self.assertEqual(result["sender"], "Yamada")
        self.assertEqual(result["body"], "just a plain message")

    def test_forwarded_header_en(self):
        """English forwarded message header should be reformatted."""
        text = "Yamada: I signed up on Mar 13th in #announcements: Body text. 5:28 PM."
        result = parse_slack_message(text)
        self.assertIn("Forwarded from #announcements", result["body"])
        self.assertIn("I signed up", result["body"])
        self.assertNotIn("on Mar", result["body"])

    def test_real_forwarded_message_en(self):
        """Real English forwarded message from log should be reformatted."""
        text = (
            "サンプル太郎/Sample Taro/work-pc: "
            "申し込んでみました on Mar 13th in #announcements: "
            "本日は晴天なり。 "
            "5:28 PM. 1 reaction."
        )
        result = parse_slack_message(text)
        self.assertEqual(result["sender"], "サンプル太郎/Sample Taro/work-pc")
        self.assertIn("Forwarded from #announcements", result["body"])
        self.assertIn("申し込んでみました", result["body"])

    def test_no_false_positive_on_normal_message(self):
        """Normal English message with 'on' and 'in' should not be affected."""
        text = "Yamada: I worked on this task in the morning. 2:01 PM."
        result = parse_slack_message(text)
        self.assertNotIn("Forwarded from", result["body"])
        self.assertIn("I worked on this task", result["body"])

    def test_forwarded_header_absent(self):
        """Message without forwarded header should be unchanged."""
        text = "Yamada: 普通のメッセージです。 時刻 12:10。"
        result = parse_slack_message(text)
        self.assertNotIn("からの転送", result["body"])
        self.assertIn("普通のメッセージです", result["body"])

    def test_attachment_en_single(self):
        """English message with a single file attachment should capture the count."""
        text = "Yamada: Testing. 4:37 PM. 1 attachment."
        result = parse_slack_message(text)
        self.assertEqual(result["sender"], "Yamada")
        self.assertEqual(result["body"], "Testing")
        self.assertEqual(result["time"], "4:37 PM")
        self.assertEqual(result["attachments"], "1")

    def test_attachment_en_multiple(self):
        """English message with multiple attachments should capture the count."""
        text = "Yamada: Files. 10:00 AM. 3 attachments."
        result = parse_slack_message(text)
        self.assertEqual(result["attachments"], "3")


class TestCleanMessageBodyI18n(unittest.TestCase):
    def test_japanese_expanded_emoji_only_kept(self):
        """Emoji-only message should be kept even with many emoji."""
        parts = [f"x{i} 絵文字" for i in range(15)]
        text = " ".join(parts)
        result = clean_message_body(text, lang="ja")
        self.assertIn("絵文字", result)

    def test_japanese_expanded_emoji_mixed_with_text_removed(self):
        """Mixed emoji+text message should still remove emoji above threshold."""
        parts = [f"x{i} 絵文字" for i in range(15)]
        text = "important message " + " ".join(parts)
        result = clean_message_body(text, lang="ja")
        self.assertNotIn("絵文字", result)
        self.assertIn("important", result)

    def test_english_expanded_emoji_only_kept(self):
        """English emoji-only message should be kept."""
        parts = [f"x{i} emoji" for i in range(15)]
        text = " ".join(parts)
        result = clean_message_body(text, lang="en")
        self.assertIn("emoji", result)

    def test_japanese_default_lang(self):
        """lang省略時は 'ja' がデフォルト（後方互換）— 絵文字のみは保持"""
        parts = [f"x{i} 絵文字" for i in range(15)]
        text = " ".join(parts)
        result = clean_message_body(text)
        self.assertIn("絵文字", result)


class TestGitHubUrlParsing(unittest.TestCase):
    def test_pull_request(self):
        url = "https://github.com/kinto-technologies/sample-repo/pull/2720"
        self.assertEqual(_title_from_github_url(url), "sample-repo PR #2720")

    def test_issue(self):
        url = "https://github.com/owner/my-repo/issues/42"
        self.assertEqual(_title_from_github_url(url), "my-repo Issue #42")

    def test_commit(self):
        url = "https://github.com/owner/repo/commit/abc1234def5678"
        self.assertEqual(_title_from_github_url(url), "repo commit abc1234")

    def test_repo_only(self):
        url = "https://github.com/owner/repo"
        self.assertEqual(_title_from_github_url(url), "repo")

    def test_non_github(self):
        url = "https://example.com/page"
        self.assertIsNone(_title_from_github_url(url))


class TestTwitterPattern(unittest.TestCase):
    def test_matches_x_com_status(self):
        url = "https://x.com/example_qa/status/1234567890000000001?s=46"
        self.assertIsNotNone(TWITTER_PATTERN.match(url))

    def test_matches_twitter_com_status(self):
        url = "https://x.com/example_user/status/1234567890000000002"
        self.assertIsNotNone(TWITTER_PATTERN.match(url))

    def test_matches_www_x_com(self):
        url = "https://www.x.com/user/status/123456"
        self.assertIsNotNone(TWITTER_PATTERN.match(url))

    def test_no_match_x_com_home(self):
        url = "https://x.com/home"
        self.assertIsNone(TWITTER_PATTERN.match(url))

    def test_no_match_github(self):
        url = "https://github.com/user/repo"
        self.assertIsNone(TWITTER_PATTERN.match(url))


class TestUrlPatternExclusions(unittest.TestCase):
    def test_tco_url_with_trailing_kagikako_is_not_matched(self):
        """URL_PATTERN should stop before 」 so t.co URLs inside 「...」 are clean."""
        text = "https://t.co/EXAMPLE0002」 / X"
        matches = URL_PATTERN.findall(text)
        self.assertEqual(matches, ["https://t.co/EXAMPLE0002"])

    def test_normal_url_still_matched(self):
        text = "check https://example.com/page here"
        self.assertIn("https://example.com/page", URL_PATTERN.findall(text))


class TestParseSlackXUnfurlJa(unittest.TestCase):
    # Shape mirrors a real NVDA log capture; message content is fictionalized.
    _OBJ_NAME = (
        "サンプル太郎/Sample Taro/pc1 : テストです。"
        " [ (1) Xユーザーのサンプル太郎さん: 「本日は晴天なり。"
        " https://t.co/EXAMPLE0002」 / X (リンク)] 時刻 16:11。 1 件のリンク、 1 件の添付ファイル。"
    )

    def test_tweet_text_extracted_as_unfurl_title(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertEqual(len(result["unfurl_titles"]), 1)
        self.assertIn("本日は晴天なり", result["unfurl_titles"][0])
        self.assertNotIn("Xユーザーの", result["unfurl_titles"][0])

    def test_tco_url_stripped_from_unfurl_title(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertNotIn("t.co", result["unfurl_titles"][0])

    def test_x_card_not_left_in_body(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertNotIn("Xユーザーの", result["body"])
        self.assertNotIn("/ X", result["body"])

    def test_no_stray_urls_extracted(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertEqual(result["urls"], [])

    def test_body_is_message_text_only(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertEqual(result["body"], "テストです")

    def test_sender_parsed(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertEqual(result["sender"], "サンプル太郎/Sample Taro/pc1")

    def test_metadata_parsed(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertEqual(result["time"], "16:11")
        self.assertEqual(result["link_count"], "1")
        self.assertEqual(result["attachments"], "1")


class TestParseSlackXUnfurlEnUi(unittest.TestCase):
    """英語 Slack UI（時刻が AM/PM 形式）でも X カードからツイート本文が抽出されること。
    X カードの文字列自体は日本語形式のまま。実ログの形式を模した（本文は架空）。"""
    _OBJ_NAME = (
        "サンプル太郎/Sample Taro/pc1: 英語のポストのテストです。"
        " [ XユーザーのExampleAppsさん: 「本日は晴天なり"
        " https://t.co/EXAMPLE0001」 / X (link)] 5:03 PM. 1 link, 1 attachment."
    )

    def test_lang_detected_as_en(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertEqual(result["lang"], "en")

    def test_tweet_text_extracted_not_full_card(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertEqual(len(result["unfurl_titles"]), 1)
        self.assertNotIn("Xユーザーの", result["unfurl_titles"][0])
        self.assertIn("本日は晴天なり", result["unfurl_titles"][0])

    def test_tco_url_stripped_from_title(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertNotIn("t.co", result["unfurl_titles"][0])

    def test_metadata_parsed(self):
        result = parse_slack_message(self._OBJ_NAME)
        self.assertEqual(result["time"], "5:03 PM")
        self.assertEqual(result["link_count"], "1")
        self.assertEqual(result["attachments"], "1")


if __name__ == "__main__":
    unittest.main()
