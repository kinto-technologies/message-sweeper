# Message Sweeper — NVDA Add-on

[日本語版 (Japanese)](https://github.com/kinto-technologies/message-sweeper/blob/main/README.md)

An NVDA add-on that makes Slack Desktop and Microsoft Teams messages easier to read with a screen reader.

When you focus a message, the following processing happens automatically:

- Reads page titles fetched from URLs in the message instead of raw addresses
- Removes excessive emoji and decorative symbols so the message body stays clear
- Reads sender, body, links, time, reactions in a clean, organized order
- Sends the processed text to a connected braille display


## Supported Environment

- NVDA 2025.1 or later (as of August 2026, verified on the Japanese distribution of NVDA 2025.3.3 and 2026.1)
- Windows 11
- Slack Desktop (as of August 2026, verified on 4.51.180)
- Microsoft Teams desktop app (new Teams)


## Installation

1. Download the latest `.nvda-addon` file from the [Releases page](https://github.com/kinto-technologies/message-sweeper/releases/latest)
2. Double-click the downloaded file (or press Enter on it)
3. Choose "Yes" in NVDA's installation confirmation dialog
4. NVDA restarts and the add-on is enabled


## Uninstallation

1. Open NVDA menu → Tools → Add-on Manager
2. Select "Message Sweeper" from the list
3. Press the "Remove" button
4. Restart NVDA


## How to Use

No special action is required. When you focus a message in Slack or Teams, the processing applies automatically.

### Keyboard Shortcut

- NVDA+V: Toggle the add-on on or off (sound feedback)

If you want to temporarily disable the add-on and return to Slack or Teams' default reading, press NVDA+V. Press it again to re-enable.

### Reading Order

When you focus a message, the components are read in this order:

1. Sender name
2. Message body (with emoji and decoration cleaned)
3. Link titles (page titles instead of raw URLs)
4. Time
5. Reaction counts and reply counts

Fetching link titles requires an internet connection. While titles are being fetched, the message body is read first, and titles are appended once they arrive.


## Features

### URL Title Reading

The add-on detects URLs in the message, fetches their page titles, and reads them aloud.

- Reads "Link: article title" instead of the raw URL
- Once a title is fetched, it is cached, so re-focusing a message with the same URL is instant
- Titles can be picked up from Slack's preview cards (unfurled links) even for services that require authentication, such as Confluence
- YouTube video titles are also supported

### X (Twitter) Post Preview

When a message contains an X (formerly Twitter) post URL, the add-on reads the tweet body instead of the raw URL. On Slack, the body is extracted from the preview card shown in the message view. On Teams, it is fetched via X's oEmbed API.

### Emoji and Decoration Cleanup

The add-on strips unnecessary symbols from decoration-heavy messages so the body is easier to listen to.

Removed:
- Runs of consecutive emoji (default: 3 or more in a row; the threshold is configurable from 1 to 99 via NVDA Settings → "Message Sweeper" → "Consecutive-emoji count to skip")
- Colon-style emoji (`:emoji_name:` format)
- Full-width decorative symbols (rules, geometric shapes, ornaments)
- Long ASCII decorations (5 or more repeated symbols, such as `=====`)

Kept:
- Channel mentions (#channel) and user mentions (@name)
- `---` separator lines
- Runs shorter than the threshold (by default, up to 2 consecutive emoji — typical greetings with a few emoji remain audible)

### Automatic Japanese / English Detection

The add-on automatically detects the message language (Japanese / English) for both Slack and Teams, and applies the matching parsing patterns. The speech language follows NVDA's own language setting.


## Settings

Open NVDA menu → Preferences → Settings and select the "Message Sweeper" category to change these.

### Consecutive-emoji Count to Skip

- Default: 3
- Range: 1 to 99
- Removes emoji when this many (or more) consecutive emoji appear. Lower values remove emoji more aggressively.

### Summary Position

- Default: After the message
- Choices: Do not announce / Before the message / After the message
- Controls where the summary of skipped emoji (e.g. "Skipped: sparkles 3, thumbs up 2") is read.

### Title Fetch Failure Announcement

- Default: Announce with hostname
- Choices: Do not announce / Announce "Title unavailable" only / Announce with hostname / Announce the URL itself
- Controls how the add-on announces a URL whose title could not be fetched (private IPs, network errors, non-HTML responses, etc.).

### Notify Enable/Disable Toggle with Sound

- Default: On
- Controls how state changes are announced when you press NVDA+V. When on, a tone plays. When off, the state is spoken.


## Known Limitations

Please be aware of the following:

- Fetching link titles requires an internet connection. URLs whose title cannot be fetched are, by default, announced with the host name — for example "Link: example.com (Title unavailable)". The behavior is configurable via NVDA Settings → "Message Sweeper" → "Title fetch failure announcement" (do not announce / "Title unavailable" only / with hostname / the URL itself).
- URLs pointing to private IP addresses (e.g. internal networks) are not fetched, for security reasons; they are announced using the setting above.
- Internal-only services (such as pages requiring a VPN) may be unreachable from the add-on, in which case the title cannot be fetched.
- Teams support is newer than Slack support and may still have rough edges.


## Feedback

If you notice anything while using the add-on, please let us know:

- Spots where the speech sounds unnatural
- Cases that did not work as expected
- Ideas for improvement

Contact: message-sweeper@kinto-technologies.com


## License

This add-on is released under the GNU General Public License v2.0 (GPLv2), matching the license of NVDA itself.

- Full license: see the [LICENSE](https://github.com/kinto-technologies/message-sweeper/blob/main/LICENSE) file in the repository
- Source code: https://github.com/kinto-technologies/message-sweeper

This software is provided as-is, without warranty of any kind, express or implied. See the "NO WARRANTY" section of the LICENSE file for details.

This add-on is independent third-party software and is not affiliated with Slack Technologies, LLC or Microsoft Corporation. Slack and Microsoft Teams are trademarks of their respective owners.

Copyright (C) 2026 KINTO Technologies Corporation
