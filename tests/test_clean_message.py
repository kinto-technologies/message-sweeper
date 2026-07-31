# -*- coding: utf-8 -*-
"""Tests for clean_message_body emoji threshold logic."""
import sys
import os
import unittest

# addon/ を sys.path に追加して shared.cleaner をインポート可能にする
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon'))

from shared.cleaner import clean_message_body, CleanResult


class TestEmojiThreshold(unittest.TestCase):
    """Consecutive emoji runs of 5+ should be removed; fewer should be kept."""

    def test_four_consecutive_expanded_emoji_kept(self):
        """4 consecutive expanded emojis (like morning greetings) should be kept."""
        text = "ohayougozaimasu 絵文字 wfh 絵文字 kinmukaishi 絵文字 desu 絵文字"
        result = clean_message_body(text)
        self.assertIn("絵文字", result)
        self.assertTrue(len(result.strip()) > 0)

    def test_few_expanded_emoji_kept_due_to_greedy_match(self):
        """EXPANDED_EMOJI_PATTERN greedily matches up to 5 words before 絵文字,
        so 5 emoji entries collapse into 2 regex matches — below threshold, kept."""
        text = "a 絵文字 b 絵文字 c 絵文字 d 絵文字 e 絵文字"
        result = clean_message_body(text)
        self.assertIn("絵文字", result)

    def test_many_expanded_emoji_removed_when_enough_matches(self):
        """With enough emoji entries to produce 5+ regex matches, they get removed.
        Each match consumes up to 5 words, so we need many entries."""
        # 15 entries -> at least 5 greedy matches
        # テキストも混在させて絵文字オンリー判定に引っかからないようにする
        parts = [f"x{i} 絵文字" for i in range(15)]
        text = "important message " + " ".join(parts)
        result = clean_message_body(text)
        self.assertNotIn("絵文字", result)

    def test_scattered_emoji_kept(self):
        """Emojis scattered across text with content between should be kept."""
        text = "行1 ok 絵文字 ここはテキスト。行2 good 絵文字 ここもテキスト。行3 nice 絵文字"
        result = clean_message_body(text)
        self.assertIn("テキスト", result)
        self.assertIn("絵文字", result)

    def test_emoji_only_japanese_morning_short_kept(self):
        """Short emoji-only Japanese morning greeting should not be emptied."""
        text = "ohayougozaimasu 絵文字wfh kaishi 絵文字desu 絵文字"
        result = clean_message_body(text)
        self.assertTrue(len(result.strip()) > 0)

    def test_emoji_only_japanese_morning_long_kept(self):
        """Long emoji-only Japanese morning greeting should not be emptied."""
        text = "ohayougozaimasu 絵文字 home office 絵文字 kinmukaishi 絵文字"
        result = clean_message_body(text)
        self.assertTrue(len(result.strip()) > 0)

    def test_emoji_only_message_above_threshold_kept(self):
        """Emoji-only message (5+ emoji, no text) should NOT be removed."""
        text = "ohayougozaimasu 絵文字officework 絵文字kaishi 絵文字desu 絵文字amefuri 絵文字"
        result = clean_message_body(text)
        self.assertIn("絵文字", result)
        self.assertTrue(len(result.strip()) > 0)

    def test_emoji_with_text_above_threshold_removed(self):
        """Mixed emoji+text message should still remove emoji when above threshold."""
        parts = [f"x{i} 絵文字" for i in range(15)]
        text = "important message " + " ".join(parts)
        result = clean_message_body(text)
        self.assertIn("important", result)
        self.assertNotIn("絵文字", result)

    def test_four_consecutive_colon_emoji_removed(self):
        """4 consecutive colon emoji after text = decoration run -> removed."""
        text = "hello :wave: :smile: :thumbsup: :heart:"
        result = clean_message_body(text, threshold=3)
        self.assertNotIn(":wave:", result)
        self.assertIn("hello", result)

    def test_five_consecutive_colon_emoji_only_kept(self):
        """5+ consecutive colon-style emojis (emoji-only message) should be kept."""
        text = ":wave: :smile: :thumbsup: :heart: :fire:"
        result = clean_message_body(text)
        self.assertIn(":wave:", result)

    def test_four_consecutive_unicode_emoji_removed(self):
        """4 consecutive Unicode emoji after text = decoration run -> removed."""
        text = "good morning \U0001F600 \U0001F601 \U0001F602 \U0001F603"
        result = clean_message_body(text, threshold=3)
        self.assertNotIn("\U0001F600", result)
        self.assertIn("morning", result)

    def test_five_consecutive_unicode_emoji_only_kept(self):
        """5+ consecutive Unicode emojis (emoji-only message) should be kept."""
        text = "\U0001F600 \U0001F601 \U0001F602 \U0001F603 \U0001F604"
        result = clean_message_body(text)
        self.assertIn("\U0001F600", result)

    def test_text_with_no_emoji_unchanged(self):
        """Plain text should pass through unchanged."""
        text = "おはようございます。今日もよろしく。"
        result = clean_message_body(text)
        self.assertEqual(result, "おはようございます。今日もよろしく。")

    def test_empty_string(self):
        """Empty string should return empty."""
        self.assertEqual(clean_message_body(""), "")

    def test_channel_mentions_preserved(self):
        """Channel mentions should be preserved even near emojis."""
        text = "#general a 絵文字 b 絵文字 c 絵文字"
        result = clean_message_body(text)
        self.assertIn("#general", result)

    def test_consecutive_same_colon_emoji_removed(self):
        """3+ identical consecutive colon emoji form a decoration run and are
        removed once the run length reaches threshold."""
        text = "hello :custom-icon::custom-icon::custom-icon: world"
        result = clean_message_body(text, threshold=3)
        self.assertNotIn(":custom-icon:", result)
        self.assertIn("hello", result)
        self.assertIn("world", result)

    def test_consecutive_same_colon_emoji_with_spaces_removed(self):
        """3+ identical colon emoji with spaces form a decoration run and are
        removed once the run length reaches threshold."""
        text = "hello :custom-icon: :custom-icon: :custom-icon: world"
        result = clean_message_body(text, threshold=3)
        self.assertNotIn(":custom-icon:", result)

    def test_different_colon_emoji_below_threshold_kept(self):
        """2 different colon emoji should be kept (below threshold, not consecutive same)."""
        text = "hello :wave: :smile:"
        result = clean_message_body(text)
        self.assertIn(":wave:", result)
        self.assertIn(":smile:", result)

    def test_status_emoji_schedule_kept_in_place(self):
        """予定表: 各行の絵文字はラン長1なので残り、位置関係が保たれる。"""
        text = (
            "来週の予定です。 "
            "7/27（月）:wfh: 7/28（火）:office_x: "
            "7/29（水）:am: のあと、:wfh: 7/30（木）:office_x: 7/31（金）:wfh:"
        )
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertIn(":wfh:", result)
        self.assertIn(":office_x:", result)
        self.assertIn(":am:", result)
        self.assertEqual(result.skipped_emoji, {})

    def test_time_token_not_removed(self):
        """8:15 のような時刻もどきは絵文字として消えない。"""
        text = "集合は8:15分です。:wave:"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertIn("8:15", result)

    def test_hyphenated_colon_emoji_only_kept(self):
        """5+ different hyphenated colon emoji (emoji-only message) should be kept."""
        text = ":icon-red: :custom-icon: :icon-green: :icon-yellow: :icon-purple:"
        result = clean_message_body(text)
        self.assertIn(":icon-red:", result)

    def test_bold_markdown_stripped(self):
        """*bold* should become bold."""
        text = "これは *重要なお知らせ* です"
        result = clean_message_body(text)
        self.assertIn("重要なお知らせ", result)
        self.assertNotIn("*", result)

    def test_bold_no_false_positive_on_arithmetic(self):
        """Spaced asterisks like 2 * 3 * 4 should not be stripped."""
        text = "計算: 2 * 3 * 4 = 24"
        result = clean_message_body(text)
        self.assertIn("2 * 3 * 4", result)

    def test_italic_markdown_stripped(self):
        """_italic_ should become italic."""
        text = "これは _補足情報_ です"
        result = clean_message_body(text)
        self.assertIn("補足情報", result)
        self.assertNotIn("_補足", result)

    def test_italic_no_false_positive_on_snake_case(self):
        """snake_case_var should not be modified."""
        text = "変数名は snake_case_var です"
        result = clean_message_body(text)
        self.assertIn("snake_case_var", result)

    def test_strikethrough_markdown_stripped(self):
        """~strikethrough~ should become strikethrough."""
        text = "これは ~古い情報~ です"
        result = clean_message_body(text)
        self.assertIn("古い情報", result)
        self.assertNotIn("~", result)

    def test_combined_markdown_stripped(self):
        """Multiple markdown types in one message."""
        text = "*太字* と _斜体_ と ~取り消し~"
        result = clean_message_body(text)
        self.assertIn("太字", result)
        self.assertIn("斜体", result)
        self.assertIn("取り消し", result)
        self.assertNotIn("*", result)
        self.assertNotIn("~", result)

    def test_link_bracket_residual_removed_ja(self):
        """URL除去後の [ (リンク)] 残骸が除去される"""
        text = "[ (リンク)] テスト"
        result = clean_message_body(text)
        self.assertNotIn("[", result)
        self.assertNotIn("(リンク)", result)
        self.assertIn("テスト", result)

    def test_link_bracket_residual_removed_en(self):
        """URL除去後の [ (link)] 残骸が除去される"""
        text = "[ (link)] test"
        result = clean_message_body(text)
        self.assertNotIn("[", result)
        self.assertNotIn("(link)", result)
        self.assertIn("test", result)

    def test_real_quoted_message_decorations_stripped(self):
        """Quoted message (log-shaped, fictional content) should have decorations stripped."""
        text = (
            ":new3: *本日は晴天なり* "
            "@here _サンプル 太郎（人事） (管理部)_ "
            ":custom-icon::custom-icon::custom-icon::custom-icon::custom-icon::custom-icon:"
            ":custom-icon::custom-icon::custom-icon::custom-icon::custom-icon: "
            "ご確認をお願いします。"
        )
        result = clean_message_body(text)
        self.assertNotIn("*本日", result)
        self.assertNotIn(":custom-icon:", result)
        self.assertIn(":new3:", result)
        self.assertIn("本日は晴天なり", result)
        self.assertIn("サンプル 太郎（人事） (管理部)", result)
        self.assertIn("ご確認をお願いします。", result)
        self.assertIn("@here", result)


class TestCleanResult(unittest.TestCase):
    """clean_message_body should return CleanResult with skipped emoji info."""

    def test_returns_clean_result(self):
        result = clean_message_body("hello world")
        self.assertIsInstance(result, CleanResult)
        self.assertEqual(result.text, "hello world")
        self.assertEqual(result.skipped_emoji, {})

    def test_empty_string_returns_clean_result(self):
        result = clean_message_body("")
        self.assertIsInstance(result, CleanResult)
        self.assertEqual(result.text, "")
        self.assertEqual(result.skipped_emoji, {})

    def test_emoji_below_threshold_no_skip(self):
        text = "hello :wave: :smile: world"
        result = clean_message_body(text)
        self.assertIsInstance(result, CleanResult)
        self.assertIn(":wave:", result.text)
        self.assertEqual(result.skipped_emoji, {})

    def test_emoji_above_threshold_records_skipped(self):
        text = "message :a: :b: :c: :d: :e: end"
        result = clean_message_body(text)
        self.assertIsInstance(result, CleanResult)
        self.assertNotIn(":a:", result.text)
        self.assertIn("a", result.skipped_emoji)
        self.assertEqual(result.skipped_emoji["a"], 1)
        self.assertEqual(len(result.skipped_emoji), 5)

    def test_duplicate_emoji_counted(self):
        # :heart:x3 :smile:x2 は空白のみで連続 = 1つのラン(長さ5) -> 全除去
        text = "message :heart: :heart: :heart: :smile: :smile: end"
        result = clean_message_body(text, threshold=3)
        self.assertIsInstance(result, CleanResult)
        self.assertEqual(result.skipped_emoji.get("heart", 0), 3)
        self.assertEqual(result.skipped_emoji.get("smile", 0), 2)
        self.assertNotIn(":smile:", result.text)
        self.assertIn("message", result.text)
        self.assertIn("end", result.text)

    def test_emoji_only_message_no_skip(self):
        text = ":wave: :smile: :thumbsup: :heart: :fire:"
        result = clean_message_body(text)
        self.assertIsInstance(result, CleanResult)
        self.assertEqual(result.skipped_emoji, {})

    def test_custom_threshold(self):
        text = "hello :a: :b: :c: end"
        result = clean_message_body(text, threshold=3)
        self.assertIsInstance(result, CleanResult)
        self.assertNotIn(":a:", result.text)
        self.assertEqual(len(result.skipped_emoji), 3)


class TestEmojiEdgeCases(unittest.TestCase):
    def test_plus_one_expanded_emoji_removed_above_threshold(self):
        """+1 絵文字 が閾値超過時に除去される（+が文字クラスに含まれていないバグ）"""
        # 通常絵文字10個(greedyで5マッチ=閾値到達)＋+1 絵文字
        text = "テスト " + " ".join(f"x{i} 絵文字" for i in range(10)) + " +1 絵文字"
        result = clean_message_body(text, lang="ja", threshold=5)
        # "1 絵文字" だけ除去されて "+" が残骸として残るバグがないこと
        self.assertNotIn("+", result)
        self.assertIn("テスト", result)

    def test_multi_word_custom_emoji_fully_removed(self):
        """kyoumi ari 絵文字 のような2語カスタム絵文字が完全に除去される（残骸 "kyoumi" バグ）"""
        # 通常絵文字10個(greedyで5マッチ=閾値到達)＋2語カスタム絵文字
        text = "テスト " + " ".join(f"x{i} 絵文字" for i in range(10)) + " kyoumi ari 絵文字"
        result = clean_message_body(text, lang="ja", threshold=5)
        self.assertNotIn("kyoumi", result)
        self.assertIn("テスト", result)

    def test_plus_one_colon_emoji_removed_above_threshold(self):
        """:+1: コロン絵文字が閾値超過時に除去される"""
        text = "テスト :a: :b: :c: :d: :e: :+1:"
        result = clean_message_body(text, lang="ja", threshold=5)
        self.assertNotIn(":+1:", result)
        self.assertIn("テスト", result)

    def test_hiragana_sentence_preserved_before_katakana_emoji(self):
        """先頭の連続絵文字群は除去、末尾の孤立展開形は残す。
        いただきます(本文)は保持され、孤立した バンザイ 絵文字 は残る。"""
        text = "テスト " + " ".join(f"x{i} 絵文字" for i in range(10)) + " いただきますバンザイ 絵文字"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertIn("いただきます", result)
        self.assertNotIn("x0", result)  # 連続群は除去
        self.assertIn("バンザイ 絵文字", result)  # 孤立は保持

    def test_sentence_kanji_preserved_before_kanji_emoji(self):
        """先頭の連続絵文字群は除去、末尾の孤立展開形は残す。"""
        text = "テスト " + " ".join(f"x{i} 絵文字" for i in range(10)) + " 参加してみたい方挙手 絵文字"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertIn("参加してみたい方", result)
        self.assertNotIn("x0", result)
        self.assertIn("挙手 絵文字", result)


if __name__ == "__main__":
    unittest.main()
