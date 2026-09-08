# -*- coding: utf-8 -*-
"""Language-specific and language-independent regex patterns for message parsing."""
import re

# --- Language-independent patterns ---
URL_PATTERN = re.compile(
    r'https?://[^\s<>\"\'\)\]。、」]+',
    re.IGNORECASE
)

SENDER_PATTERN = re.compile(
    r'^(.+?)\s*:\s+'
)

# A Slack "link chip" display string: a bare host (label.label...) optionally
# followed by a path/query, with NO scheme. Slack may insert a mid-string
# ellipsis (…) where it truncated the visible URL, so the display text alone
# is not always a fetchable URL. Anchored at start so it does not match real
# unfurl titles (which begin with words/CJK and contain spaces). Used to tell
# URL-display chips apart from genuine title chips so the real href is
# recovered from the accessibility tree instead of announcing the chip text.
URL_DISPLAY_PATTERN = re.compile(
    r'^(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:[/?#]\S*)?$'
)

# Used as a boolean gate only; partial match on \d+ is intentional.
TWITTER_PATTERN = re.compile(
    r'^https?://(?:www\.)?(?:twitter\.com|x\.com)/\S+/status/\d+',
    re.IGNORECASE
)

YOUTUBE_PATTERN = re.compile(
    r'^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+|^https?://youtu\.be/[\w-]+',
    re.IGNORECASE
)

GITHUB_PATTERN = re.compile(
    r'^https?://github\.com/([^/]+)/([^/]+)(?:/(pull|issues|commit)/([^/?\s]+))?',
    re.IGNORECASE
)

CHANNEL_MENTION_PATTERN = re.compile(r'(?:#[a-zA-Z0-9_\-]+|@[a-zA-Z0-9_.\-]+)')

# --- Language-specific patterns ---
_PATTERNS = {
    "ja": {
        "metadata_suffix": re.compile(
            r'(?:(?<=。)|(?<=\])|(?<=\)))\s*時刻\s+.+$'
            r'|(?:(?<=。)|(?<=\])|(?<=\)))\s*（\d{1,2}:\d{2}）.*$'
        ),
        "time": re.compile(r'(?:時刻\s+(.+?)(?:。|$)|（(\d{1,2}:\d{2})）)'),
        "link_count": re.compile(r'(\d+)\s*件のリンク'),
        "reaction": re.compile(r'(\d+)\s*(?:個の絵文字リアクション|件のリアクション)'),
        "replies": re.compile(r'(\d+)\s*件の返信'),
        "attachment": re.compile(r'(\d+)\s*件の添付ファイル'),
        "unfurl_link": re.compile(r'\[\s*(.+?)\s*\(リンク\)\s*\]'),
        "mention_prefix": re.compile(r'^(.+?)さんが\s+#(\S+)\s+であなたをメンションしました。\s*'),
        "expanded_emoji": re.compile(
            r'(?:(?:[a-zA-Z0-9_\-+]{1,20}|[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]{1,10})\s+){1,3}絵文字'
        ),
        "forwarded_header": re.compile(
            r'^(.+?)(?:\s+\S+)?さんが\s+\S+\s+に\s+#(\S+)\s+で作成\s*:\s*'
        ),
        "forwarded_template": "{comment}。 #{channel} からの転送：",
        "sentence_sep": "。",
        "body_trail": "。",
    },
    "en": {
        "metadata_suffix": re.compile(r'(?:(?<=\.)|(?<=\])|(?<=\)))\s*\d{1,2}:\d{2}\s*[AP]M[.\s]*.*$'),
        "time": re.compile(r'(\d{1,2}:\d{2}\s*[AP]M)'),
        "link_count": re.compile(r'(\d+)\s*links?'),
        "reaction": re.compile(r'(\d+)\s*reactions?'),
        "replies": re.compile(r'(\d+)\s*repl(?:y|ies)'),
        "attachment": re.compile(r'(\d+)\s*attachments?'),
        "unfurl_link": re.compile(r'\[\s*(.+?)\s*\(link\)\s*\]'),
        "mention_prefix": re.compile(
            r'^(.+?)\s+mentioned you in (?:thread in )?#(\S+)[.:]\s*'
        ),
        "expanded_emoji": re.compile(
            r'(?:[a-zA-Z0-9_\-+]{1,20}\s+){1,3}emoji'
        ),
        "forwarded_header": re.compile(
            r'^(.+?)\s+on\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?\s+in\s+#(\S+)\s*:\s*'
        ),
        "forwarded_template": "{comment}. Forwarded from #{channel}:",
        "sentence_sep": ".",
        "body_trail": ".",
    },
}


def _detect_lang(text):
    """日本語パターンを先に試し、マッチすれば 'ja'、しなければ 'en' を返す"""
    if _PATTERNS["ja"]["metadata_suffix"].search(text):
        return "ja"
    # フォールバック: 日本語メタデータキーワードで判定
    if re.search(r'時刻\s+\d', text) or re.search(r'件の(?:リンク|リアクション|返信)', text):
        return "ja"
    # 通知一覧形式: 「さんが...であなたをメンションしました」または「（HH:MM）」
    if re.search(r'さんが\s+#\S+\s+であなたをメンションしました', text):
        return "ja"
    # Teams は当日のメッセージの時刻を「今日の 16:25」と書き、「時刻」という語も
    # 年月日も使わないので、上のどの手がかりにも当たらない。Slack のフッターの
    # 時刻表記（今日の08:45）は同じ形で空白がないので、空白の有無は問わない。
    if re.search(r'今日の\s*\d{1,2}:\d{2}', text):
        return "ja"
    if re.search(r'（\d{1,2}:\d{2}）', text):
        return "ja"
    return "en"


CONSECUTIVE_COLON_EMOJI_PATTERN = re.compile(
    r'(:[a-zA-Z0-9_\-+\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]+:)(?:\s*\1){2,}'
)
SLACK_BOLD_PATTERN = re.compile(r'\*(\S[^*]*\S|\S)\*')
SLACK_ITALIC_PATTERN = re.compile(r'(?<!\w)_([^_]+)_(?!\w)')
SLACK_STRIKETHROUGH_PATTERN = re.compile(r'~([^~]+)~')

_UNFURL_FILTER_STRINGS = {
    'View page', 'Confluence Cloud',
    'ページを表示',
    '新しいウィンドウで開く', 'Open in new window',
}

# Codepoints inside a contiguous Unicode-emoji cluster that are
# modifiers/joiners, NOT standalone glyphs: variation selectors
# (U+FE0E, U+FE0F), zero-width joiner (U+200D), keycap combiner (U+20E3),
# and skin-tone modifiers (U+1F3FB-U+1F3FF). Written with escaped
# codepoints only - no literal emoji glyphs in source, per project
# convention.
_ZWJ = '\u200d'
_UNI_NON_GLYPH = (
    {'\ufe0e', '\ufe0f', _ZWJ, '\u20e3'}
    | {chr(c) for c in range(0x1F3FB, 0x1F400)}  # skin-tone modifiers
)


def _unicode_glyph_count(s):
    """Approximate number of visible emoji glyphs in a contiguous cluster.

    Count base codepoints (excluding modifiers/joiners), then subtract one per
    ZWJ so a ZWJ-joined sequence (e.g. family emoji) counts as a single glyph.
    """
    bases = sum(1 for ch in s if ch not in _UNI_NON_GLYPH)
    zwj = s.count(_ZWJ)
    return max(1, bases - zwj)


def _iter_unicode_glyphs(s):
    """Split a contiguous Unicode-emoji cluster into one entry per visible glyph.

    Returns (offset, glyph) pairs, where offset is the glyph's index within `s`.
    Modifiers and joiners stay with the glyph they belong to: a variation
    selector, keycap combiner or skin-tone modifier attaches to the character in
    front of it, and a ZWJ also draws the following base into the same glyph, so
    a joined sequence is one entry. This is the unit `_unicode_glyph_count`
    counts, so the two stay in step.
    """
    spans = []
    join_next = False
    for i, ch in enumerate(s):
        attaches = join_next or ch in _UNI_NON_GLYPH
        join_next = ch == _ZWJ
        if spans and attaches:
            spans[-1][1] = i + 1
        else:
            spans.append([i, i + 1])
    return [(start, s[start:end]) for start, end in spans]
