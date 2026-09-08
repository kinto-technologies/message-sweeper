# -*- coding: utf-8 -*-
"""絵文字ラベルの取りこぼしの回帰テスト（Issue #21 と #28）。

Issue #21 の穴①: 同一の絵文字が3個以上並ぶと個数入りの1ラベルに畳まれる
（「13 青い丸 絵文字」）。個数がランの重みとして解釈されず、本文に「13 青い」の
ような断片が残っていた。

Issue #21 の穴②: ラベルが漢字3文字以上（紙吹雪）や3語以上（flag of Japan）だと
末尾だけがラベルと解釈され、先頭が本文に残っていた。

Issue #28: 実測すると Slack のラベル名は英語（large blue circle、tada）で、
本文とラベルの間に空白が入らない（今日はtada 絵文字sparkles 絵文字です）。
空白を左境界にしていた #21 の修正はこの形に一致せず、1.1.0 で除去できていた
ものが除去されなくなった。境界は空白ではなく文字種の切り替わりで取る。

ケース名（A〜H、EN-B、EN-E）は Issue #21、A〜D は Issue #28 の入力一覧に対応する。
"""
import sys
import os
import builtins
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon'))

# i18n stub（format_emoji_summary が _() を使う）
if "_" not in dir(builtins):
    builtins._ = lambda x: x

from shared.cleaner import clean_message_body, format_emoji_summary


class EmojiLabelCase(unittest.TestCase):
    """入力に対する本文とサマリーを一度に照合するための共通処理。"""

    def assertCleaned(self, text, lang, threshold, expected_text, expected_summary):
        result = clean_message_body(text, lang=lang, threshold=threshold)
        self.assertEqual(result.text, expected_text)
        self.assertEqual(
            format_emoji_summary(result.skipped_emoji, lang=lang),
            expected_summary,
        )


class TestCollapsedCountLabel(EmojiLabelCase):
    """穴①: 個数入りに畳まれたラベル。"""

    def test_collapsed_label_alone_is_removed_with_its_count(self):
        # A: 個数13がラン重みになるのでしきい値3に届き、断片も残らない
        self.assertCleaned(
            "お知らせです 13 青い丸 絵文字 よろしくお願いします",
            "ja", 3,
            "お知らせです よろしくお願いします",
            "メッセージの絵文字: 青い丸13こ",
        )

    def test_collapsed_label_alone_threshold_one(self):
        # B: しきい値1でも同じ結果になる（しきい値では回避できない不具合だった）
        self.assertCleaned(
            "お知らせです 13 青い丸 絵文字 よろしくお願いします",
            "ja", 1,
            "お知らせです よろしくお願いします",
            "メッセージの絵文字: 青い丸13こ",
        )

    def test_collapsed_label_in_run_counts_as_its_count(self):
        # E: 畳みラベル＋通常ラベル2個。サマリーの個数が実際の個数と一致する
        self.assertCleaned(
            "案内です 13 青い丸 絵文字 クラッカー 絵文字 ピカピカ 絵文字 以上です",
            "ja", 3,
            "案内です 以上です",
            "メッセージの絵文字: 青い丸13こ、クラッカー1こ、ピカピカ1こ",
        )

    def test_collapsed_label_below_threshold_leaves_no_fragment(self):
        # 個数がしきい値未満のラベルは除去しないが、本文に断片も残さない
        self.assertCleaned(
            "お知らせです 2 青い丸 絵文字 よろしくお願いします",
            "ja", 3,
            "お知らせです 2 青い丸 絵文字 よろしくお願いします",
            "",
        )

    def test_collapsed_label_in_run_en(self):
        # EN-B: 英語でも個数を重みとして数える
        self.assertCleaned(
            "Heads up 13 blue circle emoji party popper emoji sparkles emoji done",
            "en", 3,
            "Heads up done",
            "Emoji in message: blue circle 13, party popper 1, sparkles 1",
        )


class TestLongLabel(EmojiLabelCase):
    """穴②: 3文字以上・3語以上のラベル。"""

    def test_three_kanji_label_alone_leaves_no_fragment(self):
        # C: 孤立した絵文字1個はしきい値未満なので残す。断片「紙」を作らないこと
        self.assertCleaned(
            "受付を開始しました 紙吹雪 絵文字 ご確認ください",
            "ja", 3,
            "受付を開始しました 紙吹雪 絵文字 ご確認ください",
            "",
        )

    def test_three_kanji_label_in_run_removed_whole(self):
        # F: ラベル全体が除去され、サマリーの名前も「紙吹雪」になる
        self.assertCleaned(
            "案内です 紙吹雪 絵文字 クラッカー 絵文字 ピカピカ 絵文字 以上です",
            "ja", 3,
            "案内です 以上です",
            "メッセージの絵文字: 紙吹雪1こ、クラッカー1こ、ピカピカ1こ",
        )

    def test_three_word_label_in_run_removed_whole_en(self):
        # EN-E: 「flag」だけが本文に残らず、名前も「flag of Japan」になる
        self.assertCleaned(
            "Heads up flag of Japan emoji party popper emoji sparkles emoji done",
            "en", 3,
            "Heads up done",
            "Emoji in message: flag of Japan 1, party popper 1, sparkles 1",
        )


class TestEnglishLabelFromSlack(EmojiLabelCase):
    """Issue #28: 実測どおりの形（ラベル名が英語、本文と密着）。

    日本語文字の直後から終端「絵文字」までには ASCII しか現れないので、
    この経路では語数の上限を置かずにラベル領域を丸ごと取れる。
    """

    def test_space_separated_collapsed_label(self):
        # A: 個数入りに畳まれた3語ラベル。空白区切りでも丸ごと取る
        self.assertCleaned(
            "お知らせです 13 large blue circle 絵文字 よろしくお願いします",
            "ja", 3,
            "お知らせです よろしくお願いします",
            "メッセージの絵文字: large blue circle13こ",
        )

    def test_space_separated_two_word_label_alone(self):
        # B: 孤立した絵文字1個はしきい値未満なので残す。断片も作らない
        self.assertCleaned(
            "受付を開始しました confetti ball 絵文字 ご確認ください",
            "ja", 3,
            "受付を開始しました confetti ball 絵文字 ご確認ください",
            "",
        )

    def test_labels_adjacent_to_body_text_are_removed(self):
        # C: 1.1.0 で除去できていた形。この一致が #27 の回帰解消の判定
        self.assertCleaned(
            "今日はtada 絵文字sparkles 絵文字microphone 絵文字です",
            "ja", 3,
            "今日はです",
            "メッセージの絵文字: tada1こ、sparkles1こ、microphone1こ",
        )

    def test_collapsed_label_adjacent_to_body_text(self):
        # D: 密着した畳みラベル。個数13がランの重みになる
        self.assertCleaned(
            "進捗は13 large blue circle 絵文字です",
            "ja", 3,
            "進捗はです",
            "メッセージの絵文字: large blue circle13こ",
        )


class TestKatakanaLabelBoundary(EmojiLabelCase):
    """カタカナのラベルも文字種の切り替わりで境界を取る。

    カタカナ以外の文字の直後を起点として許す。カタカナだけを許容する
    クラスなので、漢字やひらがなの本文を飲み込むことはない。
    """

    def test_katakana_label_adjacent_to_body_text(self):
        self.assertCleaned(
            "今日はクラッカー 絵文字ピカピカ 絵文字マイク 絵文字です",
            "ja", 3,
            "今日はです",
            "メッセージの絵文字: クラッカー1こ、ピカピカ1こ、マイク1こ",
        )


class TestNoOverMatch(EmojiLabelCase):
    """番犬: 許容文字を広げても本文をラベル名として飲み込まないこと。"""

    def test_body_text_before_label_is_kept(self):
        # G: ラベルの左境界（行頭または空白の直後）を守る
        self.assertCleaned(
            "全社会議の資料共有 紙吹雪 絵文字 以上です",
            "ja", 3,
            "全社会議の資料共有 紙吹雪 絵文字 以上です",
            "",
        )

    def test_body_text_before_removed_label_is_kept(self):
        # G のしきい値1版。除去が起きる条件でも本文は削られない
        self.assertCleaned(
            "全社会議の資料共有 紙吹雪 絵文字 以上です",
            "ja", 1,
            "全社会議の資料共有 以上です",
            "メッセージの絵文字: 紙吹雪1こ",
        )

    def test_english_body_sentence_is_kept_en(self):
        # 英語 UI（終端が emoji）の経路は現状維持。本文の語を消さない
        self.assertCleaned(
            "Please review the report emoji",
            "en", 3,
            "Please review the report emoji",
            "",
        )

    def test_english_body_word_separated_by_japanese_is_kept(self):
        # 日本語がラベルの直前にある形。英単語 Slack は本文として残る
        self.assertCleaned(
            "修正は Slack のみ tada 絵文字sparkles 絵文字microphone 絵文字です",
            "ja", 3,
            "修正は Slack のみ です",
            "メッセージの絵文字: tada1こ、sparkles1こ、microphone1こ",
        )

    def test_ascii_only_lead_keeps_the_two_word_limit(self):
        # ラベルの手前が ASCII だけの場合は左端を決められないので、上限2語の
        # まま据え置く。ここを広げると英語の本文語を飲み込む。
        # 期待値は現在の出力そのままで、この修正で悪化しないことを固定する。
        self.assertCleaned(
            "Please review the report tada 絵文字sparkles 絵文字microphone 絵文字 done",
            "ja", 3,
            "Please review the done",
            "メッセージの絵文字: report tada1こ、sparkles1こ、microphone1こ",
        )


class TestJuxtaposedLabels(EmojiLabelCase):
    """ラベルの左境界は、直前のラベルの「絵文字」の直後も認めること。

    Slack は「ok 絵文字wfh 絵文字」のようにラベルを空白なしで並べることがある。
    境界を空白と行頭だけに限ると、2個目以降がラベルと解釈されずランが途切れ、
    連続した装飾絵文字が除去されなくなる。
    """

    def test_run_of_labels_without_spaces_is_removed(self):
        self.assertCleaned(
            "重要なお知らせ ok 絵文字wfh 絵文字kaishi 絵文字",
            "ja", 3,
            "重要なお知らせ",
            "メッセージの絵文字: ok1こ、wfh1こ、kaishi1こ",
        )


class TestUnchangedBehavior(EmojiLabelCase):
    """回帰防止: 現状で正しく動いている形を変えないこと。"""

    def test_three_different_labels_removed(self):
        # D
        self.assertCleaned(
            "案内です クラッカー 絵文字 ピカピカ 絵文字 マイク 絵文字 以上です",
            "ja", 3,
            "案内です 以上です",
            "メッセージの絵文字: クラッカー1こ、ピカピカ1こ、マイク1こ",
        )

    def test_three_identical_labels_not_collapsed_by_slack(self):
        # H: 畳まれていない同一ラベル3個は3個として数える
        self.assertCleaned(
            "案内です ピカピカ 絵文字 ピカピカ 絵文字 ピカピカ 絵文字 以上です",
            "ja", 3,
            "案内です 以上です",
            "メッセージの絵文字: ピカピカ3こ",
        )


if __name__ == "__main__":
    unittest.main()
