# -*- coding: utf-8 -*-
# NVDA App Module for the new Microsoft Teams on Windows
#
# Teams renders in a WebView2 process. Before NVDA 2024.3 that process reported
# the name of the WebView2 runtime itself, which Start menu search, Widgets and
# other Windows components share, so Teams support had to be a globalPlugin that
# checked the foreground window's title. Since nvaccess/nvda#16717 (proposed in
# nvaccess/nvda#16705) NVDA walks up to the parent process and reports the name
# of the hosting application, which for the new Teams is ms-teams. An ordinary
# appModule is therefore enough, and it is only loaded into Teams.
#
# The name ms-teams contains a hyphen, which is not a legal Python module name,
# so appModuleHandler cannot derive this file's name from the executable's. The
# binding is made explicitly by the globalPlugin, which calls
# appModuleHandler.registerExecutableWithAppModule("ms-teams", "msTeams").

import os
import re
import sys
import threading

# Add addon root to sys.path so shared modules can be imported
_addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _addon_root not in sys.path:
    sys.path.insert(0, _addon_root)

import addonHandler
import appModuleHandler
import api
import braille
import speech
import controlTypes
import queueHandler
from logHandler import log

from shared.patterns import URL_PATTERN, TWITTER_PATTERN
from shared.cleaner import clean_message_body, format_emoji_summary
from shared.fetcher import fetch_page_title, fetch_x_post_via_oembed, TitleCache, format_link_announce
from shared.state import is_processing_enabled

# --- i18n ---
try:
    addonHandler.initTranslation()
    log.info("msTeamsAppModule: initTranslation() succeeded")
except Exception:
    log.warning("msTeamsAppModule: initTranslation() failed", exc_info=True)

# --- Teams-specific patterns ---
TEAMS_DATETIME_JA = re.compile(
    r'\s*\d{4}年\d{1,2}月\d{1,2}日 \d{1,2}:\d{2}\.\s*$'
)
TEAMS_DATETIME_EN = re.compile(
    r'(?:'
    r'\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
    r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
    r'\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s*[AP]M\.'
    r'|\s*\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M\.'
    r')\s*$',
    re.IGNORECASE
)
TEAMS_LINK_PREFIX_JA = re.compile(r'\s*リンク\s+(?=https?://)')
TEAMS_LINK_PREFIX_EN = re.compile(r'\s*link\s+(?=https?://)', re.IGNORECASE)
# Teams が URL なし添付リンクに付ける "Link" / "リンク" アクセシビリティラベルの除去
TEAMS_LINK_LABEL_JA = re.compile(r'\s+リンク\s+(?!https?://)')
TEAMS_LINK_LABEL_EN = re.compile(r'\s+Link\s+(?!https?://)', re.IGNORECASE)
TEAMS_SENT_LABEL_JA = re.compile(r'\s+送信済み(?=\s)')

# 読み上げの区切り。Teams のメッセージは送信者・本文・時刻が1つの
# アクセシブル名に入っており、それを文として並べ直す。
SENTENCE_SEP = ". "


def _detect_teams_lang(text):
    """Teams メッセージの言語を日時パターンで判定"""
    if TEAMS_DATETIME_JA.search(text):
        return "ja"
    return "en"


def parse_teams_message(name_text):
    result = {
        "sender": "",
        "body": "",
        "link_display": "",
        "time": "",
        "urls": [],
        "raw": name_text,
        "lang": "en",
    }
    if not name_text:
        return result

    # \xa0 正規化
    text = name_text.replace('\xa0', ' ')
    text = re.sub(r' {2,}', ' ', text)

    # 1. 言語検出
    lang = _detect_teams_lang(text)
    result["lang"] = lang

    # 2. 末尾の日時パターンを除去
    dt_pattern = TEAMS_DATETIME_JA if lang == "ja" else TEAMS_DATETIME_EN
    dt_match = dt_pattern.search(text)
    if dt_match:
        time_str = dt_match.group().strip().rstrip(".")
        result["time"] = time_str
        text = text[:dt_match.start()]

    # 3. URL抽出
    result["urls"] = URL_PATTERN.findall(text)

    # 4. 「リンク / Link」ラベル除去
    if result["urls"]:
        # URL 直前の "リンク"/"Link" ラベルを除去
        link_prefix = TEAMS_LINK_PREFIX_JA if lang == "ja" else TEAMS_LINK_PREFIX_EN
        text = link_prefix.sub(' ', text)
    else:
        # URL なし添付リンク（表示テキスト形式）: "Link" ラベルを除去し表示テキストを分離
        link_label = TEAMS_LINK_LABEL_JA if lang == "ja" else TEAMS_LINK_LABEL_EN
        link_match = link_label.search(text)
        if link_match:
            result["link_display"] = text[link_match.end():].strip()
            text = text[:link_match.start()]

    # 5. 「送信済み」ラベル除去
    if lang == "ja":
        text = TEAMS_SENT_LABEL_JA.sub('', text)

    # 6. URL自体を本文から除去
    if result["urls"]:
        text = URL_PATTERN.sub('', text)

    # 7. 残りを本文として格納
    result["body"] = re.sub(r'\s+', ' ', text).strip()

    return result


def _build_parsed_message(name):
    """Parse the accessible name and clean the body that will be spoken."""
    parsed = parse_teams_message(name)
    cleaned = clean_message_body(parsed["body"], parsed["lang"])
    parsed["body"] = cleaned.text
    parsed["skipped_emoji"] = cleaned.skipped_emoji
    return parsed


def _summary_position():
    """Configured emoji-summary position, defaulting to "after"."""
    try:
        from shared.config import get_config, CONF_KEY_SUMMARY_POSITION
        return get_config(CONF_KEY_SUMMARY_POSITION)
    except Exception:
        return "after"


def _append_emoji_summary(parts, parsed, summary_pos):
    """Insert the emoji-run summary at the configured position."""
    summary = format_emoji_summary(parsed.get("skipped_emoji", {}), parsed["lang"])
    if not summary or summary_pos == "off":
        return
    if summary_pos == "before":
        parts.insert(1 if parsed["sender"] else 0, summary)
    else:
        parts.append(summary)


def _plain_message_parts(parsed, summary_pos):
    """Everything announced for a message with no URL to resolve."""
    parts = []
    if parsed["body"]:
        parts.append(parsed["body"])
    if parsed.get("link_display"):
        # 表示テキスト付きリンク: URL リンクの「リンク: {title}」形式に合わせて読み上げ
        parts.append(_("Link: {title}").format(title=parsed["link_display"]))
    _append_emoji_summary(parts, parsed, summary_pos)
    if parsed["time"]:
        parts.append(parsed["time"])
    return parts


def _pending_name(parsed, summary_pos):
    """Text spoken immediately, before link titles have been fetched."""
    parts = []
    if parsed["body"]:
        parts.append(parsed["body"])
    _append_emoji_summary(parts, parsed, summary_pos)
    if parts:
        return SENTENCE_SEP.join(parts)
    return _("{sender}. Fetching link titles...").format(
        sender=parsed["body"] or "Teams")


def _speak_and_finish(obj, next_handler, processed_name, context):
    """Set obj.name so braille picks it up, run next_handler, then speak."""
    obj.name = processed_name
    try:
        next_handler()
    except Exception:
        log.debugWarning(
            f"msTeamsAppModule: error in next_handler for {context}",
            exc_info=True,
        )
    speech.cancelSpeech()
    speech.speakMessage(processed_name)


class AppModule(appModuleHandler.AppModule):

    _title_cache = TitleCache()

    def event_gainFocus(self, obj, next_handler):
        name = self._name_to_rewrite(obj, next_handler)
        if name is None:
            return

        parsed = _build_parsed_message(name)
        summary_pos = _summary_position()

        if not parsed["urls"]:
            self._announce_plain_message(obj, next_handler, parsed, summary_pos)
            return

        # 本文を先に読み上げ、リンクのタイトルと時刻は解決できてから追う。
        processed_name = _pending_name(parsed, summary_pos)
        _speak_and_finish(obj, next_handler, processed_name, "grouping")
        self._start_url_fetch(parsed, processed_name)

    @staticmethod
    def _name_to_rewrite(obj, next_handler):
        """The accessible name to rewrite, or None once the event is passed on."""
        if not is_processing_enabled():
            next_handler()
            return None

        log.info(
            f"msTeamsAppModule: event_gainFocus fired. "
            f"role={obj.role}, name={obj.name!r:.80}"
        )

        try:
            is_grouping = obj.role == controlTypes.Role.GROUPING
        except AttributeError:
            is_grouping = obj.role == controlTypes.ROLE_GROUPING

        if not is_grouping:
            try:
                next_handler()
            except Exception:
                log.debugWarning(
                    "msTeamsAppModule: error in next_handler for non-grouping",
                    exc_info=True,
                )
            return None

        name = obj.name if hasattr(obj, "name") and obj.name else ""
        if not name:
            next_handler()
            return None
        return name

    @staticmethod
    def _announce_plain_message(obj, next_handler, parsed, summary_pos):
        """No URL to resolve: the whole announcement is already known."""
        parts = _plain_message_parts(parsed, summary_pos)
        if not parts:
            next_handler()
            return
        _speak_and_finish(
            obj, next_handler, SENTENCE_SEP.join(parts), "no-url grouping")

    def _start_url_fetch(self, parsed, immediate_text):
        """Resolve link titles, announcing at once when nothing needs fetching."""
        urls_to_fetch, url_title_map = self._partition_cached_urls(parsed)
        if not urls_to_fetch:
            self._announce_titles(parsed, url_title_map, immediate_text)
            return

        threading.Thread(
            target=self._fetch_and_speak,
            args=(urls_to_fetch, url_title_map, parsed, immediate_text),
            daemon=True,
        ).start()

    def _partition_cached_urls(self, parsed):
        """Split parsed URLs into (needs fetching, already-known titles)."""
        urls_to_fetch = []
        url_title_map = {}
        for url in parsed["urls"]:
            if url in self._title_cache:
                url_title_map[url] = self._title_cache.get(url)
            else:
                urls_to_fetch.append(url)
        return urls_to_fetch, url_title_map

    def _fetch_and_speak(self, urls_to_fetch, url_title_map, parsed, immediate_text):
        """Fetch titles off the main thread, then announce from the event queue."""
        for url in urls_to_fetch:
            if TWITTER_PATTERN.match(url):
                title = fetch_x_post_via_oembed(url)
            else:
                title = fetch_page_title(url)
            log.info(f"msTeamsAppModule: Fetched title for {url} -> {title!r}")
            self._title_cache.put(url, title)
            url_title_map[url] = title
        queueHandler.queueFunction(
            queueHandler.eventQueue,
            self._announce_titles,
            parsed,
            url_title_map,
            immediate_text,
        )

    def _announce_titles(self, parsed, url_title_map, immediate_text):
        link_parts = self._link_parts(parsed, url_title_map)
        if parsed["time"]:
            link_parts.append(parsed["time"])
        if not link_parts:
            return

        link_text = SENTENCE_SEP.join(link_parts)
        speech.speakMessage(link_text)
        self._update_braille(immediate_text, link_text)

    @staticmethod
    def _link_parts(parsed, url_title_map):
        """One announcement per URL, in the order the message listed them."""
        from shared.config import get_config, CONF_KEY_LINK_FAILURE_ANNOUNCE
        templates = {
            "title": _("Link: {title}"),
            "label": _("Link: Title unavailable"),
            "host": _("Link: {host} (Title unavailable)"),
            "url": _("Link: {url}"),
        }
        mode = get_config(CONF_KEY_LINK_FAILURE_ANNOUNCE)
        parts = []
        for url in parsed["urls"]:
            announce = format_link_announce(
                url, url_title_map.get(url), mode, templates)
            if announce:
                parts.append(announce)
        return parts

    @staticmethod
    def _update_braille(immediate_text, link_text):
        """Put the whole announcement on the braille display, links included."""
        complete_text = (
            immediate_text + SENTENCE_SEP + link_text if immediate_text
            else link_text
        )
        try:
            focus = api.getFocusObject()
            if focus:
                focus.name = complete_text
                braille.handler.handleGainFocus(focus)
        except Exception:
            log.debugWarning(
                "msTeamsAppModule: error updating braille with complete text",
                exc_info=True,
            )
