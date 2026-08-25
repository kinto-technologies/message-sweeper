# addon/shared/state.py
# -*- coding: utf-8 -*-
"""Whether Message Sweeper rewrites announcements, shared by every module.

The flag used to be a class attribute of the Teams globalPlugin, so the Slack
appModule had to import that plugin to read it. Slack then depended on a Teams
file for something that belongs to neither app. It lives here instead: the
globalPlugin flips it, and both appModules read it.

This is deliberately not an NVDA configuration value. The toggle is meant to
last for the session, the way NVDA's own speech-mode toggle does, and not to
survive a restart.
"""

_processing_enabled = True


def is_processing_enabled():
    """True while focus announcements should be rewritten."""
    return _processing_enabled


def set_processing_enabled(enabled):
    """Turn rewriting on or off."""
    global _processing_enabled
    _processing_enabled = bool(enabled)


def toggle_processing():
    """Flip the flag and return the value it now has."""
    set_processing_enabled(not _processing_enabled)
    return _processing_enabled
