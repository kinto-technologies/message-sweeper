# Contributing to Message Sweeper

Thank you for your interest in contributing! The most valuable contributions are **bug reports**, **feature ideas**, and **translations** — the more languages this add-on supports, the more screen reader users around the world can benefit.

## How contributions work

Message Sweeper is maintained by KINTO Technologies Corporation. To keep maintenance sustainable for a small team, **we accept contributions through GitHub Issues, not pull requests.** Please do not open a pull request — open an Issue instead and a maintainer will take it from there.

- Found a bug? Open a [Bug report](https://github.com/kinto-technologies/message-sweeper/issues/new/choose).
- Have a feature idea? Open a [Feature request](https://github.com/kinto-technologies/message-sweeper/issues/new/choose).
- Want to add or fix a translation? Open a [Translation](https://github.com/kinto-technologies/message-sweeper/issues/new/choose) issue — see below.

English or Japanese is fine for any issue. 日本語でも英語でも大丈夫です。

## Translating

Translations are especially welcome.

### What needs translating

Two files per language:

- `addon/locale/<lang>/LC_MESSAGES/nvda.po` — spoken strings (link labels, toggle messages, etc.)
- `addon/locale/<lang>/manifest.ini` — add-on name and description shown in the NVDA Add-on Manager

### How to prepare a translation

1. Copy the English locale as a starting point:
   - `addon/locale/en/LC_MESSAGES/nvda.po` → your `nvda.po`
   - `addon/locale/ja/manifest.ini` → your `manifest.ini`

   Use the standard IETF language tag for `<lang>` (e.g. `fr`, `de`, `zh_CN`, `pt_BR`).

2. Edit `nvda.po` — translate each `msgstr` line and leave `msgid` lines untouched:

   ```po
   msgid "Message Sweeper enabled"
   msgstr "Message Sweeper activé"   ← your translation here
   ```

   Set the `Language:` header near the top of the file to your language tag:

   ```po
   "Language: fr\n"
   ```

3. Edit `manifest.ini` — translate `summary` and `description`:

   ```ini
   summary = "Message Sweeper - Slack & Teams messages for screen readers"
   description = "Replaces URLs with page titles, removes emoji clutter ..."
   ```

### How to submit a translation

Open a **Translation** issue and either:

- drag-and-drop your finished `nvda.po` (and `manifest.ini`) into the issue, or
- paste their contents into the issue body.

A maintainer will review the files and commit them to the add-on. Let us know in the issue how you would like to be credited.

### Tips

- Use [Poedit](https://poedit.net/) for a comfortable translation UI.
- Keep format placeholders like `{title}`, `{author}`, `{url}` exactly as-is — they are filled in at runtime.
- If a string makes no sense in your language without context, mention it in your issue and ask.

## Reporting bugs

Open a **Bug report** issue and include:

- NVDA version
- Add-on version
- Slack / Teams version
- A description of what happened vs. what you expected

GitHub is a public forum — please remove any secrets or personal information from logs before attaching them (see our [Code of Conduct](CODE_OF_CONDUCT.md)).

## Running the tests (optional)

If you have forked the project and want to verify behaviour locally:

```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 py -X utf8 -m pytest tests/ -x --tb=short
```

The tests are pure Python and do not require NVDA to be installed.

## Code of Conduct

By participating in this project you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). For questions or concerns, email <message-sweeper@kinto-technologies.com>.
