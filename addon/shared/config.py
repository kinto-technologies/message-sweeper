# addon/shared/config.py
# -*- coding: utf-8 -*-
"""Centralized settings for Message Sweeper addon."""
import config

CONF_SECTION = "messageSweeper"
CONF_KEY_EMOJI_THRESHOLD = "emoji_threshold"
CONF_KEY_SUMMARY_POSITION = "summary_position"
CONF_KEY_TOGGLE_SOUND = "toggle_sound"
CONF_KEY_LINK_FAILURE_ANNOUNCE = "link_failure_announce"

DEFAULTS = {
    CONF_KEY_EMOJI_THRESHOLD: 3,
    CONF_KEY_SUMMARY_POSITION: "after",
    CONF_KEY_TOGGLE_SOUND: True,
    CONF_KEY_LINK_FAILURE_ANNOUNCE: "host",
}

_SPEC = {
    CONF_KEY_EMOJI_THRESHOLD: "integer(default=3, min=1, max=99)",
    CONF_KEY_SUMMARY_POSITION: 'option("off", "before", "after", default="after")',
    CONF_KEY_TOGGLE_SOUND: "boolean(default=True)",
    CONF_KEY_LINK_FAILURE_ANNOUNCE: 'option("silent", "label", "host", "url", default="host")',
}


def register_config():
    """Register the addon's config spec with NVDA. Call once at addon load."""
    config.conf.spec[CONF_SECTION] = _SPEC


def get_config(key):
    """Read a setting value. Returns the default if not set."""
    try:
        return config.conf[CONF_SECTION][key]
    except KeyError:
        return DEFAULTS.get(key)


def set_config(key, value):
    """Write a setting value."""
    if CONF_SECTION not in config.conf:
        config.conf[CONF_SECTION] = {}
    config.conf[CONF_SECTION][key] = value
