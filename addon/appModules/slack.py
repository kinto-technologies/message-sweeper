# -*- coding: utf-8 -*-
# NVDA App Module for Slack Desktop
# Replaces URL readout with page titles when focusing messages containing links.
#
# Installation:
#   1. Place this file as "slack.py" in:
#      %APPDATA%\nvda\scratchpad\appModules\slack.py
#      (Enable scratchpad in NVDA Settings > Advanced)
#   2. Restart NVDA or press NVDA+Ctrl+F3 to reload plugins.
#
# Tested with Slack 4.48.95

import os
import re
import sys
import threading

# Add addon root to sys.path so shared modules can be imported
_addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _addon_root not in sys.path:
    sys.path.insert(0, _addon_root)

import appModuleHandler
import api
import braille
import speech
import ui
import controlTypes
import queueHandler
from logHandler import log

from shared.patterns import (
    URL_PATTERN, URL_DISPLAY_PATTERN, SENDER_PATTERN, _PATTERNS, _detect_lang,
    _UNFURL_FILTER_STRINGS, TWITTER_PATTERN,
)
from shared.cleaner import clean_message_body, format_emoji_summary
from shared.fetcher import (
    fetch_page_title, fetch_x_post_via_oembed, TitleCache, format_link_announce,
)

# --- i18n ---
try:
    import addonHandler
    addonHandler.initTranslation()
    log.info("slackAppModule: initTranslation() succeeded")
except Exception:
    log.warning("slackAppModule: initTranslation() failed", exc_info=True)


# Matches Japanese X unfurl block inside [...(リンク)] blocks.
# Format: "(N) Xユーザーの{name}さん: 「{tweet}」 / X"
# Group 1 captures the tweet text (greedy to handle nested 「」 in tweets).
_JA_X_UNFURL_PATTERN = re.compile(
    r'^(?:\(\d+\)\s+)?Xユーザーの[^：:]+[：:]\s*「(.*)」\s*/\s*X\s*$',
    re.DOTALL,
)

# Matches "XユーザーのName: 「tweet text / X」" that Slack embeds in obj.name.
# Removing it from the body prevents the tweet being announced twice when
# _extract_x_preview_text_from_tree also extracts the same content.
_X_CARD_BODY_PATTERN = re.compile(
    r'\s*Xユーザーの[^：:]+[：:]\s*「[^」]*」'
)

# Slack names an X unfurl card's author link "Name (@handle) on X", and closes
# the card with an "X (formerly Twitter)" branding element. Both are used as
# boundary markers when walking the card out of the accessibility tree.
_X_AUTHOR_LINK_SUFFIX = " on X"
_X_CARD_END_MARKER = "X (formerly Twitter)"

# Matches Slack permalink URLs (.slack.com/archives/{channel}/p{ts}).
# Used to gate the subtree diagnostic dump to the Slack-permalink unfurl bug.
_SLACK_PERMALINK_PATTERN = re.compile(
    r'^https?://[^/]+\.slack\.com/archives/[^/]+/p\d+',
    re.IGNORECASE,
)


def _find_unfurl_titles_in_tree(obj):
    """Walk the accessibility tree to find link titles inside unfurl cards.

    Unfurl cards live deep in the tree (depth >= 5). We look for LINK elements
    (role=19) at depth >= 5 whose name is not a raw URL — these are page titles.
    """
    titles = []
    message_urls = set()
    try:
        link_role = controlTypes.Role.LINK
    except AttributeError:
        link_role = controlTypes.ROLE_LINK

    # First, collect URLs from the message body (shallow links, depth < 5)
    # Then find title links deep in the unfurl card
    def _walk(node, depth=0, max_depth=10):
        if depth > max_depth:
            return
        try:
            child = node.firstChild
            while child:
                if child.role == link_role and child.name:
                    if depth < 5:
                        # Shallow link: part of the message body
                        if child.name.startswith('http'):
                            message_urls.add(child.name)
                    else:
                        # Deep link: inside unfurl card
                        if not child.name.startswith('http'):
                            titles.append(child.name)
                _walk(child, depth + 1, max_depth)
                child = child.next
        except Exception:
            pass

    _walk(obj)
    # Filter out known non-title links
    filtered = [t for t in titles if t not in _UNFURL_FILTER_STRINGS]
    return filtered


def _role_or_legacy(name):
    """controlTypes.Role.<name> with a fallback for pre-Role NVDA builds."""
    try:
        return getattr(controlTypes.Role, name)
    except AttributeError:
        return getattr(controlTypes, "ROLE_" + name)


def _link_role():
    """controlTypes.Role.LINK with a fallback for pre-Role NVDA builds."""
    return _role_or_legacy("LINK")


def _record_chip_href(child, link_role, wanted, found):
    """If child is a LINK whose name is a wanted chip display, record its href.

    Broad except: detached NVDA objects can raise COMError/RuntimeError on
    attribute access; skip such nodes rather than break traversal.
    """
    try:
        if child.role != link_role:
            return
        name = child.name or ""
        if name not in wanted or name in found:
            return
        value = getattr(child, "value", None) or ""
        if value.startswith("http"):
            found[name] = value
    except Exception:
        pass


def _walk_chip_links(node, link_role, wanted, found, depth=0, max_depth=10):
    """Depth-limited pre-order walk collecting chip hrefs into `found`."""
    if depth > max_depth:
        return
    try:
        child = node.firstChild
    except Exception:
        return
    while child is not None:
        _record_chip_href(child, link_role, wanted, found)
        _walk_chip_links(child, link_role, wanted, found, depth + 1, max_depth)
        try:
            child = child.next
        except Exception:
            break


def _resolve_chip_link_hrefs(obj, displays):
    """Map Slack "link chip" display strings to their real hrefs via the tree.

    For chip-link messages, the message-body LINK node's accessible `name` is a
    schemeless / mid-truncated display URL (e.g. "sports.example.com/…/text?gk=18")
    while its `value` holds the full href. Match each display against a LINK
    node's name and return {display: href} for those whose value is an http(s)
    URL. Matching by exact name avoids the listitem's own permalink LINK (whose
    name is a timestamp, not a display URL).
    """
    wanted = set(displays)
    found = {}
    _walk_chip_links(obj, _link_role(), wanted, found)
    return found


def _merge_chip_links(parsed, resolved):
    """Fold resolved chip-link hrefs into parsed in place.

    For each chip display: if a real href was recovered, append it to
    parsed["urls"] (so the message flows through the normal tree-title / fetch
    path); otherwise fall back to announcing the raw display text as a title so
    the link is not lost entirely.
    """
    for display in parsed.get("chip_link_displays", []):
        href = resolved.get(display)
        if href:
            if href not in parsed["urls"]:
                parsed["urls"].append(href)
        else:
            parsed["unfurl_titles"].append(display)


def _extract_slack_permalink_unfurl_text(obj):
    """Extract embedded Slack permalink unfurl card content from the tree.

    Slack normally flattens an unfurled Slack-message preview into the
    listitem's accessible name (handled transparently by
    parse_slack_message). For some messages — notably thread replies that
    were broadcast to channel, or some Slack desktop versions — only the
    bare URL lands in the name and the card body lives in a sibling
    SECTION. This walker recovers that content.

    Returns {permalink_url: {"sender": str, "time": str, "body": str}}.

    Tree structure observed (Slack desktop, 2026-05):
      LISTITEM > ... >
        LINK [name == URL, value == URL]   <- the permalink itself
        SECTION (empty, spacer; JA only)   <- not present in EN UI
        SECTION (JA) / GROUPING (EN)       <- the card
          SECTION/GROUPING > BUTTON [sender] > {TEXTFRAME (JA) | STATICTEXT '' (EN)} > STATICTEXT [sender]
          SECTION/GROUPING > {LINK [mention]/STATICTEXT [body]}*
          BLOCKQUOTE > STATICTEXT [quote]
          SECTION/GROUPING > STATICTEXT [continuation]
          SECTION/GROUPING (footer)
            STATICTEXT 'プライベートの会話から' (JA) / 'From a private conversation' (EN)
            SECTION/GROUPING (sometimes channel name)
            STATICTEXT ' | '
            STATICTEXT [time, e.g. '今日の08:45' / 'Today at 8:45 AM']
    """
    try:
        link_role = controlTypes.Role.LINK
    except AttributeError:
        link_role = controlTypes.ROLE_LINK
    try:
        section_role = controlTypes.Role.SECTION
    except AttributeError:
        section_role = controlTypes.ROLE_SECTION
    try:
        grouping_role = controlTypes.Role.GROUPING
    except AttributeError:
        grouping_role = controlTypes.ROLE_GROUPING
    try:
        static_role = controlTypes.Role.STATICTEXT
    except AttributeError:
        static_role = controlTypes.ROLE_STATICTEXT

    # Container roles that may hold the unfurl card.
    # Japanese Slack uses SECTION; English uses GROUPING.
    container_roles = (section_role, grouping_role)

    # Footer text that begins the card's metadata strip ("From a private
    # conversation | <time>"). Used to split body from time. Add more
    # locales here as we observe them.
    FOOTER_MARKERS = {
        "プライベートの会話から",
        "From a private conversation",
    }
    SEPARATOR = "|"
    SKIP_TEXTS = {SEPARATOR, "もっと表示する", "Show more"}

    results = {}

    def _find_embedded_permalinks(node, max_depth=10, depth=0):
        """Yield (link_node, url) for embedded Slack permalink LINK nodes.

        The listitem's own permalink also matches _SLACK_PERMALINK_PATTERN
        but uses a timestamp string as its `name` (e.g. '今日 09:12:32 ').
        Embedded permalinks display the raw URL as the name, so gate on
        name.startswith('http').
        """
        if depth > max_depth:
            return
        try:
            child = node.firstChild
        except Exception:
            return
        while child is not None:
            try:
                if child.role == link_role:
                    name = (child.name or "")
                    if name.startswith("http") and _SLACK_PERMALINK_PATTERN.match(name):
                        yield child, name
                yield from _find_embedded_permalinks(child, max_depth, depth + 1)
            except Exception:
                pass
            try:
                child = child.next
            except Exception:
                break

    def _next_card_section(link_node):
        """Walk forward through link_node's siblings; return first non-empty
        container (SECTION in JA UI, GROUPING in EN UI)."""
        try:
            sib = link_node.next
        except Exception:
            return None
        while sib is not None:
            try:
                if sib.role in container_roles and sib.firstChild is not None:
                    return sib
            except Exception:
                pass
            try:
                sib = sib.next
            except Exception:
                break
        return None

    def _collect_statictext(node, out, max_depth=10, depth=0):
        """Depth-first collect STATICTEXT names from node's subtree.

        Recurse into empty-name STATICTEXT containers because English Slack
        wraps a real STATICTEXT name inside an outer STATICTEXT with no name
        (where JA Slack uses TEXTFRAME). For a non-empty STATICTEXT we
        capture and stop, avoiding double-collection in trees where Slack
        does not nest text under itself.
        """
        if depth > max_depth:
            return
        try:
            child = node.firstChild
        except Exception:
            return
        while child is not None:
            try:
                if child.role == static_role:
                    name = child.name or ""
                    if name:
                        out.append(name)
                    else:
                        _collect_statictext(child, out, max_depth, depth + 1)
                else:
                    _collect_statictext(child, out, max_depth, depth + 1)
            except Exception:
                pass
            try:
                child = child.next
            except Exception:
                break

    for link_node, url in _find_embedded_permalinks(obj):
        card = _next_card_section(link_node)
        if card is None:
            continue
        parts = []
        _collect_statictext(card, parts)
        # Filter decorative separators / control text.
        parts = [p for p in parts if p.strip() and p.strip() not in SKIP_TEXTS]
        if not parts:
            continue

        sender = parts[0]
        rest = parts[1:]

        # Locate footer marker; everything before it is body.
        footer_idx = len(rest)
        for i, p in enumerate(rest):
            if p.strip() in FOOTER_MARKERS:
                footer_idx = i
                break

        body_parts = rest[:footer_idx]
        footer_parts = rest[footer_idx + 1:]  # Skip the marker itself

        body = " ".join(body_parts).strip()
        time = footer_parts[-1].strip() if footer_parts else ""

        results[url] = {"sender": sender, "time": time, "body": body}

    return results


def _strip_x_branding_suffix(text):
    """Remove a trailing "/ X" branding suffix, with optional closing bracket.

    Done with string operations rather than a regex: the equivalent pattern
    needs a whitespace quantifier next to the anchor, which backtracks on long
    whitespace runs. Text that does not end in the suffix is returned unchanged
    apart from trailing whitespace, so a tweet ending in a bare "X" survives.
    """
    stripped = text.rstrip()
    candidate = stripped[:-1].rstrip() if stripped.endswith("」") else stripped
    if not candidate.endswith("X"):
        return stripped
    candidate = candidate[:-1].rstrip()
    if not candidate.endswith("/"):
        return stripped
    return candidate[:-1].rstrip()


def _strip_x_card_wrapper(text):
    """Strip Slack's Japanese attribution wrapper from collected card text.

    Slack wraps the tweet card as "Xユーザーの{name}さん: 「{tweet} / X」".
    Returns the bare tweet text, or None if nothing is left.
    """
    text = re.sub(r'^Xユーザーの[^：:]+[：:]\s*', '', text)
    text = text.lstrip('「')
    text = _strip_x_branding_suffix(text)
    return text.rstrip('」').strip() or None


def _is_x_author_link(child, name, link_role, button_role):
    """True if child is the card's author link ("Name (@handle) on X").

    LINK or BUTTON is accepted so the check survives Slack/UIA differences.
    """
    return (
        child.role in (link_role, button_role)
        and name.endswith(_X_AUTHOR_LINK_SUFFIX)
    )


def _visit_x_card_child(child, name, roles, state, collected):
    """Apply the card-boundary state machine to one child node.

    Returns True if the node is the author link, which the caller uses to
    decide whether to recurse (we never descend into the author link).
    """
    link_role, image_role, button_role = roles
    is_author_link = _is_x_author_link(child, name, link_role, button_role)

    if not state["collecting"]:
        if is_author_link:
            state["collecting"] = True
    elif name.startswith(_X_CARD_END_MARKER):
        state["done"] = True
    elif not is_author_link and child.role not in (link_role, image_role) and name:
        collected.append(name)
    return is_author_link


def _extract_x_preview_text_from_tree(obj):
    """Walk the accessibility tree to find X post preview text.

    Slack renders X URLs it did not unfurl with a preview card whose structure is:
      ... → "Name (@handle) on X" LINK (start marker, may appear twice)
          → tweet text elements (TEXT/STATICTEXT, variable count)
          → "X (formerly Twitter)" IMAGE or TEXT (end marker)
          → ...

    Returns joined tweet text, or None if the pattern is not found.
    Note: when multiple X URLs appear in one message, all are mapped to the
    text of the first preview card found (subsequent cards are ignored).
    """
    roles = (
        _link_role(),
        _role_or_legacy("GRAPHIC"),
        _role_or_legacy("BUTTON"),
    )

    state = {"collecting": False, "done": False}
    collected = []
    dbg = {"checked": 0}

    def _walk(node):
        if state["done"]:
            return
        try:
            child = node.firstChild
            while child and not state["done"]:
                dbg["checked"] += 1
                is_author_link = _visit_x_card_child(
                    child, child.name or "", roles, state, collected
                )
                if not is_author_link:
                    _walk(child)
                child = child.next
        except Exception:
            pass

    _walk(obj)
    result = " ".join(collected) if collected else None
    if result and not state["done"]:
        # 終了マーカーが現れないまま走査が終わった場合、収集はカードの外まで
        # 走っており、リアクションやアクションメニューが混入している
        # (Slack 4.51.180 で確認)。境界が確定できない収集結果は本文として
        # 信頼できないので破棄し、oEmbed 経路に委ねる。
        result = None
    if result:
        result = _strip_x_card_wrapper(result)
    log.info(
        f"slackAppModule: _extract_x_preview_text_from_tree: "
        f"checked={dbg['checked']}, on_x_found={state['collecting']}, "
        f"end_marker_found={state['done']}, "
        f"collected={collected!r}, result={result!r}"
    )
    return result


def parse_slack_message(name_text):
    result = {
        "sender": "",
        "mention_info": "",
        "body": "",
        "time": "",
        "link_count": "",
        "reactions": "",
        "replies": "",
        "attachments": "",
        "level": "",
        "urls": [],
        "unfurl_titles": [],
        "chip_link_displays": [],
        "raw": name_text,
        "lang": "en",
    }
    if not name_text:
        return result
    text = name_text

    # 1. 言語検出
    lang = _detect_lang(text)
    patterns = _PATTERNS[lang]
    result["lang"] = lang

    # 2. メタデータサフィックス除去 + 個別フィールド抽出
    meta_match = patterns["metadata_suffix"].search(text)
    if meta_match:
        meta_str = meta_match.group()
        text = text[:meta_match.start()]

        m = patterns["time"].search(meta_str)
        if m:
            result["time"] = (m.group(1) or m.group(2) or "").strip()

        m = patterns["link_count"].search(meta_str)
        if m:
            result["link_count"] = m.group(1)

        m = patterns["reaction"].search(meta_str)
        if m:
            result["reactions"] = m.group(0)

        m = patterns["replies"].search(meta_str)
        if m:
            result["replies"] = m.group(0)

        m = patterns["attachment"].search(meta_str)
        if m:
            result["attachments"] = m.group(1)

    # 3. メンション解析（言語別）
    mention_match = patterns["mention_prefix"].match(text)
    if mention_match:
        result["sender"] = mention_match.group(1).strip()
        result["mention_info"] = _("{user} mentioned you in #{channel}").format(
            user=mention_match.group(1).strip(),
            channel=mention_match.group(2)
        )
        text = text[mention_match.end():]
    else:
        sender_match = SENDER_PATTERN.match(text)
        if sender_match:
            result["sender"] = sender_match.group(1).strip()
            text = text[sender_match.end():]

    # 3.5. 転送ヘッダー解析（言語別）
    fwd_match = patterns["forwarded_header"].match(text)
    if fwd_match:
        comment = fwd_match.group(1)
        channel = fwd_match.group(2)
        replacement = patterns["forwarded_template"].format(
            comment=comment, channel=channel
        )
        text = replacement + text[fwd_match.end():]

    # 4. 本文（末尾の句点/ピリオド除去）
    result["body"] = text.strip().rstrip(patterns["body_trail"]).strip()

    # 5. Unfurlリンク抽出（言語別）
    # URL そのものはタイトルではないので除外（URL フェッチ経路で処理される）
    # X カード形式 "(N) Xユーザーの…: 「tweet」 / X" はツイート本文のみ抽出し、
    # ブロック自体は本文から除去する（展開すると不要な URL が混入するため）。
    unfurl_matches = patterns["unfurl_link"].findall(result["body"])
    if unfurl_matches:
        titles = []
        chip_link_displays = []
        for m in unfurl_matches:
            m = m.strip()
            if m.startswith("http"):
                continue
            if URL_DISPLAY_PATTERN.match(m):
                # Schemeless / truncated URL display: not a title. The real
                # href is recovered later from the accessibility tree.
                chip_link_displays.append(m)
                continue
            x_m = _JA_X_UNFURL_PATTERN.match(m)
            if x_m:
                tweet = x_m.group(1).strip()
                tweet = re.sub(r"\s*https?://t\.co/\S+", "", tweet).strip()
                if tweet:
                    titles.append(tweet)
            else:
                titles.append(m)
        result["unfurl_titles"] = titles
        result["chip_link_displays"] = chip_link_displays

        def _replace_unfurl(match):
            content = match.group(1).strip()
            if content.startswith("http"):
                return content  # raw URL: keep for URL extraction
            if URL_DISPLAY_PATTERN.match(content):
                return ""  # schemeless URL display: drop; href recovered from tree
            if _JA_X_UNFURL_PATTERN.match(content):
                return ""  # X card: remove entirely
            return content  # regular title: expand inline

        result["body"] = patterns["unfurl_link"].sub(_replace_unfurl, result["body"]).strip()
        result["body"] = result["body"].rstrip(patterns["body_trail"]).strip()

    # 6. URL抽出（言語非依存）
    result["urls"] = URL_PATTERN.findall(result["body"])
    return result


def _is_sweeper_enabled():
    """globalPlugin 側の共通フラグを参照"""
    try:
        from globalPlugins.teamsMessageSweeper import GlobalPlugin
        return GlobalPlugin._processing_enabled
    except Exception:
        return True


def _get_level_from_obj(obj):
    """obj.positionInfo['level'] を取得して文字列で返す。

    Slack の通知一覧などでは NVDA が positionInfo.level から「レベル N」を
    自動読み上げするが、Sweeper の speech.cancelSpeech() がこの自動発話を
    キャンセルしてしまう。そのため Sweeper 側で positionInfo を読んで
    読み上げ末尾に再度含める必要がある。
    """
    try:
        info = getattr(obj, "positionInfo", None)
        if info:
            level = info.get("level")
            if level:
                return str(level)
    except Exception:
        pass
    return ""


def _initial_parts(parsed):
    """Sender / mention prefix that every announcement starts with."""
    if parsed["mention_info"]:
        return [parsed["mention_info"]]
    if parsed["sender"]:
        return [parsed["sender"]]
    return []


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
        insert_idx = 1 if (parsed["mention_info"] or parsed["sender"]) else 0
        parts.insert(insert_idx, summary)
    else:
        parts.append(summary)


def _append_metadata(parts, parsed, include_link_count=True, include_level=True):
    """Append time / reactions / counts in the order each path announces them.

    link_count is omitted on the no-URL path and level on the tree-unfurl path,
    matching what those paths announced before this was factored out.
    """
    if parsed["time"]:
        parts.append(_("Time {time}").format(time=parsed["time"]))
    if parsed["reactions"]:
        parts.append(parsed["reactions"])
    if include_link_count and parsed["link_count"]:
        parts.append(_("{count} links").format(count=parsed["link_count"]))
    if parsed["replies"]:
        parts.append(parsed["replies"])
    if parsed["attachments"]:
        parts.append(_("{count} attachments").format(count=parsed["attachments"]))
    if include_level and parsed["level"]:
        parts.append(_("Level {level}").format(level=parsed["level"]))


def _non_url_body(parsed):
    """Body text with URLs and any embedded X card removed, whitespace collapsed."""
    body = URL_PATTERN.sub("", parsed["body"]).strip()
    body = re.sub(r'\s+', ' ', body).strip()
    return _X_CARD_BODY_PATTERN.sub('', body).strip()


def _link_line(title):
    """The "Link: <title>" line every announcement path emits."""
    return _("Link: {title}").format(title=title)


def _x_display_title(title, x_preview):
    """Prefer extracted tweet text over the card's author-link name."""
    if title.endswith(_X_AUTHOR_LINK_SUFFIX) and x_preview:
        return x_preview
    return title


def _build_parsed_message(obj):
    """Parse obj.name into the structured message dict and clean the body."""
    parsed = parse_slack_message(obj.name)
    parsed["level"] = _get_level_from_obj(obj)
    cleaned = clean_message_body(parsed["body"], parsed["lang"])
    parsed["body"] = cleaned.text
    parsed["skipped_emoji"] = cleaned.skipped_emoji
    return parsed


def _inline_one_permalink_card(url, cards, parsed, sep):
    """Inline one Slack-permalink card into the body. True when inlined."""
    # URL_PATTERN excludes Japanese punctuation but allows ASCII '.' in URLs, so
    # English Slack messages capture the URL with a trailing period. Keys from
    # the tree never include trailing punctuation, so normalize for lookup.
    info = cards.get(url) or cards.get(url.rstrip(".,;:!?"))
    if not info:
        return False
    # Skip when Slack already flattened the card into obj.name (avoid a
    # duplicate readout). Language-agnostic: if the extracted body already
    # appears in the parsed body, the card was inlined upstream.
    if info["body"] and info["body"] in parsed["body"]:
        return False
    if info["time"]:
        formatted = _("Shared by {sender} at {time}: {body}").format(
            sender=info["sender"], time=info["time"], body=info["body"])
    else:
        formatted = _("Shared by {sender}: {body}").format(
            sender=info["sender"], body=info["body"])
    # Replace the URL itself with the formatted card so the URL is not
    # announced separately and the body reads naturally inline.
    if url in parsed["body"]:
        parsed["body"] = parsed["body"].replace(url, formatted, 1).strip()
    else:
        parsed["body"] = (parsed["body"] + sep + formatted).strip()
    # Drop the URL so the background fetcher does not announce the useless
    # "Slack" page title for it.
    parsed["urls"] = [u for u in parsed["urls"] if u != url]
    return True


def _inline_permalink_cards(obj, parsed, sep):
    """Inline Slack-permalink unfurl cards recovered from the tree.

    Slack normally flattens an embedded message's card into obj.name. When it
    does not, the card body lives in a sibling SECTION.
    """
    permalink_urls = [
        u for u in parsed["urls"] if _SLACK_PERMALINK_PATTERN.match(u)
    ]
    if not permalink_urls:
        return
    cards = _extract_slack_permalink_unfurl_text(obj)
    extracted_for = {
        url for url in permalink_urls
        if _inline_one_permalink_card(url, cards, parsed, sep)
    }
    # DIAG: log when we knew there was a permalink but extracted nothing.
    missed = [u for u in permalink_urls if u not in extracted_for]
    if missed:
        log.info(
            f"slackAppModule: Slack permalink extraction missed: {missed!r}"
        )


def _recover_chip_links(obj, parsed):
    """Recover real hrefs for Slack "link chip" displays via the tree.

    When a link's accessible name is a schemeless / truncated display URL, the
    real href lives in the LINK node's value. Recovering it lets the message
    flow through the normal tree-title / fetch path instead of announcing the
    chip text.
    """
    if not parsed.get("chip_link_displays"):
        return
    resolved = _resolve_chip_link_hrefs(obj, parsed["chip_link_displays"])
    log.info(
        f"slackAppModule: chip link recovery: "
        f"displays={parsed['chip_link_displays']!r}, resolved={resolved!r}"
    )
    _merge_chip_links(parsed, resolved)


def _resolve_tree_titles(obj):
    """Unfurl titles from the tree, plus extracted X card text when present.

    Returns (tree_titles, x_preview). When the card is an X card whose body
    cannot be extracted, tree_titles is emptied so the caller falls through to
    the URL fetch path: announcing the author-link name and returning would
    make the oEmbed fallback unreachable.
    """
    tree_titles = _find_unfurl_titles_in_tree(obj)
    x_preview = None
    if any(t.endswith(_X_AUTHOR_LINK_SUFFIX) for t in tree_titles):
        x_preview = _extract_x_preview_text_from_tree(obj)
        if not x_preview:
            log.info(
                "slackAppModule: X card tree extraction failed; "
                "falling through to URL fetch path"
            )
            tree_titles = []
    if tree_titles:
        log.info(f"slackAppModule: Found unfurl titles in tree: {tree_titles!r}")
    return tree_titles, x_preview


def _speak_and_finish(obj, next_handler, processed_name, context):
    """Set obj.name so braille picks it up, run next_handler, then speak."""
    obj.name = processed_name
    try:
        next_handler()
    except Exception:
        log.debugWarning(
            f"slackAppModule: error in next_handler for {context}",
            exc_info=True,
        )
    speech.cancelSpeech()
    speech.speakMessage(processed_name)


def _announce_unfurl_only(obj, next_handler, parsed, sep, summary_pos, parts):
    """Unfurl titles with no URLs to fetch: everything is already known."""
    body = _X_CARD_BODY_PATTERN.sub('', parsed["body"]).strip()
    if body:
        parts.append(body)
    log.info(
        f"slackAppModule: unfurl path: unfurl_titles={parsed['unfurl_titles']!r}, "
        f"urls={parsed['urls']!r}"
    )
    x_preview = None
    if any(t.endswith(_X_AUTHOR_LINK_SUFFIX) for t in parsed["unfurl_titles"]):
        x_preview = _extract_x_preview_text_from_tree(obj)
    for title in parsed["unfurl_titles"]:
        parts.append(_link_line(_x_display_title(title, x_preview)))
    _append_emoji_summary(parts, parsed, summary_pos)
    _append_metadata(parts, parsed)
    _speak_and_finish(obj, next_handler, sep.join(parts), "unfurl listitem")


def _announce_tree_titles(obj, next_handler, parsed, sep, summary_pos, parts,
                          tree_titles, x_preview):
    """Titles recovered from the unfurl card in the tree: no network needed."""
    body = _non_url_body(parsed)
    if body:
        parts.append(body)
    for title in tree_titles:
        parts.append(_link_line(_x_display_title(title, x_preview)))
    _append_emoji_summary(parts, parsed, summary_pos)
    _append_metadata(parts, parsed, include_level=False)
    _speak_and_finish(obj, next_handler, sep.join(parts), "tree-unfurl listitem")


def _announce_plain_message(obj, next_handler, parsed, sep, summary_pos, parts):
    """No URLs and no unfurl titles: cleaned body plus metadata."""
    if parsed["body"]:
        parts.append(parsed["body"])
    _append_emoji_summary(parts, parsed, summary_pos)
    _append_metadata(parts, parsed, include_link_count=False)
    if not parts:
        next_handler()
        return
    _speak_and_finish(obj, next_handler, sep.join(parts), "listitem")


class AppModule(appModuleHandler.AppModule):

    _title_cache = TitleCache()

    def event_gainFocus(self, obj, next_handler):
        if not self._should_process(obj, next_handler):
            return

        parsed = _build_parsed_message(obj)
        summary_pos = _summary_position()
        sep = _PATTERNS[parsed["lang"]]["sentence_sep"] + " "

        _inline_permalink_cards(obj, parsed, sep)
        _recover_chip_links(obj, parsed)

        parts = _initial_parts(parsed)

        if parsed["unfurl_titles"] and not parsed["urls"]:
            _announce_unfurl_only(obj, next_handler, parsed, sep, summary_pos, parts)
            return
        if not parsed["urls"]:
            _announce_plain_message(obj, next_handler, parsed, sep, summary_pos, parts)
            return

        tree_titles, x_preview = _resolve_tree_titles(obj)
        if tree_titles:
            _announce_tree_titles(
                obj, next_handler, parsed, sep, summary_pos, parts,
                tree_titles, x_preview,
            )
            return

        processed_name = self._build_pending_name(parsed, sep, summary_pos, parts)
        _speak_and_finish(obj, next_handler, processed_name, "listitem")
        self._start_url_fetch(obj, parsed, processed_name)

    def _should_process(self, obj, next_handler):
        """Guard clauses for event_gainFocus.

        Returns False (after passing the event on) when this focus event is not
        a Slack message list item we should rewrite.
        """
        if not _is_sweeper_enabled():
            next_handler()
            return False

        log.info(
            f"slackAppModule: event_gainFocus fired. "
            f"role={obj.role}, name={obj.name!r}"
        )

        if obj.role != _role_or_legacy("LISTITEM"):
            try:
                next_handler()
            except Exception:
                log.debugWarning(
                    "slackAppModule: error in next_handler for non-listitem",
                    exc_info=True,
                )
            return False

        if not (hasattr(obj, "name") and obj.name):
            next_handler()
            return False
        return True

    def _build_pending_name(self, parsed, sep, summary_pos, parts):
        """Text spoken immediately, before link titles have been fetched."""
        body = _non_url_body(parsed)
        if body:
            parts.append(body)
        _append_emoji_summary(parts, parsed, summary_pos)
        if parts:
            return sep.join(parts)
        return _("{sender}. Fetching link titles...").format(
            sender=parsed["sender"])

    def _start_url_fetch(self, obj, parsed, processed_name):
        """Resolve link titles, announcing immediately when nothing needs fetching."""
        urls_to_fetch, url_title_map = self._partition_cached_urls(parsed)
        urls_to_fetch = self._resolve_x_urls_from_tree(
            obj, urls_to_fetch, url_title_map
        )

        if not urls_to_fetch:
            self._announce_links_and_meta(parsed, url_title_map, processed_name)
            return

        threading.Thread(
            target=self._fetch_and_speak,
            args=(urls_to_fetch, url_title_map, parsed, processed_name),
            daemon=True,
        ).start()

    def _partition_cached_urls(self, parsed):
        """Split parsed URLs into (needs fetching, already-known titles).

        X URLs cached as None (from a previous failed fetch) are retried via
        tree extraction rather than reusing the stale None.
        """
        urls_to_fetch = []
        url_title_map = {}
        for url in parsed["urls"]:
            if url not in self._title_cache:
                urls_to_fetch.append(url)
                continue
            cached = self._title_cache.get(url)
            if cached is None and TWITTER_PATTERN.match(url):
                urls_to_fetch.append(url)
            else:
                url_title_map[url] = cached
        return urls_to_fetch, url_title_map

    def _resolve_x_urls_from_tree(self, obj, urls_to_fetch, url_title_map):
        """Try the accessibility tree for X URLs before going to the network.

        Synchronous and network-free, so it is the cheapest path when the card
        is in the DOM. Returns the URLs still needing a fetch; those fall
        through to the X oEmbed API in the background thread (see
        _fetch_url_title).
        """
        still_needed = []
        for url in urls_to_fetch:
            x_text = (
                _extract_x_preview_text_from_tree(obj)
                if TWITTER_PATTERN.match(url) else None
            )
            if not x_text:
                still_needed.append(url)
                continue
            self._title_cache.put(url, x_text)
            url_title_map[url] = x_text
        return still_needed

    def _fetch_url_title(self, url):
        """Dispatch URL title fetching: oEmbed for X posts, HTTP fetch otherwise.

        X URLs always fail HTTP fetching (X blocks bot scrapers) but expose the
        tweet body via the twitter oEmbed API. Slack normally renders an
        unfurl card that we extract from the accessibility tree, but when the
        card is missing (duplicate suppression, transient unfurl failures, the
        user manually removed the preview, etc.) oEmbed is the only fallback.
        """
        if TWITTER_PATTERN.match(url):
            return fetch_x_post_via_oembed(url)
        return fetch_page_title(url)

    def _fetch_and_speak(self, urls_to_fetch, url_title_map, parsed, immediate_text):
        """Background-thread URL title fetcher and announcement scheduler."""
        import time as _time
        fetch_start = _time.perf_counter()
        for url in urls_to_fetch:
            url_start = _time.perf_counter()
            title = self._fetch_url_title(url)
            url_elapsed = _time.perf_counter() - url_start
            log.info(
                f"slackAppModule: Fetched title for {url} "
                f"in {url_elapsed:.3f}s -> {title!r}"
            )
            self._title_cache.put(url, title)
            url_title_map[url] = title

        total_elapsed = _time.perf_counter() - fetch_start
        log.info(
            f"slackAppModule: Total fetch time for "
            f"{len(urls_to_fetch)} URL(s): {total_elapsed:.3f}s"
        )
        queueHandler.queueFunction(
            queueHandler.eventQueue,
            self._announce_links_and_meta,
            parsed,
            url_title_map,
            immediate_text,
        )

    def _announce_links_and_meta(self, parsed, url_title_map, immediate_text):
        link_parts = []
        lang = parsed.get("lang", "ja")
        sep = _PATTERNS[lang]["sentence_sep"] + " "

        for title in parsed.get("unfurl_titles", []):
            link_parts.append(_link_line(title))
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
            link_parts.append(_("Time {time}").format(time=parsed["time"]))
        if parsed["reactions"]:
            link_parts.append(parsed["reactions"])
        if parsed["link_count"]:
            link_parts.append(_("{count} links").format(count=parsed["link_count"]))
        if parsed["replies"]:
            link_parts.append(parsed["replies"])
        if parsed["attachments"]:
            link_parts.append(_("{count} attachments").format(count=parsed["attachments"]))
        if parsed["level"]:
            link_parts.append(_("Level {level}").format(level=parsed["level"]))
        if not link_parts:
            return

        link_text = sep.join(link_parts)

        # Speech: announce link titles
        speech.speakMessage(link_text)

        # Braille: build complete text and update the focus region
        complete_text = (
            immediate_text + sep + link_text if immediate_text else link_text
        )
        try:
            focus = api.getFocusObject()
            if focus:
                focus.name = complete_text
                braille.handler.handleGainFocus(focus)
        except Exception:
            log.debugWarning(
                "slackAppModule: error updating braille with complete text",
                exc_info=True,
            )
            braille.handler.message(braille.handler.messageTimeout, complete_text)
