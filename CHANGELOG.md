# Changelog

All notable changes to Message Sweeper are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] — 2026-09-07

### Changed

- The manual now sends you to NVDA's Add-on Store first. Installing from the
  store lets NVDA verify the integrity of the file it downloads, which a manual
  download cannot do. Downloading the `.nvda-addon` file from the Releases page
  is kept as the fallback, since in-house distribution and handing over a
  development build still need it. The uninstall steps no longer name the
  Add-on Manager: NVDA replaced it with the Add-on Store in 2023.2, so the name
  does not exist in any NVDA version this add-on supports.

### Fixed

- Two kinds of emoji label are no longer half-read. Slack collapses a run of
  three or more identical emoji into one label that carries the count, as in
  `13 青い丸 絵文字`. That count is now the weight of the run, so the label is
  removed once and summarized as 13 emoji, where before the count was read as
  one emoji and the body kept the fragment `13 青い`. A label of three or more
  Japanese characters (`紙吹雪`) or three or more English words
  (`flag of Japan`) is now matched whole as well; only its tail used to match,
  which left the first character or word in the body and named the summary
  after the remainder.
- Emoji labels are recognized again where Slack runs them straight onto the
  message text. Slack has begun naming emoji in English (`large blue circle`,
  `tada`) and leaves no space between the body and the label, as in
  `今日はtada 絵文字sparkles 絵文字です`. The fix above had required a label to
  start at the beginning of the text, after whitespace, or after another label,
  so a label in that shape was not recognized at all and decoration that 1.1.0
  removed was read out in full. Where a label may start is now decided by the
  switch in character class instead: an English label may start after any
  non-ASCII character, a katakana label after any non-katakana character.
  Between a Japanese character and the closing `絵文字` nothing but the label
  can appear, so a name of any length is taken there, which is what gets the
  count on `13 large blue circle 絵文字` as well. Where the text in front of a
  label is ASCII too, nothing marks where the name begins, so at most two
  words are taken there, as before.
- The emoji summary no longer reads the removed run back out. Teams leaves
  emoji in the message text as the characters themselves, and a run of them was
  summarized under one name made of the whole run and counted as a single
  emoji, so a message decorated with thirteen identical emoji had them removed
  from the body and then spoken again in full by the summary, followed by the
  count 1. Every emoji in a run is now counted on its own: that message is
  summarized as one emoji with the count 13, and a run of different emoji names
  each of them once. A sequence joined by a zero-width joiner, or a character
  followed by a variation selector, counts as the one emoji it displays as. The
  name in the summary is the emoji character itself, which NVDA's own symbol
  dictionary reads out, so no table of emoji names ships with the add-on.
  Slack's collapsed labels (`13 青い丸 絵文字`) already carried their count and
  are unchanged.
- A Japanese Teams message sent today is no longer taken for English. Teams
  writes the time of such a message as `今日の 16:25`, where an older message
  carries the full date (`2026年9月7日 16:25.`). Only the full date counted as
  a marker of a Japanese message, so a message sent today had its emoji summary
  spoken in English after a Japanese body, and the `送信済み` label Teams
  appends to your own messages stayed in the text. What the English interface
  writes in that position has not been measured, so the English side is
  unchanged.
- Four strings in the settings panel are now translated into English. The
  summary position setting and its three choices had no entry in the English
  catalog, so NVDA fell back to the Japanese source string and an English
  interface showed, and read out, Japanese. A new check
  (`tests/test_locale_catalog.py`) compares every string the add-on marks for
  translation against every locale catalog, and also fails on a translation
  left empty, because an empty one falls back to the source string in the same
  silent way.
- Both catalogs no longer carry two entries that nothing asks for. The strings
  that announced an X post (`X post: {text}` and `{author}'s X post: {text}`)
  outlived the code that used them; X posts have been announced in the same
  form as any other link since the oEmbed path was reinstated. The check above
  now also fails on a catalog entry with no matching source string, so a
  translator is not asked to render a phrase the add-on will never speak.

## [1.1.0] — 2026-08-25

### Changed

- The toggle that turns processing on and off no longer claims a default key.
  It used to be bound to NVDA+V, which NVDA itself uses in browse mode to
  switch screen layout. A global plugin's gestures are resolved before a browse
  mode document's, so installing this add-on took that command away from NVDA
  everywhere, not only in Slack and Teams. That was a defect, not a choice.
  To get the toggle back on a key, open NVDA's menu, choose Preferences and
  then Input Gestures, find the toggle under the Message Sweeper category, and
  assign whatever key you like. Nothing else changes if you do not: message
  processing is on by default, as before.
- Microsoft Teams is now served by an app module (`addon/appModules/msTeams.py`)
  instead of a global plugin. NVDA 2024.3 resolves a WebView2 process to the
  name of the application hosting it (nvaccess/nvda#16717, proposed in
  nvaccess/nvda#16705), and the new Teams reports `ms-teams`, so the add-on no
  longer has to load its Teams code into every WebView2 app and then decide,
  from the foreground window's title, whether the window is Teams. Because
  `ms-teams` contains a hyphen and cannot be a Python module name, the global
  plugin states the binding with
  `appModuleHandler.registerExecutableWithAppModule()` and removes it on
  `terminate()`. What Teams messages sound like is unchanged.
- The global plugin was renamed to `addon/globalPlugins/messageSweeper.py` and
  now keeps only what belongs to neither app: the toggle, the settings panel,
  and the Teams binding.
- The enable flag moved to `addon/shared/state.py`. It used to be a class
  attribute of the Teams global plugin, which the Slack app module imported to
  read, so Slack depended on a Teams file for a setting that is neither app's.
  Both app modules and the toggle now read the same module.
- Teams support no longer targets the WebView2 runtime process itself. Any
  other WebView2 application that this add-on happened to affect is now left
  alone, which is the intended narrowing.

## [1.0.1] — 2026-08-21

Add-on Store listing metadata, with build and documentation fixes. No change
in the add-on's behaviour.

### Changed

- The manifest `summary` and `description` were rewritten for the Add-on Store
  listing: what the add-on does, how it differs from lowering NVDA's symbol
  level, the toggle gesture, and where the settings live. The wording now names
  NVDA rather than "screen readers", because the add-on is specific to NVDA.
- The Japanese translated manifest (`addon/locale/ja/manifest.ini`) was
  rewritten to match, so the store listing and the add-on's own entry read the
  same way in Japanese. It also names NVDA instead of "screen readers".
- `build_addon.py` no longer reads the manifest with `configparser`, which
  requires continuation lines to be indented and therefore fails on a
  triple-quoted multi-line value. It now reads the manifest line by line and
  skips the body of a triple-quoted value, so a line such as `version = "9.9"`
  written inside `description` as a configuration example is no longer taken
  as the add-on's version. Before this change it was, and the package was
  built under that version.
- A manifest that declares the same key twice now fails the build. ConfigObj
  takes the last value, but a manifest whose effective version a reader cannot
  determine is not worth packaging.
- The translation example in `CONTRIBUTING.md` still showed the 1.0.0 `summary`
  and `description`. It now shows the current wording, and the triple-quoted
  multi-paragraph form the value actually uses, so a translator starting from
  the guide neither translates prose that no longer exists nor collapses the
  paragraphs into one line.

## [1.0.0] — 2026-08-12

First public release.

### Added

- Structured announcement of Slack Desktop and Microsoft Teams messages:
  sender, body, links, time, reactions and reply count, in a fixed order.
- URLs in a message body are replaced with the fetched page title (`<title>`
  or `og:title`), including an oEmbed path for services that do not expose a
  usable title in their HTML.
- The body of X (formerly Twitter) posts is read instead of the raw URL. The
  text is taken from the accessibility tree without any network request; when
  the client has not rendered the unfurl card, the add-on falls back to the
  public oEmbed endpoint.
- Removal of emoji, colon-style emoji names, fullwidth decorations and long
  ASCII rules, with a spoken summary of how many emoji were skipped. Removal
  triggers on a **consecutive run** of emoji rather than the total number in a
  message, so emoji that carry information — a weekly schedule marked with one
  emoji per day, for example — are kept.
- `NVDA+V` to toggle processing on and off, with a choice of tone or speech for
  the notification.
- Settings panel in NVDA Preferences: the emoji run-length threshold, the
  position of the emoji summary, the notification style, and what to announce
  when a page title cannot be fetched — say nothing, the link label, the host
  name, or the full URL. The default is the host name.
- Processed text is sent to the braille display as well as to speech.
- Japanese and English message formats are detected automatically, and the
  add-on interface is localized for both.

### Security

- Title fetching refuses any host that resolves to a loopback, private,
  link-local, reserved, multicast or CGNAT (`100.64.0.0/10`) address, and a
  redirect whose target fails the same check is aborted rather than followed.
  A crafted link in a message therefore cannot make the add-on reach an
  internal host.
- Title fetching sends a generic User-Agent that does not reveal an
  assistive-technology context.
