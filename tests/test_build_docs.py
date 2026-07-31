# -*- coding: utf-8 -*-
"""Tests for the Markdown -> HTML documentation generator in build_addon.py."""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import build_addon


class TestMarkdownToHtml(unittest.TestCase):

    def test_heading_levels(self):
        html_text = build_addon.markdown_to_html("# Title\n\n## Section\n\n### Sub\n", "ja")
        self.assertIn("<h1>Title</h1>", html_text)
        self.assertIn("<h2>Section</h2>", html_text)
        self.assertIn("<h3>Sub</h3>", html_text)

    def test_paragraph(self):
        html_text = build_addon.markdown_to_html("# T\n\n本文です。\n", "ja")
        self.assertIn("<p>本文です。</p>", html_text)

    def test_bullet_list(self):
        html_text = build_addon.markdown_to_html("# T\n\n- one\n- two\n", "ja")
        self.assertIn("<ul>\n<li>one</li>\n<li>two</li>\n</ul>", html_text)

    def test_ordered_list(self):
        html_text = build_addon.markdown_to_html("# T\n\n1. first\n2. second\n", "ja")
        self.assertIn("<ol>\n<li>first</li>\n<li>second</li>\n</ol>", html_text)

    def test_blank_line_closes_list(self):
        html_text = build_addon.markdown_to_html("# T\n\n- one\n\nafter\n", "ja")
        self.assertIn("</ul>", html_text)
        self.assertLess(html_text.index("</ul>"), html_text.index("<p>after</p>"))

    def test_inline_code(self):
        html_text = build_addon.markdown_to_html("# T\n\n`NVDA+V` を押す\n", "ja")
        self.assertIn("<code>NVDA+V</code>", html_text)

    def test_link(self):
        html_text = build_addon.markdown_to_html("# T\n\n[LICENSE](https://example.com/L)\n", "ja")
        self.assertIn('<a href="https://example.com/L">LICENSE</a>', html_text)

    def test_html_is_escaped(self):
        html_text = build_addon.markdown_to_html("# T\n\na <script> & b\n", "ja")
        self.assertIn("&lt;script&gt;", html_text)
        self.assertIn("&amp;", html_text)
        self.assertNotIn("<script>", html_text)

    def test_lang_attribute(self):
        self.assertIn('<html lang="ja">', build_addon.markdown_to_html("# T\n", "ja"))
        self.assertIn('<html lang="en">', build_addon.markdown_to_html("# T\n", "en"))

    def test_title_comes_from_h1(self):
        html_text = build_addon.markdown_to_html("# Message Sweeper\n", "ja")
        self.assertIn("<title>Message Sweeper</title>", html_text)

    def test_charset_and_doctype(self):
        html_text = build_addon.markdown_to_html("# T\n", "ja")
        self.assertTrue(html_text.startswith("<!DOCTYPE html>"))
        self.assertIn('<meta charset="utf-8">', html_text)


class TestUnsupportedMarkdownStopsTheBuild(unittest.TestCase):

    def _assert_rejected(self, md_text):
        with self.assertRaises(ValueError):
            build_addon.markdown_to_html(md_text, "ja")

    def test_bold_is_rejected(self):
        self._assert_rejected("# T\n\n**bold**\n")

    def test_table_is_rejected(self):
        self._assert_rejected("# T\n\n| a | b |\n")

    def test_nested_list_is_rejected(self):
        self._assert_rejected("# T\n\n- one\n  - nested\n")

    def test_heading_deeper_than_h3_is_rejected(self):
        self._assert_rejected("# T\n\n#### too deep\n")

    def test_horizontal_rule_is_rejected(self):
        self._assert_rejected("# T\n\n---\n")

    def test_horizontal_rule_with_trailing_whitespace_is_rejected(self):
        self._assert_rejected("# T\n\n--- \n")

    def test_missing_h1_is_rejected(self):
        self._assert_rejected("## no h1 here\n")

    def test_fenced_code_block_is_rejected(self):
        self._assert_rejected("# T\n\n```\ncode here\n```\n")

    def test_tilde_fenced_code_block_is_rejected(self):
        self._assert_rejected("# T\n\n~~~\ncode here\n~~~\n")

    def test_asterisk_bullet_is_rejected(self):
        self._assert_rejected("# T\n\n* one\n")

    def test_plus_bullet_is_rejected(self):
        self._assert_rejected("# T\n\n+ one\n")

    def test_blockquote_is_rejected(self):
        self._assert_rejected("# T\n\n> quoted\n")

    def test_bare_blockquote_marker_is_rejected(self):
        self._assert_rejected("# T\n\n>\n")

    def test_underscore_emphasis_is_rejected(self):
        self._assert_rejected("# T\n\n_italic_\n")

    def test_underscore_rule_is_rejected(self):
        self._assert_rejected("# T\n\n___\n")

    def test_underscore_rule_with_trailing_whitespace_is_rejected(self):
        self._assert_rejected("# T\n\n___ \n")

    def test_malformed_heading_is_rejected(self):
        self._assert_rejected("# T\n\n#nospace\n")

    def test_image_is_rejected(self):
        self._assert_rejected("# T\n\n![alt](https://example.com/x.png)\n")

    def test_reference_style_link_is_rejected(self):
        self._assert_rejected("# T\n\n[a][b]\n")

    def test_hard_wrapped_paragraph_is_rejected(self):
        self._assert_rejected("# T\n\nfirst line\nsecond line\n")

    def test_link_only_paragraph_is_accepted(self):
        # README.md / README.en.md 冒頭は「[English version](...)」だけの行。
        # 段落の先頭が `[` であることは正当なので、これを壊してはならない。
        html_text = build_addon.markdown_to_html(
            "# T\n\n[English version](https://example.com/en)\n", "ja"
        )
        self.assertIn('<a href="https://example.com/en">English version</a>', html_text)


class TestRealReadmesConvert(unittest.TestCase):
    """実物の README が変換器を通ることを守る回帰テスト。

    README に未対応記法を書いてしまった場合、ここで落ちる。
    """

    def test_every_doc_source_converts(self):
        repo_root = os.path.join(os.path.dirname(__file__), '..')
        for src_name, lang in build_addon.DOC_SOURCES:
            path = os.path.join(repo_root, src_name)
            self.assertTrue(os.path.isfile(path), f"{src_name} is missing")
            with open(path, encoding='utf-8') as f:
                md_text = f.read()
            html_text = build_addon.markdown_to_html(md_text, lang)
            self.assertIn(f'<html lang="{lang}">', html_text)
            self.assertIn("<h1>", html_text)
            self.assertIn("</body>", html_text)

    def test_supported_environment_is_current(self):
        repo_root = os.path.join(os.path.dirname(__file__), '..')
        with open(os.path.join(repo_root, 'README.md'), encoding='utf-8') as f:
            ja = f.read()
        self.assertIn("4.51.180", ja)
        self.assertNotIn("4.48.95", ja)
        self.assertNotIn("Beta13", ja)
        # インストール手順が「最新版をダウンロード」であることを直接固定する。
        # バージョン名を埋め込んだ配布ファイル名（例: messageSweeper-1.1.0.nvda-addon）
        # に戻ると、旧文字列の非存在チェックだけでは検出できない。
        self.assertIn("releases/latest", ja)
        with open(os.path.join(repo_root, 'README.en.md'), encoding='utf-8') as f:
            en = f.read()
        self.assertIn("4.51.180", en)
        self.assertNotIn("4.48.95", en)
        self.assertIn("releases/latest", en)


class TestGenerateDocs(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = os.path.join(self.tmp, 'repo')
        self.addon = os.path.join(self.tmp, 'addon')
        os.makedirs(self.repo)
        os.makedirs(self.addon)
        for name, body in (
            ('README.md', "# 日本語タイトル\n\n本文です。\n"),
            ('README.en.md', "# English Title\n\nBody text.\n"),
        ):
            with open(os.path.join(self.repo, name), 'w', encoding='utf-8') as f:
                f.write(body)

    def test_writes_one_html_per_language(self):
        build_addon.generate_docs(repo_dir=self.repo, addon_dir=self.addon)
        ja = os.path.join(self.addon, 'doc', 'ja', 'readme.html')
        en = os.path.join(self.addon, 'doc', 'en', 'readme.html')
        self.assertTrue(os.path.isfile(ja))
        self.assertTrue(os.path.isfile(en))
        with open(ja, encoding='utf-8') as f:
            ja_text = f.read()
        self.assertIn('<html lang="ja">', ja_text)
        self.assertIn('<title>日本語タイトル</title>', ja_text)
        with open(en, encoding='utf-8') as f:
            self.assertIn('<html lang="en">', f.read())

    def test_creates_missing_output_directories(self):
        # doc/ が存在しない状態から呼んでも失敗しないこと
        self.assertFalse(os.path.exists(os.path.join(self.addon, 'doc')))
        build_addon.generate_docs(repo_dir=self.repo, addon_dir=self.addon)
        self.assertTrue(os.path.isdir(os.path.join(self.addon, 'doc', 'ja')))


class TestManifestDeclaresDocFile(unittest.TestCase):

    def test_doc_file_name_is_declared(self):
        repo_root = os.path.join(os.path.dirname(__file__), '..')
        with open(os.path.join(repo_root, 'addon', 'manifest.ini'), encoding='utf-8') as f:
            manifest = f.read()
        # docFileName が無いと NVDA の getDocFilePath() が None を返し、
        # アドオンストアの「アドオンのヘルプ」から説明書に到達できない。
        self.assertIn('docFileName = "readme.html"', manifest)


class TestBuildPackagesGeneratedDocs(unittest.TestCase):
    """build() が生成済み HTML を確実に同梱し、古い .md を混入させないことを守る。

    build() 自体には自動テストが無く、doc/<lang>/readme.html をパッケージへ
    入れ忘れても誰も気付けなかった。ここでは本物の build() を、モジュール
    定数 ADDON_DIR / OUTPUT_DIR だけ一時ディレクトリへ差し替えて実行し、
    出来上がった zip の namelist を検査する。README.md / README.en.md は
    リポジトリ本物を読ませる（generate_docs() の repo_dir はデフォルトの
    まま）。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addon_dir = os.path.join(self.tmp, 'addon')
        self.output_dir = os.path.join(self.tmp, 'output')
        os.makedirs(self.addon_dir)
        os.makedirs(self.output_dir)
        with open(os.path.join(self.addon_dir, 'manifest.ini'), 'w', encoding='utf-8') as f:
            f.write('name = "testAddon"\nversion = "9.9.9"\n')
        # 誰かのディスクに残った古い手書き .md が、生成済み HTML と一緒に
        # パッケージへ混入しないかを確かめるための「仕込み」。
        for lang in ('ja', 'en'):
            stale_dir = os.path.join(self.addon_dir, 'doc', lang)
            os.makedirs(stale_dir)
            with open(os.path.join(stale_dir, 'readme.md'), 'w', encoding='utf-8') as f:
                f.write('stale handwritten manual, should never ship\n')

    def test_zip_contains_generated_html_and_excludes_stale_markdown(self):
        with mock.patch.object(build_addon, 'ADDON_DIR', self.addon_dir), \
                mock.patch.object(build_addon, 'OUTPUT_DIR', self.output_dir):
            output_file = build_addon.build()
        self.addCleanup(lambda: os.path.exists(output_file) and os.remove(output_file))
        with zipfile.ZipFile(output_file) as zf:
            names = zf.namelist()
        self.assertIn('doc/ja/readme.html', names)
        self.assertIn('doc/en/readme.html', names)
        self.assertNotIn('doc/ja/readme.md', names)
        self.assertNotIn('doc/en/readme.md', names)


if __name__ == '__main__':
    unittest.main()
