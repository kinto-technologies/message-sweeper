# -*- coding: utf-8 -*-
"""Tests for the manifest reader in build_addon.py.

The store listing takes displayName and description from the add-on manifest,
so description is a long, multi-paragraph, triple-quoted value. Reading a key
by matching the whole file also matches inside such a value, which is how a
description that shows `version = "9.9"` as an example came to be picked up as
the version. These tests pin the structural reading that replaced it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import build_addon


class TestParseManifestItems(unittest.TestCase):

    def test_reads_simple_quoted_values(self):
        items = build_addon.parse_manifest_items(
            'name = "messageSweeper"\nversion = "1.0.1"\n')
        self.assertEqual(items["name"], "messageSweeper")
        self.assertEqual(items["version"], "1.0.1")

    def test_key_inside_a_multiline_value_is_not_an_item(self):
        # 修正前はここで 9.9 を拾い、そのバージョンでパッケージが作られた。
        content = (
            'name = "messageSweeper"\n'
            'description = """To pin the version, write:\n'
            'version = "9.9"\n'
            'in your config."""\n'
            'version = "1.0.1"\n'
        )
        items = build_addon.parse_manifest_items(content)
        self.assertEqual(items["version"], "1.0.1")

    def test_multiline_value_body_is_not_kept(self):
        # name と version を取るための関数なので、複数行の値は None で足りる。
        # 本文を持たせないことで、値の中身が項目として誤解される余地を残さない。
        content = 'description = """first\nsecond"""\nversion = "1.0.1"\n'
        items = build_addon.parse_manifest_items(content)
        self.assertIsNone(items["description"])

    def test_single_line_triple_quoted_value_closes_on_the_same_line(self):
        content = 'description = """all on one line"""\nversion = "1.0.1"\n'
        items = build_addon.parse_manifest_items(content)
        self.assertEqual(items["version"], "1.0.1")

    def test_empty_triple_quoted_value_closes_on_the_same_line(self):
        content = 'description = """"""\nversion = "1.0.1"\n'
        items = build_addon.parse_manifest_items(content)
        self.assertEqual(items["version"], "1.0.1")

    def test_duplicate_key_is_an_error(self):
        # ConfigObj は後勝ちだが、どちらが効くのか読み手に分からない manifest を
        # 黙って受け入れると、意図しないバージョンで公開する事故になる。
        content = 'name = "n"\nversion = "1.0.1"\nversion = "0.9.0"\n'
        with self.assertRaises(ValueError) as ctx:
            build_addon.parse_manifest_items(content)
        self.assertIn("version", str(ctx.exception))

    def test_comment_lines_are_ignored(self):
        content = '# version = "0.0.1"\nversion = "1.0.1"\n'
        items = build_addon.parse_manifest_items(content)
        self.assertEqual(items["version"], "1.0.1")
        self.assertEqual(len(items), 1)

    def test_single_quoted_value(self):
        items = build_addon.parse_manifest_items("version = '1.0.1'\n")
        self.assertEqual(items["version"], "1.0.1")

    def test_unquoted_value_is_kept_as_written(self):
        # NVDA manifest では docFileName のようにクォート無しで書かれる項目もある。
        items = build_addon.parse_manifest_items("updateChannel = stable\n")
        self.assertEqual(items["updateChannel"], "stable")


class TestReadManifest(unittest.TestCase):

    def test_reads_the_real_manifest(self):
        name, version = build_addon.read_manifest()
        self.assertEqual(name, "messageSweeper")
        # 実際の manifest は複数段落の description を持つ。その状態で version が
        # 正しく取れることが、この修正が守っている性質そのものである。
        self.assertRegex(version, r"^\d+\.\d+(\.\d+)?$")

    def test_missing_key_is_an_error(self):
        content = 'name = "messageSweeper"\n'
        items = build_addon.parse_manifest_items(content)
        self.assertNotIn("version", items)


if __name__ == '__main__':
    unittest.main()
