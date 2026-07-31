# -*- coding: utf-8 -*-
"""Message body cleaning: emoji removal, decoration stripping."""
import re
from dataclasses import dataclass, field
from shared.patterns import (
    CHANNEL_MENTION_PATTERN,
    SLACK_BOLD_PATTERN, SLACK_ITALIC_PATTERN, SLACK_STRIKETHROUGH_PATTERN,
    _unicode_glyph_count,
)

LINK_BRACKET_RESIDUAL_PATTERN = re.compile(r'\[\s*\((?:リンク|link)\)\s*\]')
COLON_EMOJI_PATTERN = re.compile(r':[a-zA-Z0-9_\-+\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]+:')
UNICODE_EMOJI_PATTERN = re.compile('[\U0001F300-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\u2600-\u26FF\u2700-\u27BF\uFE00-\uFE0F\u200D\u20E3\u2B50\u23E9-\u23FA]+')
FULLWIDTH_DECORATION_PATTERN = re.compile('[\u2500-\u257F\u2580-\u259F\u25A0-\u25FF\u2190-\u21FF\u2200-\u22FF\u2010-\u2017\u2020-\u2025\u2027\u2030-\u205E\u2E00-\u2E4F\u02DA\u207A\u2605-\u2606\u2934-\u2935\uFF61-\uFF65\uFF0B\u0B60-\u0B7F]+')
ASCII_DECORATION_PATTERN = re.compile(r'[=\-~_]{5,}')

EMOJI_TOTAL_THRESHOLD = 3

# Single-word-before-絵文字/emoji variants used in _is_emoji_only and removal.
# The full expanded_emoji pattern uses {1,3} greedy repetition, which can consume
# legitimate words like "important message" as emoji name prefixes, causing
# _is_emoji_only to return a false positive and the removal sub() to swallow
# non-emoji text. These single-word patterns prevent that.
_EXPANDED_EMOJI_SINGLE = {
    "ja": re.compile(
        r'(?:[a-zA-Z0-9_\-+]{1,20}(?:\s+[a-zA-Z0-9_\-+]{1,20})?|[゠-ヿ]{1,5}|[一-鿿]{1,2})\s+絵文字'
    ),
    "en": re.compile(
        r'[a-zA-Z0-9_\-+]{1,20}(?:\s+[a-zA-Z0-9_\-+]{1,20})?\s+emoji'
    ),
}


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
    # 展開形式の絵文字を除去（例: 「スマイル 絵文字」「sakura 絵文字」）
    # 単語1個限定パターンを使用: {1,3}greedy版は "important message x0 絵文字" のように
    # 前置きの通常テキストも消費し、誤って emoji-only と判定してしまうため。
    stripped = _EXPANDED_EMOJI_SINGLE[lang].sub('', stripped)
    # コロン形式の絵文字を除去
    stripped = COLON_EMOJI_PATTERN.sub('', stripped)
    # Unicode絵文字を除去
    stripped = UNICODE_EMOJI_PATTERN.sub('', stripped)
    # 残りが数字・空白・句読点だけなら絵文字のみ
    stripped = re.sub(r'[\s\d。、．，.,]+', '', stripped)
    return len(stripped) == 0


def _iter_emoji_atoms(text, lang):
    """Yield (start, end, weight, names) for each emoji occurrence.

    An atom is one colon emoji, one expanded "name 絵文字" token, or one
    contiguous Unicode-emoji cluster. weight is the glyph count (1 for colon
    and expanded; glyph count for Unicode). names is a list of summary keys.

    Reuses UNICODE_EMOJI_PATTERN (defined above, with correctly escaped
    codepoint ranges) as the contiguous-cluster matcher, so the run/glyph
    logic stays consistent with the rest of this module.
    """
    spans = []
    # expanded "name 絵文字" (language specific, single-word-limited)
    for m in _EXPANDED_EMOJI_SINGLE[lang].finditer(text):
        name = m.group(0).replace(" 絵文字", "").replace(" emoji", "").strip()
        spans.append((m.start(), m.end(), 1, [name]))
    # colon emoji
    for m in COLON_EMOJI_PATTERN.finditer(text):
        spans.append((m.start(), m.end(), 1, [m.group(0).strip(':')]))
    # unicode emoji clusters
    for m in UNICODE_EMOJI_PATTERN.finditer(text):
        spans.append((m.start(), m.end(), _unicode_glyph_count(m.group(0)),
                      [m.group(0)]))
    # resolve overlaps: sort by start, drop any atom starting before prev end
    spans.sort(key=lambda s: (s[0], -(s[1])))
    result = []
    last_end = -1
    for s in spans:
        if s[0] >= last_end:
            result.append(s)
            last_end = s[1]
    return result


def _flush_emoji_run(emoji_run, threshold, remove_spans, skipped_emoji):
    """Record one run for removal when its glyph weight meets the threshold.

    Extracted from _remove_emoji_runs as a module-level helper to keep that
    function's cognitive complexity within bounds.
    """
    weight = sum(a[2] for a in emoji_run)
    if weight >= threshold:
        remove_spans.append((emoji_run[0][0], emoji_run[-1][1]))
        for a in emoji_run:
            for name in a[3]:
                skipped_emoji[name] = skipped_emoji.get(name, 0) + 1


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
        gap = text[prev[1]:cur[0]]
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
