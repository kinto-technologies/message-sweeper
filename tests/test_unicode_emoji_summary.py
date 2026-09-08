# -*- coding: utf-8 -*-
"""絵文字サマリーが Unicode 絵文字を1文字単位で数えることを固定する。

除去したランを丸ごと1つの名前にすると、サマリーがそのランを並べ直して読み上げ、
本文から消した意味が打ち消される（個数も常に「1こ」になる）。名前は絵文字1文字、
個数はその出現回数であること。絵文字の名前の表は同梱せず、NVDA 自身の記号辞書に
読ませる前提なので、名前は絵文字の文字そのものを使う。

絵文字はソースに直接書かずコードポイントで書く（addon/shared/patterns.py と同じ流儀）。
"""
import sys
import os
import builtins
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon'))

if "_" not in dir(builtins):
    builtins._ = lambda x: x

from shared.cleaner import clean_message_body, format_emoji_summary
from shared.patterns import _unicode_glyph_count

BLUE = "\U0001F535"          # large blue circle
PARTY = "\U0001F389"         # party popper
SPARKLES = "\u2728"          # sparkles
MIC = "\U0001F3A4"           # microphone
HEART_VS = "\u2764\ufe0f"    # heavy black heart + variation selector-16
DEVELOPER = "\U0001F468\u200d\U0001F4BB"  # man + ZWJ + laptop


class TestUnicodeEmojiSummaryCount(unittest.TestCase):
    def test_identical_run_named_once_and_counted(self):
        text = "テスト1 お知らせです " + BLUE * 13 + " よろしくお願いします"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertEqual(result.text, "テスト1 お知らせです よろしくお願いします")
        self.assertEqual(result.skipped_emoji, {BLUE: 13})
        self.assertEqual(
            format_emoji_summary(result.skipped_emoji, lang="ja"),
            "メッセージの絵文字: " + BLUE + "13こ",
        )

    def test_mixed_run_split_per_emoji(self):
        text = "テスト3 今日は" + PARTY + SPARKLES + MIC + "です"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertEqual(result.text, "テスト3 今日はです")
        self.assertEqual(
            list(result.skipped_emoji.items()),
            [(PARTY, 1), (SPARKLES, 1), (MIC, 1)],
        )
        self.assertEqual(
            format_emoji_summary(result.skipped_emoji, lang="ja"),
            "メッセージの絵文字: " + PARTY + "1こ、" + SPARKLES + "1こ、" + MIC + "1こ",
        )

    def test_variation_selector_counted_as_one(self):
        text = "お知らせ " + HEART_VS * 3 + " です"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertEqual(result.skipped_emoji, {HEART_VS: 3})

    def test_zwj_sequence_counted_as_one(self):
        text = "お知らせ " + DEVELOPER * 3 + " です"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertEqual(result.skipped_emoji, {DEVELOPER: 3})

    def test_separate_runs_of_same_emoji_added_up(self):
        text = BLUE * 3 + " 中 " + BLUE * 3
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertEqual(result.text, "中")
        self.assertEqual(result.skipped_emoji, {BLUE: 6})

    def test_summary_total_matches_glyph_count(self):
        run = PARTY + SPARKLES + MIC + DEVELOPER + HEART_VS + BLUE * 4
        result = clean_message_body("お知らせ " + run + " です", lang="ja", threshold=3)
        self.assertEqual(
            sum(result.skipped_emoji.values()), _unicode_glyph_count(run)
        )

    def test_expanded_label_path_unchanged(self):
        """Slack の畳みラベル経路は既に正しいので出力を変えない"""
        text = "お知らせ 13 large blue circle 絵文字 です"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertEqual(result.text, "お知らせ です")
        self.assertEqual(result.skipped_emoji, {"large blue circle": 13})


if __name__ == "__main__":
    unittest.main()
