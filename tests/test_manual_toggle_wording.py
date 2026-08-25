# -*- coding: utf-8 -*-
"""The manual and the store listing must not present a default toggle key.

The add-on used to claim NVDA+V as the default gesture for its toggle. A
globalPlugin's gestures win over a tree interceptor's, so that binding took
browse mode's screen layout toggle away from NVDA everywhere, not only in Slack
and Teams. The binding is gone; every place that told a user to press it has to
go with it, in both languages, or the manual describes a key that does nothing.

These read the repository's own files rather than exercising a function, in the
same spirit as tests/test_release_consistency.py.
"""
import os
import sys
import tempfile
import unittest

REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON_DIR = os.path.join(REPO_DIR, "addon")

sys.path.insert(0, REPO_DIR)

import build_addon

GESTURE = "NVDA+V"

# Where a reader is told to assign the toggle instead. NVDA's dialog is called
# 入力ジェスチャ in Japanese and Input Gestures in English, and the toggle is
# listed there under the add-on's own category.
ASSIGNMENT_HINTS = {
    "README.md": ("入力ジェスチャ", "Message Sweeper"),
    "README.en.md": ("Input Gestures", "Message Sweeper"),
}


def _read(*parts):
    with open(os.path.join(REPO_DIR, *parts), encoding="utf-8") as f:
        return f.read()


def _manifest_paths():
    paths = [("addon/manifest.ini", os.path.join(ADDON_DIR, "manifest.ini"))]
    locale_dir = os.path.join(ADDON_DIR, "locale")
    for lang in sorted(os.listdir(locale_dir)):
        path = os.path.join(locale_dir, lang, "manifest.ini")
        if os.path.isfile(path):
            paths.append(("locale/%s/manifest.ini" % lang, path))
    return paths


def _addon_sources():
    for root, dirs, files in os.walk(ADDON_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


class TestNoDefaultGesture(unittest.TestCase):

    def test_no_gesture_is_registered_in_code(self):
        offenders = []
        for path in _addon_sources():
            with open(path, encoding="utf-8") as f:
                if GESTURE.lower() in f.read().lower():
                    offenders.append(os.path.relpath(path, REPO_DIR))
        self.assertEqual(
            [], offenders,
            "a default binding here is claimed globally, and a comment naming "
            "the old key outlives the fact")

    def test_manifest_descriptions_name_no_key(self):
        for label, path in _manifest_paths():
            with self.subTest(manifest=label):
                with open(path, encoding="utf-8") as f:
                    self.assertNotIn(
                        GESTURE.lower(), f.read().lower(),
                        "the Add-on Store shows this text verbatim, so it "
                        "would advertise a key that is not assigned")


class TestManuals(unittest.TestCase):
    """Both languages, always. One updated manual is a mistranslation."""

    def test_neither_manual_names_the_old_key(self):
        for name in ASSIGNMENT_HINTS:
            with self.subTest(manual=name):
                self.assertNotIn(GESTURE.lower(), _read(name).lower())

    def test_both_manuals_say_where_to_assign_the_toggle(self):
        for name, hints in ASSIGNMENT_HINTS.items():
            text = _read(name)
            for hint in hints:
                with self.subTest(manual=name, hint=hint):
                    self.assertIn(
                        hint, text,
                        "dropping the key without saying where to assign one "
                        "leaves the toggle unreachable")

    def test_generated_help_names_no_key(self):
        # The Add-on Store's help button opens the generated HTML, so that is
        # the copy a user actually reads.
        with tempfile.TemporaryDirectory() as out_dir:
            build_addon.generate_docs(addon_dir=out_dir)
            for src_name, lang in build_addon.DOC_SOURCES:
                path = os.path.join(out_dir, "doc", lang, "readme.html")
                with self.subTest(lang=lang, source=src_name):
                    with open(path, encoding="utf-8") as f:
                        self.assertNotIn(GESTURE.lower(), f.read().lower())


if __name__ == "__main__":
    unittest.main()
