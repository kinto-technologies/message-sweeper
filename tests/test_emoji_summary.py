# -*- coding: utf-8 -*-
"""Tests for format_emoji_summary."""
import sys
import os
import builtins
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon'))

# i18n stub
if "_" not in dir(builtins):
    builtins._ = lambda x: x

from shared.cleaner import format_emoji_summary


class TestFormatEmojiSummary(unittest.TestCase):

    def test_empty_dict_returns_empty(self):
        self.assertEqual(format_emoji_summary({}), "")

    def test_none_returns_empty(self):
        self.assertEqual(format_emoji_summary(None), "")

    def test_single_emoji_ja(self):
        result = format_emoji_summary({"スマイル": 3}, lang="ja")
        self.assertEqual(result, "メッセージの絵文字: スマイル3こ")

    def test_multiple_emoji_ja(self):
        result = format_emoji_summary({"スマイル": 3, "拍手": 2}, lang="ja")
        self.assertEqual(result, "メッセージの絵文字: スマイル3こ、拍手2こ")

    def test_single_emoji_en(self):
        result = format_emoji_summary({"smile": 3}, lang="en")
        self.assertEqual(result, "Emoji in message: smile 3")

    def test_multiple_emoji_en(self):
        result = format_emoji_summary({"smile": 3, "thumbsup": 2}, lang="en")
        self.assertEqual(result, "Emoji in message: smile 3, thumbsup 2")

    def test_preserves_insertion_order(self):
        from collections import OrderedDict
        emoji = OrderedDict([("heart", 1), ("smile", 2), ("wave", 3)])
        result = format_emoji_summary(emoji, lang="en")
        self.assertEqual(result, "Emoji in message: heart 1, smile 2, wave 3")


if __name__ == "__main__":
    unittest.main()
