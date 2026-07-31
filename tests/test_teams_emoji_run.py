# -*- coding: utf-8 -*-
"""Teams-shaped regression: run-based emoji detection applies to Teams input.

Investigation: Teams exposes emoji in
the accessible-name text that `parse_teams_message` reads as literal Unicode
emoji glyphs (e.g. tests/test_parse_teams_message.py::test_no_url_emoji_body_extracted
asserts "👍" survives into parsed["body"]). Teams does not emit Slack-style
colon shortcodes or "name 絵文字" expanded tokens in that text. Unicode is one
of the three forms `clean_message_body` already recognizes, so no extra
Teams-specific logic is needed -- this test just pins that behavior so a
regression to total-count detection would be caught here too.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon'))

from shared.cleaner import clean_message_body


class TestTeamsEmojiRun(unittest.TestCase):
    def test_teams_status_schedule_kept(self):
        # Fictional weekly work-location schedule, as Teams would surface it
        # in a grouping's accessible name: one isolated Unicode emoji per
        # weekday, separated by day labels. Each run length is 1 (< threshold
        # 3), so every emoji must be kept and nothing recorded as skipped.
        text = "今週の勤務予定: 月 \U0001F3E0 火 \U0001F3E2 水 \U0001F3E0 木 \U0001F3E2 金 \U0001F3E0"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertIn("\U0001F3E0", result.text)  # home-office marker (kept)
        self.assertIn("\U0001F3E2", result.text)  # on-site marker (kept)
        self.assertIn("月", result.text)
        self.assertIn("金", result.text)
        self.assertEqual(result.skipped_emoji, {})

    def test_teams_decoration_run_removed(self):
        # Fictional celebratory message: 4 consecutive Unicode emoji with no
        # text between them form one run of weight 4 (>= threshold 3), so the
        # whole run is summarized away while the surrounding text is kept.
        text = "プロジェクト完了おめでとう \U0001F389\U0001F389\U0001F389\U0001F389 最高でした"
        result = clean_message_body(text, lang="ja", threshold=3)
        self.assertNotIn("\U0001F389", result.text)
        self.assertIn("おめでとう", result.text)
        self.assertIn("最高でした", result.text)
        self.assertTrue(result.skipped_emoji)


if __name__ == "__main__":
    unittest.main()
