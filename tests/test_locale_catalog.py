# -*- coding: utf-8 -*-
"""Every translatable string in the add-on must exist in every catalog.

Like test_release_consistency, these checks read the repository's own files
rather than exercising a function. They compare the strings the source wraps
in ``_()`` against the msgids in each ``addon/locale/<lang>/LC_MESSAGES/nvda.po``.

They exist because a missing msgid fails silently and invisibly. The source
strings of this add-on are Japanese, so gettext falls back to the Japanese
msgid when the English catalog has no entry for it -- an English-speaking
screen reader user hears Japanese read out by an English voice, and nothing in
a diff, a build, or a unit test says so. That is how four strings of the
settings panel ("Summary announcement position:" and its three choices)
shipped untranslated: they were added to the panel without being added to
en.po, and the only way to notice was to open the panel with NVDA running in
English.

An empty msgstr is checked too. It falls back to the msgid exactly like an
absent entry does, so a catalog with a blank translation leaks the same way.

The opposite direction is checked as well: a catalog must not carry an entry
that no source string asks for. Two such entries had been sitting in both
catalogs since the commit that deleted the code using them, and the only cost
of an entry like that is paid by whoever translates the add-on next -- they
render a phrase into their language, see it in the catalog, and never hear it.
"""
import os
import re
import unittest

REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ADDON_DIR = os.path.join(REPO_DIR, 'addon')
LOCALE_DIR = os.path.join(ADDON_DIR, 'locale')

# Strings that are deliberately absent from the catalogs.
#
# format_emoji_summary() picks between these two by the language of the
# *message* being read, not by the language of NVDA's interface, so each one is
# already in its target language at the point it is chosen. Translating them
# would change which language a mixed case speaks in (a Japanese message under
# an English interface, say) and that is a product decision, not a translation
# gap.
#
# Do not add a string here to make this test pass. A string belongs here only
# when translating it would be wrong, and the reason has to be written down.
EXEMPT = {
    'メッセージの絵文字: ',
    'Emoji in message: ',
}

_STRING = r'''("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')'''
_GETTEXT_CALL = re.compile(r'_\(\s*' + _STRING + r'\s*\)')
_PO_ENTRY = re.compile(r'^(msgid|msgstr)\s+"((?:[^"\\]|\\.)*)"\s*$')
_PO_CONTINUATION = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*$')


def _unescape(text):
    return text.replace('\\n', '\n').replace('\\t', '\t') \
               .replace('\\"', '"').replace('\\\\', '\\')


def _source_files():
    found = []
    for dirpath, dirnames, filenames in os.walk(ADDON_DIR):
        dirnames[:] = [d for d in dirnames if d not in ('locale', '__pycache__')]
        for name in sorted(filenames):
            if name.endswith('.py'):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def _translatable_strings():
    """Map each ``_("...")`` literal to the source locations that use it."""
    found = {}
    for path in _source_files():
        with open(path, encoding='utf-8') as f:
            text = f.read()
        for match in _GETTEXT_CALL.finditer(text):
            literal = _unescape(match.group(1)[1:-1])
            line = text.count('\n', 0, match.start()) + 1
            where = '%s:%d' % (os.path.relpath(path, REPO_DIR).replace(os.sep, '/'), line)
            found.setdefault(literal, []).append(where)
    return found


def _catalog_paths():
    found = []
    for lang in sorted(os.listdir(LOCALE_DIR)):
        path = os.path.join(LOCALE_DIR, lang, 'LC_MESSAGES', 'nvda.po')
        if os.path.isfile(path):
            found.append((lang, path))
    return found


def _parse_catalog(path):
    """Read a .po file into {msgid: msgstr}, joining continuation lines."""
    entries = {}
    current_key = None
    parts = {'msgid': [], 'msgstr': []}

    def flush():
        if parts['msgid']:
            entries[_unescape(''.join(parts['msgid']))] = _unescape(''.join(parts['msgstr']))

    with open(path, encoding='utf-8') as f:
        for raw in f:
            line = raw.rstrip('\n')
            entry = _PO_ENTRY.match(line)
            if entry:
                keyword, value = entry.group(1), entry.group(2)
                if keyword == 'msgid':
                    flush()
                    parts = {'msgid': [], 'msgstr': []}
                current_key = keyword
                parts[current_key].append(value)
                continue
            continuation = _PO_CONTINUATION.match(line)
            if continuation and current_key:
                parts[current_key].append(continuation.group(1))
                continue
            if not line.strip():
                current_key = None
    flush()
    entries.pop('', None)
    return entries


class TestLocaleCatalogCoverage(unittest.TestCase):
    def setUp(self):
        self.strings = _translatable_strings()
        self.catalogs = _catalog_paths()

    def test_catalogs_are_present(self):
        self.assertTrue(self.catalogs, 'no nvda.po found under addon/locale')

    def test_translatable_strings_were_found(self):
        # Guards the regex itself: a scanner that silently matches nothing
        # would make every other check in this module pass vacuously.
        self.assertGreater(len(self.strings), 10)

    def test_every_string_has_a_msgid_in_every_catalog(self):
        missing = []
        for lang, path in self.catalogs:
            entries = _parse_catalog(path)
            for literal, locations in sorted(self.strings.items()):
                if literal in EXEMPT or literal in entries:
                    continue
                missing.append('%s: %r used at %s' % (lang, literal, ', '.join(locations)))
        self.assertEqual([], missing, 'strings with no msgid:\n' + '\n'.join(missing))

    def test_no_catalog_entry_is_unused(self):
        # The add-on translates its interface strings through _() only. The
        # manifest's summary and description are translated in
        # locale/<lang>/manifest.ini instead, so nothing legitimately lives in
        # a catalog without appearing in the source.
        unused = []
        for lang, path in self.catalogs:
            for msgid in sorted(_parse_catalog(path)):
                if msgid not in self.strings:
                    unused.append('%s: %r' % (lang, msgid))
        self.assertEqual(
            [], unused,
            'catalog entries no source string asks for:\n' + '\n'.join(unused))

    def test_no_translation_is_empty(self):
        empty = []
        for lang, path in self.catalogs:
            for msgid, msgstr in sorted(_parse_catalog(path).items()):
                if not msgstr.strip():
                    empty.append('%s: %r' % (lang, msgid))
        self.assertEqual([], empty, 'empty msgstr falls back to the msgid:\n' + '\n'.join(empty))

    def test_exempt_strings_are_still_in_the_source(self):
        # An exemption that outlives the string it excused becomes a hole
        # nobody is watching.
        stale = sorted(s for s in EXEMPT if s not in self.strings)
        self.assertEqual([], stale, 'EXEMPT lists strings no longer in the source: %r' % (stale,))


if __name__ == '__main__':
    unittest.main()
