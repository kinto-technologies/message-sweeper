# -*- coding: utf-8 -*-
"""Message body cleaning: emoji removal, decoration stripping."""
import re
from collections import namedtuple
from dataclasses import dataclass, field
from shared.patterns import (
    CHANNEL_MENTION_PATTERN,
    SLACK_BOLD_PATTERN, SLACK_ITALIC_PATTERN, SLACK_STRIKETHROUGH_PATTERN,
    _iter_unicode_glyphs,
)

LINK_BRACKET_RESIDUAL_PATTERN = re.compile(r'\[\s*\((?:リンク|link)\)\s*\]')
COLON_EMOJI_PATTERN = re.compile(r':[a-zA-Z0-9_\-+\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]+:')
UNICODE_EMOJI_PATTERN = re.compile('[\U0001F300-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\u2600-\u26FF\u2700-\u27BF\uFE00-\uFE0F\u200D\u20E3\u2B50\u23E9-\u23FA]+')
FULLWIDTH_DECORATION_PATTERN = re.compile('[\u2500-\u257F\u2580-\u259F\u25A0-\u25FF\u2190-\u21FF\u2200-\u22FF\u2010-\u2017\u2020-\u2025\u2027\u2030-\u205E\u2E00-\u2E4F\u02DA\u207A\u2605-\u2606\u2934-\u2935\uFF61-\uFF65\uFF0B\u0B60-\u0B7F]+')
ASCII_DECORATION_PATTERN = re.compile(r'[=\-~_]{5,}')

EMOJI_TOTAL_THRESHOLD = 3

# Expanded emoji labels: the "<label> 絵文字" / "<label> emoji" form used in
# _is_emoji_only and removal.
#
# Matching one has to thread between two failures. Too narrow, and a label it
# cannot cover in full leaves its head in the body ("紙" out of "紙吹雪") while
# the summary gets named after the tail. Too wide, and it reaches back over
# ordinary words before the label ("important message x0 絵文字"), which makes
# _is_emoji_only report a false positive and the removal swallow body text.
#
# What settles where a label starts is the switch in character class, not
# whitespace: Slack runs a label straight onto the body text ("今日はtada
# 絵文字") and onto the previous label's terminator ("絵文字sparkles"), so
# whitespace is not there to be relied on. Each kind of label therefore gets
# the left boundary its own character class can defend, and they are kept in
# separate patterns rather than one alternation — a label shape may only widen
# on the boundary that makes it safe.
_ASCII_EMOJI_WORD = r'[a-zA-Z0-9_\-+]{1,20}'
# Any number of ASCII words, for the boundary below where the run cannot reach
# body text: between a non-ASCII character and the terminator, only the label
# can appear. Emoji names run to five words ("smiling face with smiling eyes")
# and their length is not knowable in advance.
_ASCII_EMOJI_RUN = _ASCII_EMOJI_WORD + r'(?:\s+' + _ASCII_EMOJI_WORD + r')*'
# Up to two words, plus "of" as an internal connector so "flag of Japan" fits.
# This is the form for a label whose left side is ASCII too, where nothing says
# how far back the name reaches; widening it there would eat body words.
_ASCII_EMOJI_LABEL = (
    _ASCII_EMOJI_WORD + r'(?:\s+of)?(?:\s+' + _ASCII_EMOJI_WORD + r')?'
)
# Katakana labels ("クラッカー"), bounded to katakana so kanji and hiragana body
# text cannot be drawn in.
_KATAKANA_EMOJI_LABEL = r'[゠-ヿ]{1,8}'
# Labels that mix kanji and hiragana ("青い丸", "紙吹雪") cannot be told apart
# from Japanese body text by character class, so this one keeps a length bound
# and the whitespace boundary. A label run onto the body text is missed here
# (it gets read out as-is), which is better than eating the sentence in front
# of it.
_JA_EMOJI_LABEL = r'[ぁ-ゟ一-鿿]{1,8}'

# After any non-ASCII character, together with whatever whitespace follows it.
# This is what catches a label run onto Japanese body text; it also covers the
# terminator (絵文字 is non-ASCII) and the space-separated form.
_NON_ASCII_BOUNDARY = r'(?<=[^\x00-\x7f])\s*'
# After any non-katakana character, including the start of the text.
_NON_KATAKANA_BOUNDARY = r'(?<![゠-ヿ])'


def _whitespace_boundary(terminator):
    """Start of text, after whitespace, or right after a preceding terminator.

    The boundary for label shapes that no character class can delimit, where
    only whitespace says a name has started.
    """
    return r'(?:(?<![^\s])|(?<=' + terminator + r'))'


def _expanded_emoji_pattern(boundary, label, terminator):
    """Compile one expanded-label matcher.

    `boundary` decides where a label is allowed to start, `label` what it may
    contain, `terminator` the word that follows the name. The `atom` group is
    the label region itself: the boundary may consume the whitespace in front
    of the label, and that whitespace is not part of the emoji.

    A leading count is optional and part of the region: Slack collapses a run
    of three or more identical emoji into one label carrying the count
    ("13 large blue circle 絵文字"), so the count has to go with the label
    rather than stay in the body. A body number in that position ("在庫 12
    confetti ball 絵文字") is indistinguishable from it, and is read as a count.
    """
    return re.compile(
        boundary
        + r'(?P<atom>'
        r'(?:(?P<count>\d{1,4})\s+)?'
        r'(?P<label>' + label + r')'
        r'\s+' + terminator +
        r')'
    )


_EXPANDED_EMOJI_PATTERNS = {
    "ja": (
        _expanded_emoji_pattern(_NON_ASCII_BOUNDARY, _ASCII_EMOJI_RUN, '絵文字'),
        _expanded_emoji_pattern(_whitespace_boundary('絵文字'),
                                _ASCII_EMOJI_LABEL, '絵文字'),
        _expanded_emoji_pattern(_NON_KATAKANA_BOUNDARY,
                                _KATAKANA_EMOJI_LABEL, '絵文字'),
        _expanded_emoji_pattern(_whitespace_boundary('絵文字'),
                                _JA_EMOJI_LABEL, '絵文字'),
    ),
    # English UI (the terminator is "emoji"): how Slack joins a label to body
    # text there has not been measured, so this path is left as it was.
    "en": (
        _expanded_emoji_pattern(_whitespace_boundary('emoji'),
                                _ASCII_EMOJI_LABEL, 'emoji'),
    ),
}


# One emoji occurrence: where it sits, how much it weighs against the
# threshold, the summary keys it contributes, and how many emoji it stands for.
_EmojiAtom = namedtuple("_EmojiAtom", "start end weight names count")


@dataclass
class CleanResult:
    """Result of clean_message_body with skipped emoji information."""
    text: str
    skipped_emoji: dict = field(default_factory=dict)

    # 後方互換: 文字列として扱えるようにする
    def __str__(self):
        return self.text

    def __contains__(self, item):
        return item in self.text

    def __eq__(self, other):
        if isinstance(other, str):
            return self.text == other
        return NotImplemented

    def __len__(self):
        return len(self.text)

    def __bool__(self):
        return bool(self.text)

    def strip(self):
        return self.text.strip()


def _count_emoji_total(text, pattern):
    """Count total emoji matches in text."""
    return len(list(pattern.finditer(text)))


def _is_emoji_only(text, lang="ja"):
    """テキストが絵文字のみで構成されているか判定する。

    全ての絵文字パターンと数字・空白・句読点を除去して、
    意味のあるテキストが残らなければ絵文字のみと判定。
    """
    stripped = text
    # 展開形式の絵文字を除去（例: 「tada 絵文字」「クラッカー 絵文字」）
    # ラベルの種類ごとに左境界の違うパターンを順に適用する。境界のない
    # greedy 版は "important message x0 絵文字" のように前置きの通常テキストも
    # 消費し、誤って emoji-only と判定してしまうため。
    for pattern in _EXPANDED_EMOJI_PATTERNS[lang]:
        stripped = pattern.sub('', stripped)
    # コロン形式の絵文字を除去
    stripped = COLON_EMOJI_PATTERN.sub('', stripped)
    # Unicode絵文字を除去
    stripped = UNICODE_EMOJI_PATTERN.sub('', stripped)
    # 残りが数字・空白・句読点だけなら絵文字のみ
    stripped = re.sub(r'[\s\d。、．，.,]+', '', stripped)
    return len(stripped) == 0


def _expanded_emoji_atom(match):
    """Build the atom for one expanded-label match.

    A collapsed label carries its own count ("13 large blue circle 絵文字").
    That count is the atom's weight, so a collapsed run reaches the threshold
    exactly as 13 separate emoji would, and it is also how many emoji the
    summary reports. The span is the `atom` group, not the whole match, so the
    whitespace a boundary consumed in front of the label stays in the body.
    """
    count = int(match.group("count")) if match.group("count") else 1
    start, end = match.span("atom")
    return _EmojiAtom(start, end, count, [match.group("label")], count)


def _iter_emoji_atoms(text, lang):
    """Return one _EmojiAtom per emoji occurrence, left to right.

    An atom is one colon emoji, one expanded "name 絵文字" token, or one
    contiguous Unicode-emoji cluster. weight is what the threshold is measured
    against (1 for colon; the collapsed count for expanded; glyph count for
    Unicode) and count is how many emoji the summary attributes to each name.

    Reuses UNICODE_EMOJI_PATTERN (defined above, with correctly escaped
    codepoint ranges) as the contiguous-cluster matcher, so the run/glyph
    logic stays consistent with the rest of this module.
    """
    spans = []
    # expanded "name 絵文字" (one pattern per label shape and its boundary;
    # where two of them cover the same label the overlap resolution below
    # keeps the one that starts earliest, which is the widest reading)
    for pattern in _EXPANDED_EMOJI_PATTERNS[lang]:
        for m in pattern.finditer(text):
            spans.append(_expanded_emoji_atom(m))
    # colon emoji
    for m in COLON_EMOJI_PATTERN.finditer(text):
        spans.append(_EmojiAtom(m.start(), m.end(), 1,
                                [m.group(0).strip(':')], 1))
    # unicode emoji clusters, one atom per visible glyph. The name is the emoji
    # character itself, which NVDA's own symbol dictionary reads out, so no table
    # of emoji names has to ship with the add-on. Naming the whole cluster
    # instead made the summary read the removed run back out and report it as one
    # emoji ("13 blue circles, 1"), which cancels out the removal.
    for m in UNICODE_EMOJI_PATTERN.finditer(text):
        base = m.start()
        for offset, glyph in _iter_unicode_glyphs(m.group(0)):
            start = base + offset
            spans.append(_EmojiAtom(start, start + len(glyph), 1, [glyph], 1))
    # resolve overlaps: sort by start, drop any atom starting before prev end
    spans.sort(key=lambda s: (s.start, -s.end))
    result = []
    last_end = -1
    for s in spans:
        if s.start >= last_end:
            result.append(s)
            last_end = s.end
    return result


def _flush_emoji_run(emoji_run, threshold, remove_spans, skipped_emoji):
    """Record one run for removal when its glyph weight meets the threshold.

    Extracted from _remove_emoji_runs as a module-level helper to keep that
    function's cognitive complexity within bounds.
    """
    weight = sum(a.weight for a in emoji_run)
    if weight >= threshold:
        remove_spans.append((emoji_run[0].start, emoji_run[-1].end))
        for a in emoji_run:
            for name in a.names:
                skipped_emoji[name] = skipped_emoji.get(name, 0) + a.count


def _remove_emoji_runs(text, lang, threshold, skipped_emoji):
    """Remove runs of >= threshold consecutive emoji (whitespace-only gaps).

    Isolated emoji (runs shorter than threshold) are left untouched so
    information-bearing status emoji stay attached to their text.
    """
    atoms = _iter_emoji_atoms(text, lang)
    if not atoms:
        return text
    remove_spans = []  # (start, end)
    run = [atoms[0]]
    for prev, cur in zip(atoms, atoms[1:]):
        gap = text[prev.end:cur.start]
        if gap.strip() == "":
            run.append(cur)
        else:
            _flush_emoji_run(run, threshold, remove_spans, skipped_emoji)
            run = [cur]
    _flush_emoji_run(run, threshold, remove_spans, skipped_emoji)
    if not remove_spans:
        return text
    out = []
    pos = 0
    for start, end in remove_spans:
        out.append(text[pos:start])
        pos = end
    out.append(text[pos:])
    return "".join(out)


def clean_message_body(text, lang="ja", threshold=None):
    if threshold is None:
        try:
            from shared.config import get_config, CONF_KEY_EMOJI_THRESHOLD
            threshold = get_config(CONF_KEY_EMOJI_THRESHOLD)
        except Exception:
            threshold = EMOJI_TOTAL_THRESHOLD
    skipped_emoji = {}

    if not text:
        return CleanResult(text=text, skipped_emoji={})
    original_text = text

    # 絵文字のみのメッセージはそのまま返す
    if _is_emoji_only(text, lang):
        return CleanResult(text=text, skipped_emoji={})

    placeholders = {}
    counter = [0]
    def _replace_placeholder(m):
        key = '__PLACEHOLDER_%d__' % counter[0]
        counter[0] += 1
        placeholders[key] = m.group(0)
        return key
    text = CHANNEL_MENTION_PATTERN.sub(_replace_placeholder, text)

    # 連続ラン基準で絵文字を除去（コロン・展開形・Unicode を統一）。
    # ラン長 >= threshold の塊のみ除去し、孤立絵文字は素通しで残す。
    text = _remove_emoji_runs(text, lang, threshold, skipped_emoji)

    # Slackマークダウン装飾除去
    text = SLACK_BOLD_PATTERN.sub(r'\1', text)
    text = SLACK_ITALIC_PATTERN.sub(r'\1', text)
    text = SLACK_STRIKETHROUGH_PATTERN.sub(r'\1', text)

    text = FULLWIDTH_DECORATION_PATTERN.sub('', text)
    text = ASCII_DECORATION_PATTERN.sub('', text)
    # URL除去後に残るリンク装飾の残骸 [ (リンク)] を除去
    text = LINK_BRACKET_RESIDUAL_PATTERN.sub('', text)
    for key, val in placeholders.items():
        text = text.replace(key, val)
    text = re.sub(r'\s+', ' ', text).strip()
    # 絵文字のみのメッセージで掃除後に空になった場合、元のテキストを保持
    if not text and original_text.strip():
        return CleanResult(text=original_text, skipped_emoji={})
    return CleanResult(text=text, skipped_emoji=skipped_emoji)


def format_emoji_summary(skipped_emoji, lang="ja"):
    """Generate a human-readable summary of skipped emoji."""
    if not skipped_emoji:
        return ""
    if lang == "ja":
        parts = [f"{name}{count}こ" for name, count in skipped_emoji.items()]
        return _("メッセージの絵文字: ") + "、".join(parts)
    else:
        parts = [f"{name} {count}" for name, count in skipped_emoji.items()]
        return _("Emoji in message: ") + ", ".join(parts)
