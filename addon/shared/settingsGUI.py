# -*- coding: utf-8 -*-
"""Settings panel for Message Sweeper in NVDA Preferences."""
import wx
import gui
from gui.settingsDialogs import SettingsPanel

from shared.config import (
    get_config, set_config,
    CONF_KEY_EMOJI_THRESHOLD, CONF_KEY_SUMMARY_POSITION,
    CONF_KEY_TOGGLE_SOUND, CONF_KEY_LINK_FAILURE_ANNOUNCE,
)

try:
    import addonHandler
    addonHandler.initTranslation()
except Exception:
    pass

SUMMARY_POSITIONS = [
    ("off", _("読み上げない")),
    ("before", _("メッセージの前")),
    ("after", _("メッセージの後")),
]

LINK_FAILURE_MODES = [
    ("silent", _("読み上げない")),
    ("label", _("「タイトル取得不可」とだけ読み上げる")),
    ("host", _("ホスト名とともに読み上げる")),
    ("url", _("URL をそのまま読み上げる")),
]


class MessageSweeperSettingsPanel(SettingsPanel):
    title = _("Message Sweeper")

    def makeSettings(self, settingsSizer):
        helper = gui.guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        self._threshold = helper.addLabeledControl(
            _("絵文字を省略する連続数のしきい値:"),
            wx.SpinCtrl, min=1, max=99,
        )
        self._threshold.SetValue(get_config(CONF_KEY_EMOJI_THRESHOLD))

        self._summary_position = helper.addLabeledControl(
            _("サマリーの読み上げ位置:"),
            wx.Choice,
            choices=[label for _, label in SUMMARY_POSITIONS],
        )
        current = get_config(CONF_KEY_SUMMARY_POSITION)
        for i, (value, _label) in enumerate(SUMMARY_POSITIONS):
            if value == current:
                self._summary_position.SetSelection(i)
                break

        self._link_failure_announce = helper.addLabeledControl(
            _("リンクのタイトル取得に失敗したときの読み上げ:"),
            wx.Choice,
            choices=[label for _, label in LINK_FAILURE_MODES],
        )
        current = get_config(CONF_KEY_LINK_FAILURE_ANNOUNCE)
        for i, (value, _label) in enumerate(LINK_FAILURE_MODES):
            if value == current:
                self._link_failure_announce.SetSelection(i)
                break

        self._toggle_sound = helper.addItem(
            wx.CheckBox(self, label=_("Message Sweeperの有効／無効の切り替えを音で通知する"))
        )
        self._toggle_sound.SetValue(get_config(CONF_KEY_TOGGLE_SOUND))

    def onSave(self):
        set_config(CONF_KEY_EMOJI_THRESHOLD, self._threshold.GetValue())
        idx = self._summary_position.GetSelection()
        if idx >= 0:
            set_config(CONF_KEY_SUMMARY_POSITION, SUMMARY_POSITIONS[idx][0])
        set_config(CONF_KEY_TOGGLE_SOUND, self._toggle_sound.GetValue())
        idx2 = self._link_failure_announce.GetSelection()
        if idx2 >= 0:
            set_config(CONF_KEY_LINK_FAILURE_ANNOUNCE, LINK_FAILURE_MODES[idx2][0])
