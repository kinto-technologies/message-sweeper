# -*- coding: utf-8 -*-
"""Tests for URL title fetching in fetcher.py."""
import os
import sys
import types
import unittest
from io import BytesIO
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon"))

sys.modules.setdefault("logHandler", types.ModuleType("logHandler"))
sys.modules["logHandler"].log = types.SimpleNamespace(
    info=lambda *a, **kw: None,
    debugWarning=lambda *a, **kw: None,
)

from shared.fetcher import fetch_page_title, TitleParser, fetch_x_post_via_oembed


def _make_response(html_bytes, content_type="text/html; charset=UTF-8"):
    """Return a mock urllib response that streams like a real HTTP response."""
    resp = MagicMock()
    resp.headers.get.return_value = content_type
    resp.geturl.return_value = "https://example.com/"
    buf = BytesIO(html_bytes)
    resp.read = buf.read
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestTitleParserBasic(unittest.TestCase):
    def test_extracts_title(self):
        p = TitleParser()
        p.feed("<html><head><title>Hello World</title></head></html>")
        self.assertEqual(p.title, "Hello World")

    def test_empty_when_no_title(self):
        p = TitleParser()
        p.feed("<html><head></head></html>")
        self.assertEqual(p.title, "")


class TestFetchPageTitle(unittest.TestCase):
    def _urlopen_ctx(self, html_bytes, content_type="text/html; charset=UTF-8"):
        resp = _make_response(html_bytes, content_type)
        return patch("shared.fetcher.urlopen", return_value=resp)

    def test_returns_title_when_title_is_in_first_64kb(self):
        html = b"<html><head><title>My Page</title></head><body></body></html>"
        with self._urlopen_ctx(html):
            result = fetch_page_title("https://example.com/page")
        self.assertEqual(result, "My Page")

    def test_title_beyond_65536_bytes_is_still_found(self):
        # Simulate a Wix-like page where <title> is at byte ~131000
        padding = b" " * 131000
        html = b"<html><head>" + padding + b"<title>About | Example Corp</title></head></html>"
        with self._urlopen_ctx(html):
            result = fetch_page_title("https://example.com/about")
        self.assertEqual(result, "About | Example Corp")

    def test_returns_none_when_no_title_tag(self):
        html = b"<html><head></head><body>No title here</body></html>"
        with self._urlopen_ctx(html):
            result = fetch_page_title("https://example.com/notitle")
        self.assertIsNone(result)

    def test_returns_none_on_network_error(self):
        with patch("shared.fetcher.urlopen", side_effect=OSError("connection refused")):
            result = fetch_page_title("https://unreachable.example.com/")
        self.assertIsNone(result)

    def test_github_url_non_html_returns_repo_name(self):
        resp = _make_response(b"", content_type="application/octet-stream")
        with patch("shared.fetcher.urlopen", return_value=resp):
            result = fetch_page_title("https://github.com/kinto-technologies/message-sweeper")
        self.assertEqual(result, "message-sweeper")

    def test_private_ip_host_blocked_no_urlopen(self):
        with patch("shared.fetcher._is_safe_host", return_value=False) as safe_mock, \
             patch("shared.fetcher.urlopen") as urlopen_mock:
            result = fetch_page_title("http://192.168.1.1/admin")
        self.assertIsNone(result)
        safe_mock.assert_called()
        urlopen_mock.assert_not_called()

    def test_safe_host_proceeds_to_urlopen(self):
        html = b"<html><head><title>OK</title></head></html>"
        resp = _make_response(html)
        with patch("shared.fetcher._is_safe_host", return_value=True), \
             patch("shared.fetcher.urlopen", return_value=resp) as urlopen_mock:
            result = fetch_page_title("https://example.com/")
        self.assertEqual(result, "OK")
        urlopen_mock.assert_called_once()

    def test_github_url_with_private_host_returns_fallback(self):
        # Even if a malicious DNS points github.com at a private IP, we should
        # still produce the GitHub fallback title without network access.
        with patch("shared.fetcher._is_safe_host", return_value=False), \
             patch("shared.fetcher.urlopen") as urlopen_mock:
            result = fetch_page_title("https://github.com/kinto-technologies/message-sweeper")
        self.assertEqual(result, "message-sweeper")
        urlopen_mock.assert_not_called()

    def test_redirect_to_private_host_blocked(self):
        # Pretend the redirect handler is asked to follow a redirect to 10.0.0.1.
        from shared.fetcher import _SafeRedirectHandler
        from urllib.request import HTTPError
        handler = _SafeRedirectHandler()
        with patch("shared.fetcher._is_safe_host", return_value=False):
            with self.assertRaises(HTTPError):
                handler.redirect_request(
                    req=MagicMock(),
                    fp=MagicMock(),
                    code=302,
                    msg="Found",
                    headers=MagicMock(),
                    newurl="http://10.0.0.1/admin",
                )

    def test_redirect_to_public_host_allowed(self):
        from shared.fetcher import _SafeRedirectHandler
        handler = _SafeRedirectHandler()
        # Patch the parent class redirect_request to avoid touching the network.
        with patch("shared.fetcher._is_safe_host", return_value=True), \
             patch(
                 "urllib.request.HTTPRedirectHandler.redirect_request",
                 return_value="ok",
             ) as parent_mock:
            out = handler.redirect_request(
                req=MagicMock(),
                fp=MagicMock(),
                code=302,
                msg="Found",
                headers=MagicMock(),
                newurl="https://example.com/",
            )
        self.assertEqual(out, "ok")
        parent_mock.assert_called_once()


class TestFetchXPostViaOembed(unittest.TestCase):
    _OEMBED_HTML = (
        '<blockquote class="twitter-tweet">'
        '<p lang="ja" dir="ltr">「今日のお昼ごはん」という写真です。'
        '<a href="https://t.co/EXAMPLE0002">https://t.co/EXAMPLE0002</a></p>'
        '&mdash; サンプル太郎 (@example_user) '
        '<a href="https://twitter.com/example_user/status/1234567890000000004">December 14, 2025</a>'
        '</blockquote>'
    )
    _OEMBED_JSON = (
        '{"url":"https://twitter.com/example_user/status/1234567890000000004",'
        '"author_name":"サンプル太郎",'
        '"html":"' + _OEMBED_HTML.replace('"', '\\"') + '"}'
    ).encode("utf-8")

    def _oembed_ctx(self):
        resp = MagicMock()
        resp.read.return_value = self._OEMBED_JSON
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return patch("shared.fetcher.urlopen", return_value=resp)

    def test_returns_tweet_text_from_oembed(self):
        with self._oembed_ctx():
            result = fetch_x_post_via_oembed(
                "https://x.com/example_user/status/1234567890000000004"
            )
        self.assertEqual(result, "「今日のお昼ごはん」という写真です。")

    def test_strips_tco_urls_from_tweet_text(self):
        with self._oembed_ctx():
            result = fetch_x_post_via_oembed(
                "https://x.com/example_user/status/1234567890000000004"
            )
        self.assertNotIn("t.co", result)

    def test_returns_none_on_network_error(self):
        with patch("shared.fetcher.urlopen", side_effect=OSError("timeout")):
            result = fetch_x_post_via_oembed(
                "https://x.com/unknown/status/123"
            )
        self.assertIsNone(result)

    def test_returns_none_when_oembed_has_no_p_tag(self):
        bad_json = b'{"html": "<blockquote>no paragraph here</blockquote>"}'
        resp = MagicMock()
        resp.read.return_value = bad_json
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("shared.fetcher.urlopen", return_value=resp):
            result = fetch_x_post_via_oembed("https://x.com/user/status/1")
        self.assertIsNone(result)


class TestIsSafeHost(unittest.TestCase):
    def _mock_getaddrinfo(self, ips):
        """Build a getaddrinfo return value that yields the given IPs."""
        import socket as _socket
        return [
            (_socket.AF_INET if "." in ip else _socket.AF_INET6, 0, 0, "", (ip, 0))
            for ip in ips
        ]

    def _with_dns(self, ips):
        from shared import fetcher
        return patch.object(
            fetcher.socket, "getaddrinfo",
            return_value=self._mock_getaddrinfo(ips),
        )

    def test_public_ipv4_is_safe(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["8.8.8.8"]):
            self.assertTrue(_is_safe_host("dns.google"))

    def test_public_ipv6_is_safe(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["2001:4860:4860::8888"]):
            self.assertTrue(_is_safe_host("dns.google"))

    def test_loopback_v4_blocked(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["127.0.0.1"]):
            self.assertFalse(_is_safe_host("localhost"))

    def test_loopback_v6_blocked(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["::1"]):
            self.assertFalse(_is_safe_host("localhost"))

    def test_rfc1918_10_8_blocked(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["10.0.0.1"]):
            self.assertFalse(_is_safe_host("internal.example"))

    def test_rfc1918_192_168_blocked(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["192.168.1.1"]):
            self.assertFalse(_is_safe_host("router.local"))

    def test_rfc1918_172_16_blocked(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["172.16.0.1"]):
            self.assertFalse(_is_safe_host("internal.example"))

    def test_link_local_v4_blocked(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["169.254.169.254"]):
            self.assertFalse(_is_safe_host("metadata.example"))

    def test_link_local_v6_blocked(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["fe80::1"]):
            self.assertFalse(_is_safe_host("router.local"))

    def test_ula_v6_blocked(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["fc00::1"]):
            self.assertFalse(_is_safe_host("ula.local"))

    def test_any_private_in_mixed_list_blocks(self):
        from shared.fetcher import _is_safe_host
        with self._with_dns(["8.8.8.8", "192.168.1.1"]):
            self.assertFalse(_is_safe_host("dualhomed.example"))

    def test_dns_failure_blocks(self):
        from shared.fetcher import _is_safe_host
        from shared import fetcher
        with patch.object(fetcher.socket, "getaddrinfo", side_effect=OSError("name resolution failed")):
            self.assertFalse(_is_safe_host("nonexistent.example"))

    def test_cgnat_blocked(self):
        # RFC 6598 (100.64.0.0/10) — Carrier-Grade NAT range, not covered by
        # ipaddress.is_private but functionally private.
        from shared.fetcher import _is_safe_host
        with self._with_dns(["100.64.0.1"]):
            self.assertFalse(_is_safe_host("cgnat.example"))

        # Also verify the upper end of the CGNAT range
        with self._with_dns(["100.127.255.254"]):
            self.assertFalse(_is_safe_host("cgnat-upper.example"))

        # Sanity check: 100.63.x.x is NOT CGNAT (it's normal public)
        with self._with_dns(["100.63.255.255"]):
            self.assertTrue(_is_safe_host("public-near-cgnat.example"))


if __name__ == "__main__":
    unittest.main()
