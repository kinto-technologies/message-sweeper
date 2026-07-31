# -*- coding: utf-8 -*-
"""URL title fetching, HTML parsing, title caching, and link-announce formatting.

Importing this module also installs a urllib opener that blocks
redirects to private/loopback hosts (see _SafeRedirectHandler).
"""
import ipaddress
import json
import re
import socket
import threading
from urllib.request import (
    urlopen,
    Request,
    HTTPRedirectHandler,
    build_opener,
    install_opener,
    HTTPError,
)
from urllib.parse import quote as url_quote, urlparse
from html import unescape as html_unescape
from html.parser import HTMLParser

from logHandler import log
from shared.patterns import YOUTUBE_PATTERN, GITHUB_PATTERN

# --- Configuration ---
FETCH_TIMEOUT = 5
CACHE_MAX_SIZE = 200
# NOTE: Intentionally generic to avoid disclosing "NVDA addon / screen-reader
# user" via the User-Agent header (or via a project URL that resolves to that
# fact) to arbitrary servers the user happens to receive URLs from.
USER_AGENT = "Mozilla/5.0 (compatible; LinkPreview/1.0)"
_FETCH_CHUNK = 16384     # 16 KB per read
_FETCH_MAX_BYTES = 524288  # 512 KB cap
_TITLE_CLOSE_TAG = b"</title>"


class TitleCache:
    """Thread-safe URL title cache with size limit."""

    def __init__(self, max_size=CACHE_MAX_SIZE):
        self._cache = {}
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, url):
        with self._lock:
            return self._cache[url]

    def put(self, url, title):
        with self._lock:
            if len(self._cache) >= self._max_size:
                keys = list(self._cache.keys())
                for k in keys[:self._max_size // 4]:
                    del self._cache[k]
            self._cache[url] = title

    def __contains__(self, url):
        with self._lock:
            return url in self._cache


class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


# RFC 6598 — Carrier-Grade NAT shared address space. Python's
# ipaddress.IPv4Address.is_private does NOT include this range, but ISPs and
# some corporate networks use it as functionally private space, so treat it
# as unsafe for outbound fetches.
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _is_safe_host(host):
    """Return True iff every IP that the host resolves to is a public, routable address.

    Blocks any host whose DNS result contains a loopback / private (RFC 1918 / ULA) /
    link-local / reserved / multicast / unspecified / CGNAT (RFC 6598) address.
    DNS resolution failure is also treated as unsafe.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip_str = info[4][0]
            ip = ipaddress.ip_address(ip_str)
        except (ValueError, IndexError):
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
            or (ip.version == 4 and ip in _CGNAT_NETWORK)
        ):
            return False
    return True


class _SafeRedirectHandler(HTTPRedirectHandler):
    """HTTPRedirectHandler that aborts if a redirect target resolves to a private IP."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urlparse(newurl).hostname
        if host and not _is_safe_host(host):
            log.debugWarning(
                f"messageSweeper: blocked redirect to private/loopback host: {host}"
            )
            raise HTTPError(newurl, code, "blocked private redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Replace urllib's default opener so all urlopen() calls go through the safe
# redirect handler. This also lets existing tests that patch
# `shared.fetcher.urlopen` continue to work.
install_opener(build_opener(_SafeRedirectHandler()))


def _detect_charset(data, content_type):
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip().strip('"\'')
    raw = data[:4096].decode("ascii", errors="replace").lower()
    m = re.search(r'<meta\s+charset=["\']?([^"\'\s>]+)', raw)
    if m:
        return m.group(1)
    m = re.search(r'<meta[^>]+content=["\'][^"\']*charset=([^"\'\s;]+)', raw)
    if m:
        return m.group(1)
    return "utf-8"



def fetch_x_post_via_oembed(url):
    """Fetch tweet text for an X/Twitter URL via the oEmbed API."""
    oembed_url = (
        "https://publish.twitter.com/oembed?url="
        + url_quote(url, safe="")
        + "&omit_script=true"
    )
    try:
        req = Request(oembed_url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            html = data.get("html", "")
            m = re.search(r"<p[^>]*>(.*?)</p>", html, re.DOTALL)
            if not m:
                return None
            tweet_text = re.sub(r"<[^>]+>", "", m.group(1))
            tweet_text = html_unescape(tweet_text).strip()
            tweet_text = re.sub(r"\s*https?://t\.co/\S+", "", tweet_text).strip()
            return tweet_text if tweet_text else None
    except Exception as e:
        log.debugWarning(f"messageSweeper: Failed to fetch X oEmbed for {url}: {e}")
        return None


def _fetch_youtube_title(url):
    """Fetch YouTube video title via oEmbed API."""
    oembed_url = (
        "https://www.youtube.com/oembed?url="
        + url_quote(url, safe="")
        + "&format=json"
    )
    try:
        req = Request(oembed_url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            title = data.get("title", "").strip()
            return title if title else None
    except Exception as e:
        log.debugWarning(f"messageSweeper: Failed to fetch YouTube oEmbed for {url}: {e}")
        return None


def _title_from_github_url(url):
    """Extract a readable title from a GitHub URL structure."""
    m = GITHUB_PATTERN.match(url)
    if not m:
        return None
    repo = m.group(2)
    kind = m.group(3)  # pull, issues, commit, or None
    number = m.group(4)
    if kind == "pull" and number:
        return "{repo} PR #{number}".format(repo=repo, number=number)
    if kind == "issues" and number:
        return "{repo} Issue #{number}".format(repo=repo, number=number)
    if kind == "commit" and number:
        return "{repo} commit {short}".format(repo=repo, short=number[:7])
    return repo


def fetch_page_title(url):
    if YOUTUBE_PATTERN.match(url):
        return _fetch_youtube_title(url)
    host = urlparse(url).hostname
    if not host or not _is_safe_host(host):
        log.debugWarning(
            f"messageSweeper: blocked fetch for private/loopback host: {host}"
        )
        return _title_from_github_url(url)
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                return _title_from_github_url(url)
            chunks = []
            total = 0
            overlap = b""
            while total < _FETCH_MAX_BYTES:
                chunk = resp.read(_FETCH_CHUNK)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                window = overlap + chunk
                if _TITLE_CLOSE_TAG in window.lower():
                    break
                overlap = chunk[-(len(_TITLE_CLOSE_TAG) - 1):]
            data = b"".join(chunks)
            charset = _detect_charset(data, content_type)
            html_text = data.decode(charset, errors="replace")
            parser = TitleParser()
            parser.feed(html_text)
            title = re.sub(r'\s+', ' ', parser.title.strip())
            if title:
                return title
    except Exception as e:
        log.debugWarning(f"messageSweeper: Failed to fetch title for {url}: {e}")
    # フォールバック: GitHub URLならURLから情報を抽出
    return _title_from_github_url(url)


# URL shorteners whose host is meaningless to announce. When a title fetch fails
# for these, we stay silent regardless of link_failure_announce mode — the user
# gets no information from "Link: t.co (Title unavailable)" since t.co is just
# Twitter's internal redirect wrapper.
_SILENT_FAILURE_HOSTS = frozenset({"t.co"})


def format_link_announce(url, title, mode, templates):
    """Format the announce string for a URL/title pair under the given fallback mode.

    Args:
        url:        The URL being announced.
        title:      The fetched title, or None / empty string on failure.
        mode:       One of "silent", "label", "host", "url".
        templates:  Dict with keys "title", "label", "host", "url" — pre-translated
                    template strings using {title}, {host}, {url} placeholders.

    Returns:
        Announce string, or None when nothing should be spoken. URLs whose host
        is in _SILENT_FAILURE_HOSTS (e.g. t.co) always return None on failure
        regardless of mode, because the host name carries no meaning to the user.
    """
    if title:
        return templates["title"].format(title=title)
    host = urlparse(url).hostname
    if host and host.lower() in _SILENT_FAILURE_HOSTS:
        return None
    if mode == "label":
        return templates["label"]
    if mode == "host":
        if not host:
            return templates["label"]
        return templates["host"].format(host=host)
    if mode == "url":
        return templates["url"].format(url=url)
    # "silent" or unknown
    return None
