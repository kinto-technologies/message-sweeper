# -*- coding: utf-8 -*-
"""Unit tests for consecutive-emoji-run detection."""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon'))
from shared.cleaner import _remove_emoji_runs


class TestRemoveEmojiRuns(unittest.TestCase):
    def _run(self, text, lang="ja", threshold=3):
        skipped = {}
        out = _remove_emoji_runs(text, lang, threshold, skipped)
        return out, skipped

    def test_isolated_colon_emoji_kept(self):
        # 各日付に絵文字1個 = ラン長1 → すべて残す（再現バグの核心）
        text = "7/27（月）:wfh: 7/28（火）:office_x: 7/29（水）:am:"
        out, skipped = self._run(text)
        self.assertIn(":wfh:", out)
        self.assertIn(":office_x:", out)
        self.assertIn(":am:", out)
        self.assertEqual(skipped, {})

    def test_consecutive_colon_run_removed(self):
        text = "hello :a: :b: :c: world"
        out, skipped = self._run(text)
        self.assertNotIn(":a:", out)
        self.assertIn("hello", out)
        self.assertIn("world", out)
        self.assertEqual(skipped, {"a": 1, "b": 1, "c": 1})

    def test_two_consecutive_colon_kept(self):
        text = "hi :a: :b: bye"
        out, skipped = self._run(text)
        self.assertIn(":a:", out)
        self.assertIn(":b:", out)
        self.assertEqual(skipped, {})

    def test_unicode_run_removed(self):
        text = "yay \U0001F389\U0001F389\U0001F389 done"
        out, skipped = self._run(text)
        self.assertNotIn("\U0001F389", out)
        self.assertIn("yay", out)
        self.assertIn("done", out)

    def test_unicode_checklist_kept(self):
        # ✅/❌ を各行1個、テキストで隔てられる → 各ラン長1 → 残す
        text = "✅ taskA done ❌ taskB ng ✅ taskC done ❌ taskD ng ✅ taskE"
        out, skipped = self._run(text)
        self.assertIn("✅", out)
        self.assertIn("❌", out)
        self.assertEqual(skipped, {})

    def test_zwj_sequence_counts_as_one(self):
        # 家族絵文字(ZWJ結合)は1グリフ。単独出現ならラン長1 → 残す
        family = "\U0001F468‍\U0001F469‍\U0001F467"
        text = "family " + family + " here"
        out, skipped = self._run(text)
        self.assertIn(family, out)
        self.assertEqual(skipped, {})

    def test_mixed_type_run_removed(self):
        text = "wow :a: \U0001F389 :b: end"  # colon,uni,colon 連続 = ラン長3
        out, skipped = self._run(text)
        self.assertNotIn(":a:", out)
        self.assertNotIn("\U0001F389", out)
        self.assertIn("wow", out)
        self.assertIn("end", out)

    def test_text_between_breaks_run(self):
        text = ":a: x :b: y :c:"  # 各絵文字がテキストで分断 → ラン長1 ×3 → 残す
        out, skipped = self._run(text)
        self.assertIn(":a:", out)
        self.assertIn(":c:", out)
        self.assertEqual(skipped, {})


if __name__ == "__main__":
    unittest.main()
