# -*- coding: utf-8 -*-
# NVDA Global Plugin for Message Sweeper
#
# The message handling for Slack and Teams lives in appModules/slack.py and
# appModules/msTeams.py. What is left here is what belongs to neither app:
#
#   - the toggle that turns rewriting on and off for both apps at once
#   - registering and removing the settings panel in NVDA's Settings dialog
#   - binding the ms-teams executable to appModules/msTeams.py
#
# The last one needs a globalPlugin. appModuleHandler derives a module name
# from the executable's own name, and ms-teams contains a hyphen, which no
# Python module name can. registerExecutableWithAppModule() is the documented
# way to state the binding instead, and something loaded at start-up has to
# make that call.

import os
import sys

# Add addon root to sys.path so shared modules can be imported
_addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _addon_root not in sys.path:
    sys.path.insert(0, _addon_root)

import addonHandler
import appModuleHandler
import globalPluginHandler
import braille
import tones
import speech
from logHandler import log

try:
    import gui
except Exception:
    gui = None

from shared.state import toggle_processing

# The new Teams reports this executable name; NVDA 2024.3 and later resolve it
# through the WebView2 host lookup (nvaccess/nvda#16717).
TEAMS_EXECUTABLE = "ms-teams"
TEAMS_APP_MODULE = "msTeams"

# --- i18n ---
try:
    addonHandler.initTranslation()
    log.info("messageSweeper: initTranslation() succeeded")
except Exception:
    log.warning("messageSweeper: initTranslation() failed", exc_info=True)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    # No gesture is bound by default, on purpose. A globalPlugin's gestures are
    # resolved before a tree interceptor's, so a default claimed here is taken
    # away from NVDA in every application, not only in Slack and Teams -- which
    # is how the add-on's own toggle came to shadow browse mode's screen layout
    # command. The script's category puts it in NVDA's Input Gestures dialog for
    # anyone who wants a key for it.

    def __init__(self):
        super().__init__()
        try:
            from shared.config import register_config
            register_config()
        except Exception:
            pass
        try:
            from shared.settingsGUI import MessageSweeperSettingsPanel
            gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(
                MessageSweeperSettingsPanel
            )
        except Exception:
            pass
        try:
            appModuleHandler.registerExecutableWithAppModule(
                TEAMS_EXECUTABLE, TEAMS_APP_MODULE
            )
        except Exception:
            # Without this binding Teams keeps NVDA's own announcement. Say so
            # in the log; a silent pass would look like a Teams-side change.
            log.error(
                "messageSweeper: could not bind %s to the %s app module"
                % (TEAMS_EXECUTABLE, TEAMS_APP_MODULE),
                exc_info=True,
            )

    def terminate(self):
        try:
            from shared.settingsGUI import MessageSweeperSettingsPanel
            gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(
                MessageSweeperSettingsPanel
            )
        except Exception:
            pass
        try:
            appModuleHandler.unregisterExecutable(TEAMS_EXECUTABLE)
        except Exception:
            log.error(
                "messageSweeper: could not remove the binding for %s"
                % TEAMS_EXECUTABLE,
                exc_info=True,
            )

    def script_toggleProcessing(self, gesture):
        enabled = toggle_processing()
        msg = _("Message Sweeper enabled") if enabled else _("Message Sweeper disabled")

        try:
            from shared.config import get_config, CONF_KEY_TOGGLE_SOUND
            use_sound = get_config(CONF_KEY_TOGGLE_SOUND)
        except Exception:
            use_sound = True

        if use_sound:
            tones.beep(880 if enabled else 440, 80)
        else:
            speech.speakMessage(msg)

        braille.handler.message(msg)

    script_toggleProcessing.__doc__ = _("Toggle Message Sweeper module")
    script_toggleProcessing.category = _("Message Sweeper")
