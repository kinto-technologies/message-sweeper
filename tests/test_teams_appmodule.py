# -*- coding: utf-8 -*-
"""Acceptance tests for serving Teams from an appModule instead of a globalPlugin.

NVDA 2024.3 resolves a WebView2 process to the name of the app that hosts it
(nvaccess/nvda#16717), so Teams can be served by an ordinary appModule and no
longer needs a globalPlugin that inspects the foreground window's title. These
tests pin what that move has to hold true: where the Teams message code lives,
what the remaining globalPlugin is responsible for, and that the enable flag is
shared state rather than a class attribute owned by the Teams module.

Every fixture here is invented; none comes from a real message.
"""
import os
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import MagicMock, patch

REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON_DIR = os.path.join(REPO_DIR, "addon")

sys.path.insert(0, REPO_DIR)
sys.path.insert(0, ADDON_DIR)
sys.path.insert(0, os.path.join(ADDON_DIR, "appModules"))
sys.path.insert(0, os.path.join(ADDON_DIR, "globalPlugins"))

# NVDA's own modules are absent outside NVDA. Other test modules mock the same
# names, and pytest imports every test module before running any test, so the
# mocks are shared: fill in what is missing instead of replacing what is there,
# or the module imported last would strip attributes the others rely on.
for _mod_name in [
    "addonHandler", "appModuleHandler", "globalPluginHandler",
    "api", "braille", "nvwave", "tones",
    "speech", "ui", "controlTypes", "queueHandler", "logHandler",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = types.ModuleType(_mod_name)


def _ensure_attrs(owner, **defaults):
    for name, value in defaults.items():
        if not hasattr(owner, name):
            setattr(owner, name, value)


_lh = sys.modules["logHandler"]
if not hasattr(_lh, "log"):
    _lh.log = types.SimpleNamespace()
_ensure_attrs(
    _lh.log,
    info=lambda *a, **kw: None,
    warning=lambda *a, **kw: None,
    error=lambda *a, **kw: None,
    debug=lambda *a, **kw: None,
    debugWarning=lambda *a, **kw: None,
)

_ct = sys.modules["controlTypes"]
if not hasattr(_ct, "Role"):
    _ct.Role = types.SimpleNamespace()
_ensure_attrs(_ct.Role, **{
    name: name for name in (
        "LISTITEM", "LINK", "GRAPHIC", "BUTTON", "GROUP", "SECTION",
        "GROUPING", "STATICTEXT",
    )
})

_amh = sys.modules["appModuleHandler"]
_ensure_attrs(
    _amh,
    AppModule=type("AppModule", (), {}),
    registerExecutableWithAppModule=MagicMock(),
    unregisterExecutable=MagicMock(),
)

_gph = sys.modules["globalPluginHandler"]
_ensure_attrs(_gph, GlobalPlugin=type("GlobalPlugin", (), {}))
# NVDA's ScriptableObject provides bindGestures; the plugin calls it to bind the
# toggle, so the stand-in base class needs it to be constructible here.
_ensure_attrs(_gph.GlobalPlugin, bindGestures=lambda self, gestures: None)

_ensure_attrs(sys.modules["addonHandler"], initTranslation=lambda: None)
_ensure_attrs(
    sys.modules["addonHandler"],
    getCodeAddon=lambda: types.SimpleNamespace(path=REPO_DIR),
)
_ensure_attrs(sys.modules["tones"], beep=lambda *a, **kw: None)
_ensure_attrs(
    sys.modules["speech"],
    speakMessage=lambda *a, **kw: None,
    cancelSpeech=lambda *a, **kw: None,
)
_ensure_attrs(sys.modules["braille"], handler=MagicMock())
_ensure_attrs(
    sys.modules["api"],
    getFocusObject=lambda: None,
    getForegroundObject=lambda: None,
)
_ensure_attrs(
    sys.modules["queueHandler"],
    queueFunction=lambda queue, func, *a, **kw: func(*a, **kw),
    eventQueue=object(),
)

import builtins
if "_" not in dir(builtins):
    builtins._ = lambda x: x

import build_addon
import msTeams
import messageSweeper
import slack
from shared import state


# The add-on directory also holds compiled translations (.mo) and generated
# HTML after a build, so a scan that reads everything as UTF-8 fails on the
# binaries rather than on what it is looking for.
_TEXT_SUFFIXES = (".py", ".ini", ".po", ".html", ".md")


def _walk_addon_sources():
    for root, dirs, files in os.walk(ADDON_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(_TEXT_SUFFIXES):
                yield os.path.join(root, name)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestTeamsAppModule(unittest.TestCase):
    """The Teams message code lives in an appModule NVDA can bind to ms-teams."""

    def test_msteams_is_an_appmodule(self):
        # Compared by name, not by class identity: the slack test modules
        # reassign sys.modules["appModuleHandler"].AppModule when they are
        # imported, so the class this module inherited is no longer the one
        # that attribute holds by the time any test runs.
        bases = [cls.__name__ for cls in msTeams.AppModule.__mro__[1:]]
        self.assertIn(
            "AppModule", bases,
            "NVDA only treats a subclass of appModuleHandler.AppModule as an "
            "app module for a process")

    def test_msteams_owns_the_teams_parser(self):
        self.assertTrue(callable(msTeams.parse_teams_message))
        self.assertTrue(callable(msTeams.AppModule.event_gainFocus))

    def test_old_teams_globalplugin_is_gone(self):
        self.assertFalse(
            os.path.exists(os.path.join(
                ADDON_DIR, "globalPlugins", "teamsMessageSweeper.py")),
            "leaving the old file behind would load a second event_gainFocus "
            "handler for the same messages")

    def test_no_window_title_check_remains(self):
        offenders = [p for p in _walk_addon_sources()
                     if p.endswith(".py") and '"Microsoft Teams"' in _read(p)]
        self.assertEqual(
            [], offenders,
            "an appModule is only loaded into the Teams process, so matching "
            "the foreground window's title is dead weight that also breaks "
            "when Teams renames its window")

    def test_no_msedgewebview2_target_remains(self):
        offenders = [p for p in _walk_addon_sources()
                     if "msedgewebview2" in _read(p)]
        self.assertEqual(
            [], offenders,
            "targeting the WebView2 host itself loaded this add-on's code "
            "into every WebView2 app; ms-teams is the target now")


class TestSlackHasNoGlobalPluginDependency(unittest.TestCase):

    def test_slack_does_not_import_globalplugins(self):
        self.assertNotIn(
            "globalPlugins",
            _read(os.path.join(ADDON_DIR, "appModules", "slack.py")),
            "an appModule reaching into a globalPlugin's class attribute for "
            "the enable flag is why the flag lived in the Teams file")

    def test_enable_flag_lives_in_shared_state(self):
        self.assertTrue(callable(state.is_processing_enabled))
        self.assertTrue(callable(state.set_processing_enabled))
        self.assertTrue(callable(state.toggle_processing))


class TestGlobalPluginResponsibilities(unittest.TestCase):
    """What is left of the globalPlugin: the toggle, the panel, the binding."""

    def test_init_registers_ms_teams_with_the_appmodule(self):
        with patch.object(_amh, "registerExecutableWithAppModule") as reg:
            messageSweeper.GlobalPlugin()
        reg.assert_called_once_with("ms-teams", "msTeams")

    def test_terminate_unregisters_ms_teams(self):
        with patch.object(_amh, "registerExecutableWithAppModule"):
            plugin = messageSweeper.GlobalPlugin()
        with patch.object(_amh, "unregisterExecutable") as unreg:
            plugin.terminate()
        unreg.assert_called_once_with("ms-teams")

    def test_init_binds_no_gesture_by_default(self):
        # A globalPlugin's gestures are resolved before a tree interceptor's, so
        # any default this add-on claims is taken away from NVDA everywhere, not
        # only in Slack and Teams. NVDA+V used to shadow browse mode's screen
        # layout toggle that way.
        bound = []
        with patch.object(_amh, "registerExecutableWithAppModule"), \
                patch.object(_gph.GlobalPlugin, "bindGestures",
                             lambda self, gestures: bound.append(gestures)):
            messageSweeper.GlobalPlugin()
        self.assertEqual(
            [], [gestures for gestures in bound if gestures],
            "the add-on must claim no gesture until the user assigns one")

    def test_toggle_script_stays_discoverable_in_input_gestures(self):
        # Removing the default binding leaves the Input Gestures dialog as the
        # only way to reach the toggle, so the category and the description NVDA
        # lists it under are what make it findable at all.
        script = messageSweeper.GlobalPlugin.script_toggleProcessing
        self.assertEqual("Message Sweeper", script.category)
        self.assertTrue(script.__doc__ and script.__doc__.strip())

    def test_globalplugin_no_longer_parses_messages(self):
        source = _read(os.path.join(
            ADDON_DIR, "globalPlugins", "messageSweeper.py"))
        for gone in ("event_gainFocus", "parse_teams_message"):
            with self.subTest(symbol=gone):
                self.assertNotIn(
                    gone, source,
                    "message handling moved to appModules/msTeams.py; a copy "
                    "here would announce every message twice")


class TestSharedToggle(unittest.TestCase):
    """One flag gates both apps, and the toggle script is what flips it."""

    def setUp(self):
        state.set_processing_enabled(True)
        self.addCleanup(state.set_processing_enabled, True)

    @staticmethod
    def _teams_obj():
        return types.SimpleNamespace(
            role=_ct.Role.GROUPING,
            name="UserName1 テストメッセージです 2026年3月18日 10:29.",
        )

    @staticmethod
    def _slack_obj():
        return types.SimpleNamespace(
            role=_ct.Role.LISTITEM,
            name="山田太郎 テストメッセージです 10:29",
            positionInfo=None,
        )

    def test_teams_rewrites_the_announcement_while_enabled(self):
        obj = self._teams_obj()
        original = obj.name
        with patch.object(sys.modules["speech"], "speakMessage"), \
                patch.object(sys.modules["speech"], "cancelSpeech"):
            msTeams.AppModule().event_gainFocus(obj, MagicMock())
        self.assertNotEqual(
            original, obj.name,
            "with processing on, the Teams appModule is expected to replace "
            "the raw accessible name")

    def test_toggle_off_passes_teams_through_untouched(self):
        state.set_processing_enabled(False)
        obj = self._teams_obj()
        original = obj.name
        next_handler = MagicMock()
        msTeams.AppModule().event_gainFocus(obj, next_handler)
        next_handler.assert_called_once_with()
        self.assertEqual(original, obj.name)

    def test_toggle_off_passes_slack_through_untouched(self):
        state.set_processing_enabled(False)
        obj = self._slack_obj()
        original = obj.name
        next_handler = MagicMock()
        slack.AppModule().event_gainFocus(obj, next_handler)
        next_handler.assert_called_once_with()
        self.assertEqual(original, obj.name)

    def test_toggle_script_switches_both_apps_off_and_on(self):
        with patch.object(_amh, "registerExecutableWithAppModule"):
            plugin = messageSweeper.GlobalPlugin()
        with patch.object(sys.modules["tones"], "beep"), \
                patch.object(sys.modules["braille"], "handler", MagicMock()):
            plugin.script_toggleProcessing(None)
            self.assertFalse(state.is_processing_enabled())
            self.assertFalse(slack._is_sweeper_enabled())

            plugin.script_toggleProcessing(None)
            self.assertTrue(state.is_processing_enabled())
            self.assertTrue(slack._is_sweeper_enabled())


class TestPackagedAddon(unittest.TestCase):

    def test_build_packages_the_teams_appmodule(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with patch.object(build_addon, "OUTPUT_DIR", out_dir):
                package = build_addon.build()
            with zipfile.ZipFile(package) as zf:
                names = [n.replace("\\", "/") for n in zf.namelist()]
        self.assertIn(
            "appModules/msTeams.py", names,
            "NVDA loads app modules from the packaged appModules/ directory; "
            "a file that is not in the package does nothing")


if __name__ == "__main__":
    unittest.main()
