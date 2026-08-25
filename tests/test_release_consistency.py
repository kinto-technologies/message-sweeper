# -*- coding: utf-8 -*-
"""Consistency checks across the files that describe a release.

Unlike the other test modules, these do not exercise a function against
fixtures. They read the repository's own files and assert that the several
places which describe the same release agree with each other: the manifest,
the translated manifest, the CHANGELOG, and the translation example in
CONTRIBUTING.md.

They exist because that agreement has already broken twice in one release.
The 1.0.1 CHANGELOG entry described a manifest reader that had been replaced
during review, and CONTRIBUTING.md kept showing the 1.0.0 summary after the
manifest had been rewritten. Neither is caught by a unit test of any single
function, and neither is visible in a diff of the file that changed -- only in
the file that did not. A reviewer found both. These checks are here so that a
reviewer does not have to.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import build_addon

REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ADDON_DIR = os.path.join(REPO_DIR, 'addon')

# NVDA reads only these two keys from locale/<lang>/manifest.ini. Anything else
# written there is silently ignored, which makes it worse than absent: a reader
# sees a value that never takes effect.
TRANSLATABLE_KEYS = {'summary', 'description'}

_CHANGELOG_HEADING = re.compile(r'^## \[([^\]]+)\]')
_MANIFEST_DESCRIPTION = re.compile(r'^description\s*=\s*(.*)$')
_VERSION = re.compile(r'^\d+\.\d+\.\d+$')
_UNRELEASED = re.compile(r'^unreleased$', re.IGNORECASE)


def _read(*parts):
    with open(os.path.join(REPO_DIR, *parts), encoding='utf-8') as f:
        return f.read()


def _manifest_items(*parts):
    return build_addon.parse_manifest_items(_read(*parts))


def _locale_manifest_paths():
    locale_dir = os.path.join(ADDON_DIR, 'locale')
    found = []
    for lang in sorted(os.listdir(locale_dir)):
        path = os.path.join(locale_dir, lang, 'manifest.ini')
        if os.path.isfile(path):
            found.append((lang, path))
    return found


def _description_body(text):
    """The text of a manifest's description, whatever form it is written in.

    build_addon.parse_manifest_items deliberately discards the body of a
    triple-quoted value -- it exists to read name and version, both single-line
    scalars, and dropping bodies is what keeps a `version = "9.9"` line inside
    description from being read as the version. So an empty description is
    invisible to it, and this reads the body separately. An empty description is
    worth catching: it is the blank store listing the whole 1.0.1 rewrite was
    about.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _MANIFEST_DESCRIPTION.match(line)
        if not match:
            continue
        raw = match.group(1).strip()
        for quote in ('"""', "'''"):
            if raw.startswith(quote):
                rest = raw[len(quote):]
                if rest.endswith(quote) and len(rest) >= len(quote):
                    return rest[:-len(quote)]
                body = [rest]
                for follow in lines[i + 1:]:
                    if quote in follow:
                        body.append(follow.split(quote)[0])
                        break
                    body.append(follow)
                return '\n'.join(body)
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in '"\'':
            return raw[1:-1]
        return raw
    return None


def _changelog_headings():
    """Every heading label in CHANGELOG.md, newest first (file order)."""
    labels = []
    for line in _read('CHANGELOG.md').splitlines():
        m = _CHANGELOG_HEADING.match(line)
        if m:
            labels.append(m.group(1))
    return labels


def _changelog_versions():
    """The released version headings, newest first.

    An `## [Unreleased]` heading is skipped rather than treated as a version.
    Keep a Changelog puts work there before a version number is decided, and
    the manifest still carries the last released version at that point, so
    comparing the manifest against a heading called Unreleased would fail on a
    perfectly correct file.
    """
    return [label for label in _changelog_headings()
            if not _UNRELEASED.match(label)]


class TestVersion(unittest.TestCase):

    def test_manifest_version_is_three_numbers(self):
        version = _manifest_items('addon', 'manifest.ini')['version']
        self.assertRegex(
            version, _VERSION,
            'the add-on version is what the Add-on Store shows and what an '
            'update check compares; it has to be a plain x.y.z')

    def test_newest_changelog_entry_is_the_manifest_version(self):
        version = _manifest_items('addon', 'manifest.ini')['version']
        versions = _changelog_versions()
        self.assertTrue(versions, 'CHANGELOG.md has no version heading')
        self.assertEqual(
            versions[0], version,
            'the newest CHANGELOG entry is %r but the manifest says %r. '
            'Whichever is wrong, a release tagged now would ship notes that '
            'do not belong to the package.' % (versions[0], version))

    def test_changelog_versions_are_unique(self):
        versions = _changelog_versions()
        duplicates = sorted({v for v in versions if versions.count(v) > 1})
        self.assertEqual(
            [], duplicates,
            'CHANGELOG.md describes these versions more than once: %s'
            % ', '.join(duplicates))

    def test_changelog_headings_are_versions_or_unreleased(self):
        for label in _changelog_headings():
            with self.subTest(heading=label):
                self.assertTrue(
                    _VERSION.match(label) or _UNRELEASED.match(label),
                    '%r is neither a x.y.z version nor Unreleased. A heading '
                    'this file does not recognise is a heading the release '
                    'checks silently skip.' % label)

    def test_newest_released_changelog_entry_has_a_body(self):
        lines = _read('CHANGELOG.md').splitlines()
        start = next(i for i, line in enumerate(lines)
                     if _CHANGELOG_HEADING.match(line)
                     and _VERSION.match(_CHANGELOG_HEADING.match(line).group(1)))
        body = []
        for line in lines[start + 1:]:
            if _CHANGELOG_HEADING.match(line):
                break
            body.append(line)
        self.assertTrue(
            ''.join(body).strip(),
            'the newest released CHANGELOG entry (%s) has a heading and '
            'nothing under it' % _changelog_versions()[0])


class TestManifests(unittest.TestCase):

    def test_addon_manifest_has_no_duplicate_keys(self):
        # parse_manifest_items raises on a duplicate; calling it is the check.
        _manifest_items('addon', 'manifest.ini')

    def test_locale_manifests_have_no_duplicate_keys(self):
        for lang, path in _locale_manifest_paths():
            with self.subTest(lang=lang):
                with open(path, encoding='utf-8') as f:
                    build_addon.parse_manifest_items(f.read())

    def test_locale_manifests_define_summary_and_description(self):
        for lang, path in _locale_manifest_paths():
            with self.subTest(lang=lang):
                with open(path, encoding='utf-8') as f:
                    items = build_addon.parse_manifest_items(f.read())
                for key in sorted(TRANSLATABLE_KEYS):
                    self.assertIn(
                        key, items,
                        'locale/%s/manifest.ini has no %s, so a %s user sees '
                        'the English text in the store listing'
                        % (lang, key, lang))
                self.assertTrue(
                    items['summary'].strip(),
                    'locale/%s/manifest.ini has an empty summary' % lang)

    def test_every_manifest_description_has_a_body(self):
        targets = [('addon/manifest.ini',
                    os.path.join(ADDON_DIR, 'manifest.ini'))]
        targets += [('locale/%s/manifest.ini' % lang, path)
                    for lang, path in _locale_manifest_paths()]
        for label, path in targets:
            with self.subTest(manifest=label):
                with open(path, encoding='utf-8') as f:
                    body = _description_body(f.read())
                self.assertTrue(
                    body and body.strip(),
                    '%s has no description text. The Add-on Store shows this '
                    'value verbatim, so the listing would be blank.' % label)

    def test_locale_manifests_declare_only_translatable_keys(self):
        for lang, path in _locale_manifest_paths():
            with self.subTest(lang=lang):
                with open(path, encoding='utf-8') as f:
                    items = build_addon.parse_manifest_items(f.read())
                extra = sorted(set(items) - TRANSLATABLE_KEYS)
                self.assertEqual(
                    [], extra,
                    'locale/%s/manifest.ini declares %s. NVDA reads only %s '
                    'from a locale manifest, so these have no effect and '
                    'mislead whoever reads the file next.'
                    % (lang, ', '.join(extra), ', '.join(sorted(TRANSLATABLE_KEYS))))

    def test_locale_summary_is_not_the_english_one(self):
        english = _manifest_items('addon', 'manifest.ini')['summary']
        for lang, path in _locale_manifest_paths():
            with self.subTest(lang=lang):
                with open(path, encoding='utf-8') as f:
                    items = build_addon.parse_manifest_items(f.read())
                self.assertNotEqual(
                    english, items['summary'],
                    'locale/%s/manifest.ini repeats the English summary '
                    'verbatim, which means the translation was not updated '
                    'when the English one was' % lang)


class TestDocumentation(unittest.TestCase):

    def test_manifest_declares_the_generated_doc_file(self):
        items = _manifest_items('addon', 'manifest.ini')
        self.assertEqual(
            'readme.html', items.get('docFileName'),
            "docFileName is what makes the Add-on Store's help button work; "
            'without it NVDA has nothing to open')

    def test_every_doc_source_exists(self):
        for src_name, lang in build_addon.DOC_SOURCES:
            with self.subTest(lang=lang):
                self.assertTrue(
                    os.path.isfile(os.path.join(REPO_DIR, src_name)),
                    'the build generates doc/%s/readme.html from %s, which is '
                    'missing' % (lang, src_name))

    def test_contributing_shows_the_current_summary(self):
        summary = _manifest_items('addon', 'manifest.ini')['summary']
        expected = 'summary = "%s"' % summary
        lines = [line.strip() for line in _read('CONTRIBUTING.md').splitlines()]
        self.assertIn(
            expected, lines,
            'the translation example in CONTRIBUTING.md does not show the '
            'current manifest summary. A translator starting from the guide '
            'would translate prose the add-on no longer contains.')


if __name__ == '__main__':
    unittest.main()
