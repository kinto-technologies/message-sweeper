# -*- coding: utf-8 -*-
"""アクセシビリティツリー走査と、後追い読み上げの組み立てを固定するテスト。

対象は Slack 側の2箇所。どちらも Slack の DOM / アクセシビリティ表現が変わると
静かに壊れる層で、tests/test_slack_gain_focus_paths.py では mock で差し替えて
いるため中身が検証されていなかった。

  ・_find_unfurl_titles_in_tree — unfurl カードの奥にあるタイトルリンクを拾う
  ・AppModule._announce_links_and_meta — タイトル取得後の読み上げ文の組み立て

fixture は架空データ。実在の人名・URL・投稿本文は含まない。
"""
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon", "appModules"))

for mod_name in [
    "addonHandler", "appModuleHandler", "api", "braille", "nvwave",
    "speech", "ui", "controlTypes", "queueHandler", "logHandler",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

sys.modules["logHandler"].log = types.SimpleNamespace(
    info=lambda *a, **kw: None,
    debugWarning=lambda *a, **kw: None,
    warning=lambda *a, **kw: None,
)

# controlTypes.Role は他のテストモジュールと共有される。ここでは名前空間を
# 差し替えず、足りないロールだけ補う（走査テストは実行時に Role.LINK を使う
# ため、テスト側でも patch して順序に依存しないようにしている）。
_ct_role = getattr(sys.modules["controlTypes"], "Role", None)
if _ct_role is None:
    _ct_role = types.SimpleNamespace()
    sys.modules["controlTypes"].Role = _ct_role
for _role_name in ("LISTITEM", "LINK", "GRAPHIC", "BUTTON", "GROUP",
                   "SECTION", "GROUPING", "STATICTEXT"):
    if not hasattr(_ct_role, _role_name):
        setattr(_ct_role, _role_name, _role_name)

_mock_amh = sys.modules["appModuleHandler"]
if not hasattr(_mock_amh, "AppModule"):
    _mock_amh.AppModule = type("AppModule", (), {})

_mock_addon = sys.modules["addonHandler"]
_mock_addon.initTranslation = lambda: None
_mock_addon.getCodeAddon = lambda: types.SimpleNamespace(
    path=os.path.join(os.path.dirname(__file__), "..")
)

if "config" not in sys.modules:
    _mock_config = types.ModuleType("config")

    class _MockConfigDict(dict):
        def __init__(self):
            super().__init__()
            self.spec = {}

    _mock_config.conf = _MockConfigDict()
    sys.modules["config"] = _mock_config

import builtins
if "_" not in dir(builtins):
    builtins._ = lambda x: x

import slack
from slack import AppModule, _find_unfurl_titles_in_tree

LINK = "LINK"
SECTION = "SECTION"


class _Node:
    """アクセシビリティツリーのノード相当（firstChild / next で辿る形）。"""

    def __init__(self, role=SECTION, name="", children=()):
        self.role = role
        self.name = name
        self._children = list(children)
        self.next = None
        for older, younger in zip(self._children, self._children[1:]):
            older.next = younger

    @property
    def firstChild(self):
        return self._children[0] if self._children else None


def _nest(leaf, levels):
    """leaf を levels 段の SECTION で包んだノードを返す。"""
    node = leaf
    for _ in range(levels):
        node = _Node(children=[node])
    return node


class _TreeWalkTestCase(unittest.TestCase):
    """Role.LINK を実行時に固定してから走査する（モジュール読み込み順に依存しない）。"""

    def _titles(self, root):
        role_ns = types.SimpleNamespace(LINK=LINK, SECTION=SECTION)
        with patch.object(slack, "controlTypes",
                          types.SimpleNamespace(Role=role_ns)):
            return _find_unfurl_titles_in_tree(root)


class TestFindUnfurlTitlesInTree(_TreeWalkTestCase):
    """unfurl カードのタイトルは「深い位置にある、URL でないリンク」で見分ける。"""

    def test_deep_link_title_is_collected(self):
        # depth >= 5 に置いたタイトルリンク。カード内部に相当する。
        root = _nest(_Node(role=LINK, name="サンプル記事タイトル - Example News"), 6)
        self.assertEqual(
            self._titles(root), ["サンプル記事タイトル - Example News"]
        )

    def test_shallow_link_is_not_a_title(self):
        # depth < 5 のリンクは本文中のリンク。タイトルとして拾わない。
        root = _nest(_Node(role=LINK, name="本文中のリンク"), 2)
        self.assertEqual(self._titles(root), [])

    def test_deep_raw_url_is_not_a_title(self):
        root = _nest(_Node(role=LINK, name="https://news.example.com/articles/abc123"), 6)
        self.assertEqual(self._titles(root), [])

    def test_non_link_roles_are_ignored(self):
        root = _nest(_Node(role=SECTION, name="ただのテキスト"), 6)
        self.assertEqual(self._titles(root), [])

    def test_link_without_name_is_ignored(self):
        root = _nest(_Node(role=LINK, name=""), 6)
        self.assertEqual(self._titles(root), [])

    def test_known_non_title_links_are_filtered_out(self):
        # Slack が unfurl カードに付ける操作リンク。タイトルではない。
        card = _Node(children=[
            _Node(role=LINK, name="ページを表示"),
            _Node(role=LINK, name="Open in new window"),
            _Node(role=LINK, name="サンプル記事タイトル - Example News"),
        ])
        root = _nest(card, 6)
        self.assertEqual(
            self._titles(root), ["サンプル記事タイトル - Example News"]
        )

    def test_multiple_titles_keep_tree_order(self):
        card = _Node(children=[
            _Node(role=LINK, name="1つ目のタイトル"),
            _Node(role=LINK, name="2つ目のタイトル"),
        ])
        root = _nest(card, 6)
        self.assertEqual(self._titles(root), ["1つ目のタイトル", "2つ目のタイトル"])

    def test_leaf_node_yields_nothing(self):
        self.assertEqual(self._titles(_Node()), [])

    def test_walk_stops_at_max_depth(self):
        # 深さ上限を超えた先は見に行かない（無限ツリーで固まらないための保険）。
        root = _nest(_Node(role=LINK, name="上限より深いタイトル"), 14)
        self.assertEqual(self._titles(root), [])

    def test_broken_node_does_not_raise(self):
        # 走査中にノードが無効化されることがある（画面更新との競合）。
        class _Broken:
            role = SECTION
            name = ""

            @property
            def firstChild(self):
                raise RuntimeError("dead object")

        card = _Node(children=[_Broken()])
        root = _nest(card, 6)
        self.assertEqual(self._titles(root), [])


class TestAnnounceLinksAndMeta(unittest.TestCase):
    """タイトル取得後の読み上げ文と、点字ディスプレイ向けの本文差し替え。"""

    def setUp(self):
        self.am = AppModule()

    def _parsed(self, **overrides):
        parsed = {
            "lang": "ja",
            "unfurl_titles": [],
            "urls": [],
            "time": "",
            "reactions": "",
            "link_count": "",
            "replies": "",
            "attachments": "",
            "level": "",
        }
        parsed.update(overrides)
        return parsed

    def _announce(self, parsed, url_title_map=None, immediate_text="本文",
                  link_failure="host", focus=None):
        spoken = []
        speech_mock = MagicMock()
        speech_mock.speakMessage.side_effect = lambda text: spoken.append(text)
        api_mock = MagicMock()
        api_mock.getFocusObject.return_value = focus
        braille_mock = MagicMock()

        def _get(key):
            return {"link_failure_announce": link_failure}[key]

        with patch("slack.speech", speech_mock), \
             patch("slack.api", api_mock), \
             patch("slack.braille", braille_mock), \
             patch("shared.config.get_config", _get):
            self.am._announce_links_and_meta(
                parsed, url_title_map or {}, immediate_text
            )

        return types.SimpleNamespace(
            spoken=spoken, braille=braille_mock, focus=focus
        )

    def test_unfurl_title_is_announced(self):
        r = self._announce(
            self._parsed(unfurl_titles=["サンプル記事タイトル - Example News"])
        )
        self.assertEqual(len(r.spoken), 1)
        self.assertIn("Link: サンプル記事タイトル - Example News", r.spoken[0])

    def test_fetched_title_is_announced(self):
        url = "https://news.example.com/articles/abc123"
        r = self._announce(
            self._parsed(urls=[url]), {url: "サンプル記事タイトル"}
        )
        self.assertIn("Link: サンプル記事タイトル", r.spoken[0])

    def test_failed_fetch_falls_back_to_host(self):
        url = "https://news.example.com/articles/abc123"
        r = self._announce(
            self._parsed(urls=[url]), {url: None}, link_failure="host"
        )
        self.assertIn("news.example.com", r.spoken[0])

    def test_silent_mode_with_nothing_else_speaks_nothing(self):
        url = "https://news.example.com/articles/abc123"
        r = self._announce(
            self._parsed(urls=[url]), {url: None}, link_failure="silent"
        )
        self.assertEqual(r.spoken, [])

    def test_metadata_is_appended_in_fixed_order(self):
        parsed = self._parsed(
            unfurl_titles=["サンプル記事タイトル"],
            time="16:42",
            reactions="3 件のリアクション",
            link_count="1",
            replies="2 件の返信",
            attachments="1",
            level="2",
        )
        r = self._announce(parsed)
        text = r.spoken[0]

        order = [
            text.index("Link: サンプル記事タイトル"),
            text.index("16:42"),
            text.index("3 件のリアクション"),
            text.index("1 links"),
            text.index("2 件の返信"),
            text.index("1 attachments"),
            text.index("Level 2"),
        ]
        self.assertEqual(order, sorted(order))

    def test_japanese_uses_ideographic_sentence_separator(self):
        r = self._announce(
            self._parsed(unfurl_titles=["サンプル記事タイトル"], time="16:42")
        )
        self.assertIn("。", r.spoken[0])

    def test_english_uses_period_separator(self):
        r = self._announce(
            self._parsed(lang="en", unfurl_titles=["Sample Article Title"],
                         time="4:42 PM")
        )
        self.assertNotIn("。", r.spoken[0])
        self.assertIn(".", r.spoken[0])

    def test_nothing_to_add_speaks_nothing(self):
        r = self._announce(self._parsed())
        self.assertEqual(r.spoken, [])

    def test_focus_name_gets_immediate_text_plus_link_text(self):
        focus = MagicMock()
        r = self._announce(
            self._parsed(unfurl_titles=["サンプル記事タイトル"]),
            immediate_text="サンプル太郎。 コメント本文です",
            focus=focus,
        )
        self.assertIn("コメント本文です", focus.name)
        self.assertIn("Link: サンプル記事タイトル", focus.name)
        r.braille.handler.handleGainFocus.assert_called_once_with(focus)

    def test_link_text_stands_alone_when_nothing_was_spoken_first(self):
        focus = MagicMock()
        self._announce(
            self._parsed(unfurl_titles=["サンプル記事タイトル"]),
            immediate_text="",
            focus=focus,
        )
        self.assertEqual(focus.name, "Link: サンプル記事タイトル")

    def test_no_focus_object_does_not_break_speech(self):
        r = self._announce(
            self._parsed(unfurl_titles=["サンプル記事タイトル"]), focus=None
        )
        self.assertEqual(len(r.spoken), 1)
        self.assertFalse(r.braille.handler.handleGainFocus.called)

    def test_focus_update_failure_falls_back_to_braille_message(self):
        # フォーカスが既に移っている場合など。読み上げは済んでいるので、
        # 点字側は一時メッセージでの表示に切り替える。
        focus = MagicMock()
        type(focus).name = property(
            lambda self: "",
            lambda self, value: (_ for _ in ()).throw(RuntimeError("dead object")),
        )
        r = self._announce(
            self._parsed(unfurl_titles=["サンプル記事タイトル"]), focus=focus
        )
        self.assertEqual(len(r.spoken), 1)
        self.assertTrue(r.braille.handler.message.called)


if __name__ == "__main__":
    unittest.main()
