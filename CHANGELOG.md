# Changelog

All notable changes to Message Sweeper are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
