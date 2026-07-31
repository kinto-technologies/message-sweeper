# -*- coding: utf-8 -*-
# NVDA Global Plugin for Microsoft Teams Desktop
#
# Teams runs inside msedgewebview2.exe, which is shared by many Windows
# components (Start Menu search, Widgets, etc.).  Using a globalPlugin
# instead of an appModule avoids loading custom code into every
# msedgewebview2.exe instance — only Teams windows are affected.

import os
import re
import sys
import threading

# Add addon root to sys.path so shared modules can be imported
_addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _addon_root not in sys.path:
    sys.path.insert(0, _addon_root)

import addonHandler
import globalPluginHandler
import api
import braille
import tones
import speech
import controlTypes
import queueHandler
from logHandler import log

try:
    import gui
    from gui import settingsDialogs
except Exception:
    gui = None
    settingsDialogs = None

from shared.patterns import URL_PATTERN, TWITTER_PATTERN
from shared.cleaner import clean_message_body, format_emoji_summary
from shared.fetcher import fetch_page_title, fetch_x_post_via_oembed, TitleCache, format_link_announce

# --- i18n ---
try:
    addonHandler.initTranslation()
    log.info("teamsGlobalPlugin: initTranslation() succeeded")
except Exception:
    log.warning("teamsGlobalPlugin: initTranslation() failed", exc_info=True)

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


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    _title_cache = TitleCache()
    _processing_enabled = True

    def __init__(self):
        super().__init__()
        try:
            from shared.config import register_config
            register_config()
        except Exception:
            pass
        try:
            from shared.settingsGUI import MessageSweeperSettingsPanel
            gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(
                MessageSweeperSettingsPanel
            )
        except Exception:
            pass

    def terminate(self):
        try:
            from shared.settingsGUI import MessageSweeperSettingsPanel
            gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(
                MessageSweeperSettingsPanel
            )
        except Exception:
            pass

    def script_toggleProcessing(self, gesture):
        GlobalPlugin._processing_enabled = not GlobalPlugin._processing_enabled
        enabled = GlobalPlugin._processing_enabled
        msg = _("Message Sweeper enabled") if enabled else _("Message Sweeper disabled")

        try:
            from shared.config import get_config, CONF_KEY_TOGGLE_SOUND
            use_sound = get_config(CONF_KEY_TOGGLE_SOUND)
        except Exception:
            use_sound = True

        if use_sound:
            tones.beep(880 if enabled else 440, 80)
        else:
            speech.speakMessage(msg)

        braille.handler.message(msg)

    script_toggleProcessing.__doc__ = _("Toggle Message Sweeper module")
    script_toggleProcessing.category = _("Message Sweeper")

    __gestures = {
        "kb:NVDA+v": "toggleProcessing",
    }

    _TEAMS_APP_NAMES = frozenset({"msedgewebview2", "ms-teams"})

    @staticmethod
    def _is_teams_context(obj):
        """対象が Teams ウィンドウかどうか判定（ms-teams / msedgewebview2 両対応）"""
        try:
            app_name = obj.appModule.appName
            if app_name in GlobalPlugin._TEAMS_APP_NAMES:
                fg = api.getForegroundObject()
                title = fg.name if fg and hasattr(fg, "name") else ""
                return "Microsoft Teams" in title
            return False
        except Exception:
            return False

    def event_gainFocus(self, obj, nextHandler):
        if not self._processing_enabled or not self._is_teams_context(obj):
            nextHandler()
            return

        log.info(
            f"teamsGlobalPlugin: event_gainFocus fired. "
            f"role={obj.role}, name={obj.name!r:.80}"
        )

        try:
            is_grouping = obj.role == controlTypes.Role.GROUPING
        except AttributeError:
            is_grouping = obj.role == controlTypes.ROLE_GROUPING

        if not is_grouping:
            try:
                nextHandler()
            except Exception:
                log.debugWarning(
                    "teamsGlobalPlugin: error in nextHandler for non-grouping",
                    exc_info=True,
                )
            return

        name = obj.name if hasattr(obj, "name") and obj.name else ""
        if not name:
            nextHandler()
            return

        parsed = parse_teams_message(name)
        _clean_result = clean_message_body(parsed["body"], parsed["lang"])
        parsed["body"] = _clean_result.text
        parsed["skipped_emoji"] = _clean_result.skipped_emoji
        try:
            from shared.config import get_config, CONF_KEY_SUMMARY_POSITION
            _summary_pos = get_config(CONF_KEY_SUMMARY_POSITION)
        except Exception:
            _summary_pos = "after"
        if not parsed["urls"]:
            # URL無し: クリーニング済み本文を読み上げ
            immediate_parts = []
            if parsed["body"]:
                immediate_parts.append(parsed["body"])
            if parsed.get("link_display"):
                # 表示テキスト付きリンク: URL リンクの「リンク: {title}」形式に合わせて読み上げ
                immediate_parts.append(
                    _("Link: {title}").format(title=parsed["link_display"])
                )
            _emoji_summary = format_emoji_summary(
                parsed.get("skipped_emoji", {}), parsed["lang"]
            )
            if _emoji_summary and _summary_pos != "off":
                if _summary_pos == "before":
                    insert_idx = 1 if parsed["sender"] else 0
                    immediate_parts.insert(insert_idx, _emoji_summary)
                else:  # "after"
                    immediate_parts.append(_emoji_summary)
            if parsed["time"]:
                immediate_parts.append(parsed["time"])
            if not immediate_parts:
                nextHandler()
                return
            processed_name = ". ".join(immediate_parts)
            obj.name = processed_name
            try:
                nextHandler()
            except Exception:
                log.debugWarning(
                    "teamsGlobalPlugin: error in nextHandler for no-url grouping",
                    exc_info=True,
                )
            speech.cancelSpeech()
            speech.speakMessage(processed_name)
            return

        # Immediate: speak body without URLs (time is announced later with link titles)
        immediate_parts = []
        if parsed["body"]:
            immediate_parts.append(parsed["body"])
        _emoji_summary = format_emoji_summary(
            parsed.get("skipped_emoji", {}), parsed["lang"]
        )
        if _emoji_summary and _summary_pos != "off":
            if _summary_pos == "before":
                insert_idx = 1 if parsed["sender"] else 0
                immediate_parts.insert(insert_idx, _emoji_summary)
            else:  # "after"
                immediate_parts.append(_emoji_summary)

        if immediate_parts:
            processed_name = ". ".join(immediate_parts)
        else:
            processed_name = _("{sender}. Fetching link titles...").format(
                sender=parsed["body"] or "Teams")

        obj.name = processed_name
        try:
            nextHandler()
        except Exception:
            log.debugWarning(
                "teamsGlobalPlugin: error in nextHandler for grouping",
                exc_info=True,
            )
        speech.cancelSpeech()
        speech.speakMessage(processed_name)

        # Fetch titles in background
        urls_to_fetch = []
        url_title_map = {}
        for url in parsed["urls"]:
            if url in self._title_cache:
                url_title_map[url] = self._title_cache.get(url)
            else:
                urls_to_fetch.append(url)

        if not urls_to_fetch:
            self._announce_titles(parsed, url_title_map, processed_name)
            return

        def _fetch_and_speak():
            for url in urls_to_fetch:
                if TWITTER_PATTERN.match(url):
                    title = fetch_x_post_via_oembed(url)
                else:
                    title = fetch_page_title(url)
                log.info(f"teamsGlobalPlugin: Fetched title for {url} -> {title!r}")
                self._title_cache.put(url, title)
                url_title_map[url] = title
            queueHandler.queueFunction(
                queueHandler.eventQueue,
                self._announce_titles,
                parsed,
                url_title_map,
                processed_name,
            )

        threading.Thread(target=_fetch_and_speak, daemon=True).start()

    def _announce_titles(self, parsed, url_title_map, immediate_text):
        link_parts = []
        from shared.config import get_config, CONF_KEY_LINK_FAILURE_ANNOUNCE
        templates = {
            "title": _("Link: {title}"),
            "label": _("Link: Title unavailable"),
            "host": _("Link: {host} (Title unavailable)"),
            "url": _("Link: {url}"),
        }
        mode = get_config(CONF_KEY_LINK_FAILURE_ANNOUNCE)
        for url in parsed["urls"]:
            title = url_title_map.get(url)
            announce = format_link_announce(url, title, mode, templates)
            if announce:
                link_parts.append(announce)
        if parsed["time"]:
            link_parts.append(parsed["time"])
        if not link_parts:
            return

        link_text = ". ".join(link_parts)
        speech.speakMessage(link_text)

        complete_text = (
            immediate_text + ". " + link_text if immediate_text else link_text
        )
        try:
            focus = api.getFocusObject()
            if focus:
                focus.name = complete_text
                braille.handler.handleGainFocus(focus)
        except Exception:
            log.debugWarning(
                "teamsGlobalPlugin: error updating braille with complete text",
                exc_info=True,
            )
