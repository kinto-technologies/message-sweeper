# -*- coding: utf-8 -*-
"""Build .nvda-addon package from addon/ directory."""
import html
import os
import re
import struct
import zipfile

ADDON_DIR = os.path.join(os.path.dirname(__file__), "addon")
OUTPUT_DIR = os.path.dirname(__file__)


_MANIFEST_ITEM = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
_TRIPLE_QUOTES = ('"""', "'''")


def parse_manifest_items(content):
    """manifest.ini の最上位の項目を key -> value の dict で返す。

    NVDA manifest.ini は ConfigObj 形式で、description のような長い値は三重
    クォートの複数行で書ける（NVDA 公式テンプレートの manifest.ini.tpl も
    `description = \"\"\"...\"\"\"` を出力する）。configparser は継続行がインデント
    されていることを要求するため、この形を渡すと ParsingError で落ちる。壊れる
    のは NVDA 本体ではなくこのビルドスクリプトだけなので、ここで読む。

    ファイル全体に正規表現をかける方式は採らない。複数行の値の中身にも一致して
    しまうため、description に

        version = "9.9"

    のような行が（設定例として）入っていれば、その 9.9 でパッケージが作られる。
    実測で再発を確認した誤りである。ここでは行を順に見て、三重クォートの値の
    中身は閉じるまで読み飛ばす。

    同じキーが2回現れた場合はエラーにする。ConfigObj は後勝ちだが、どちらが
    効くのか読み手に分からない manifest を黙って受け入れる理由はない。

    複数行の値は本文を保持せず None を入れる。この関数の用途は name と version
    の取得であり、どちらも1行のスカラーだからである。
    """
    items = {}
    closing = None  # 閉じ待ちの三重クォート
    for line in content.splitlines():
        if closing is not None:
            if closing in line:
                closing = None
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _MANIFEST_ITEM.match(line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2).strip()
        value = raw
        for quote in _TRIPLE_QUOTES:
            if raw.startswith(quote):
                rest = raw[len(quote):]
                if not (rest.endswith(quote) and len(rest) >= len(quote)):
                    closing = quote  # 値は次の行以降に続く
                value = None
                break
        else:
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                value = raw[1:-1]
        if key in items:
            raise ValueError(
                "manifest.ini に %s が複数あります。どちらが使われるか"
                "曖昧なので中断します。" % key
            )
        items[key] = value
    return items


def read_manifest():
    """manifest.ini から name と version を取り出す。"""
    path = os.path.join(ADDON_DIR, "manifest.ini")
    with open(path, encoding="utf-8") as f:
        items = parse_manifest_items(f.read())

    def _value(key):
        value = items.get(key)
        if not value:
            raise ValueError("manifest.ini に %s が見つかりません" % key)
        return value

    return _value("name"), _value("version")


def _compile_po_to_mo(po_path, mo_path):
    """Minimal .po -> .mo compiler (subset of msgfmt)."""
    messages = {}
    msgid = msgstr = None
    reading = None

    def _unescape(s):
        """Unescape .po string escape sequences."""
        return s.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")

    def _store(msgid, msgstr):
        if msgid is not None and msgstr is not None:
            messages[_unescape(msgid)] = _unescape(msgstr)

    with open(po_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("msgid "):
                _store(msgid, msgstr)
                msgid = line[6:].strip('"')
                reading = "id"
            elif line.startswith("msgstr "):
                msgstr = line[7:].strip('"')
                reading = "str"
            elif line.startswith('"') and reading:
                val = line.strip('"')
                if reading == "id":
                    msgid += val
                else:
                    msgstr += val
            else:
                _store(msgid, msgstr)
                msgid = msgstr = None
                reading = None
        _store(msgid, msgstr)

    # Ensure metadata entry exists (gettext needs it for charset detection)
    if "" not in messages:
        messages[""] = "Content-Type: text/plain; charset=UTF-8\n"

    # Write .mo file (GNU gettext format)
    keys = sorted(messages.keys())
    offsets = []
    ids = b""
    strs = b""
    for key in keys:
        id_bytes = key.encode("utf-8")
        str_bytes = messages[key].encode("utf-8")
        offsets.append((len(ids), len(id_bytes), len(strs), len(str_bytes)))
        ids += id_bytes + b"\0"
        strs += str_bytes + b"\0"

    n = len(keys)
    keystart = 7 * 4
    valuestart = keystart + n * 8
    koffsets = []
    voffsets = []
    ids_start = valuestart + n * 8
    strs_start = ids_start + len(ids)
    for id_off, id_len, str_off, str_len in offsets:
        koffsets.append((id_len, ids_start + id_off))
        voffsets.append((str_len, strs_start + str_off))

    output = struct.pack(
        "Iiiiiii",
        0x950412de,  # magic
        0,           # revision
        n,           # number of strings
        keystart,    # offset of table with original strings
        valuestart,  # offset of table with translation strings
        0, 0         # size/offset of hashing table
    )
    for length, offset in koffsets:
        output += struct.pack("ii", length, offset)
    for length, offset in voffsets:
        output += struct.pack("ii", length, offset)
    output += ids + strs

    with open(mo_path, "wb") as f:
        f.write(output)


def compile_locales():
    """Compile all .po files to .mo in addon/locale/."""
    locale_dir = os.path.join(ADDON_DIR, "locale")
    if not os.path.isdir(locale_dir):
        return
    for lang in os.listdir(locale_dir):
        po_path = os.path.join(locale_dir, lang, "LC_MESSAGES", "nvda.po")
        mo_path = os.path.join(locale_dir, lang, "LC_MESSAGES", "nvda.mo")
        if os.path.isfile(po_path):
            _compile_po_to_mo(po_path, mo_path)
            print(f"Compiled: {po_path} -> {mo_path}")


# --- ドキュメント生成（Markdown -> HTML） --------------------------------
# NVDA はアドオンの説明書を doc/<lang>/<docFileName> から開く（manifest の
# docFileName が未設定だと getDocFilePath() が None を返し到達できない）。
# 慣例の形式は HTML なので、README を単一ソースとして HTML を生成する。

DOC_SOURCES = (
    ("README.md", "ja"),
    ("README.en.md", "en"),
)

_HEADING = re.compile(r"^(#+)\s+(.*)$")
_BULLET = re.compile(r"^-\s+(.*)$")
_ORDERED = re.compile(r"^\d+\.\s+(.*)$")
_NESTED_ITEM = re.compile(r"^\s+(?:[-*]|\d+\.)\s")
_HRULE = re.compile(r"^-{3,}\s*$")
_FENCE = re.compile(r"^(```|~~~)")
_ALT_BULLET = re.compile(r"^[*+]\s")
_BLOCKQUOTE = re.compile(r"^>(\s|$)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

_DOC_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title}</title>
</head>
<body>
{body}
</body>
</html>
"""


def _reject_unsupported(lines):
    """未対応の記法を見つけたらビルドを止める。

    黙って欠落した HTML を配布するより、ビルドが失敗するほうが安全。
    README に新しい記法を書いたら、まずここに対応を足す。

    段落に落ちる分岐はホワイトリストの裏返し: 見出し・リスト項目のいずれ
    でもない行は、ここで「対応済みの記法ではない」と判定できない限り
    段落として素通りしてしまう。フェンスコード・別記法の箇条書き・
    引用・アンダースコア強調／区切り線・画像・参照リンク・見出し崩れ・
    ハードラップされた段落（空行を挟まない連続段落行）を個別に拒否する
    ことで、「変換できないものは大きな音で失敗する」契約を保つ。
    """
    prev_was_paragraph = False
    for no, line in enumerate(lines, 1):
        if not line.strip():
            prev_was_paragraph = False
            continue
        if _HRULE.match(line):
            raise ValueError(f"line {no}: horizontal rule is not supported: {line!r}")
        if _NESTED_ITEM.match(line):
            raise ValueError(f"line {no}: nested list is not supported: {line!r}")
        if "**" in line:
            raise ValueError(f"line {no}: bold (**) is not supported: {line!r}")
        if "|" in line:
            raise ValueError(f"line {no}: table is not supported: {line!r}")
        if _FENCE.match(line):
            raise ValueError(f"line {no}: fenced code block is not supported: {line!r}")
        if _ALT_BULLET.match(line):
            raise ValueError(f"line {no}: bullet syntax other than '- ' is not supported: {line!r}")
        if _BLOCKQUOTE.match(line):
            raise ValueError(f"line {no}: blockquote is not supported: {line!r}")
        if line.startswith("_"):
            raise ValueError(f"line {no}: underscore emphasis or rule is not supported: {line!r}")
        if "![" in line:
            raise ValueError(f"line {no}: image is not supported: {line!r}")
        if "][" in line:
            raise ValueError(f"line {no}: reference-style link is not supported: {line!r}")

        m = _HEADING.match(line)
        if m:
            if len(m.group(1)) > 3:
                raise ValueError(f"line {no}: heading deeper than h3 is not supported: {line!r}")
            prev_was_paragraph = False
            continue
        if line.startswith("#"):
            raise ValueError(f"line {no}: malformed heading (missing space after '#') is not supported: {line!r}")

        if _BULLET.match(line) or _ORDERED.match(line):
            prev_was_paragraph = False
            continue

        # 段落候補。直前も段落行なら、空行を挟まないハードラップ段落。
        if prev_was_paragraph:
            raise ValueError(
                f"line {no}: hard-wrapped paragraph (no blank line before this line) is not supported: {line!r}"
            )
        prev_was_paragraph = True


def _inline(text):
    """インライン記法を変換する。エスケープを先に行う（[ ] ( ) ` は不変）。"""
    out = html.escape(text)
    out = _INLINE_CODE.sub(lambda m: "<code>" + m.group(1) + "</code>", out)
    out = _LINK.sub(lambda m: '<a href="' + m.group(2) + '">' + m.group(1) + "</a>", out)
    return out


def markdown_to_html(md_text, lang):
    """README の Markdown を完全な HTML 文書に変換する。

    段落は 1 行 1 つの <p>。両 README に複数行にまたがる段落は無く、
    日本語の行を空白で連結する事故も避けられる。
    """
    lines = md_text.splitlines()
    _reject_unsupported(lines)

    body = []
    title = None
    open_list = None

    def close_list():
        nonlocal open_list
        if open_list:
            body.append("</%s>" % open_list)
            open_list = None

    def start_list(tag):
        nonlocal open_list
        if open_list != tag:
            close_list()
            body.append("<%s>" % tag)
            open_list = tag

    for line in lines:
        if not line.strip():
            close_list()
            continue
        m = _HEADING.match(line)
        if m:
            close_list()
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1 and title is None:
                title = text
            body.append("<h%d>%s</h%d>" % (level, _inline(text), level))
            continue
        m = _BULLET.match(line)
        if m:
            start_list("ul")
            body.append("<li>%s</li>" % _inline(m.group(1)))
            continue
        m = _ORDERED.match(line)
        if m:
            start_list("ol")
            body.append("<li>%s</li>" % _inline(m.group(1)))
            continue
        close_list()
        body.append("<p>%s</p>" % _inline(line.strip()))
    close_list()

    if title is None:
        raise ValueError("no h1 heading found; cannot build <title>")

    return _DOC_TEMPLATE.format(lang=lang, title=html.escape(title), body="\n".join(body))


def generate_docs(repo_dir=None, addon_dir=None):
    """README から addon/doc/<lang>/readme.html を生成する。"""
    repo_dir = repo_dir or os.path.dirname(os.path.abspath(__file__))
    addon_dir = addon_dir or ADDON_DIR
    for src_name, lang in DOC_SOURCES:
        src_path = os.path.join(repo_dir, src_name)
        with open(src_path, encoding="utf-8") as f:
            html_text = markdown_to_html(f.read(), lang)
        out_dir = os.path.join(addon_dir, "doc", lang)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "readme.html")
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(html_text)
        print(f"Generated: {src_name} -> {out_path}")


def build():
    generate_docs()
    compile_locales()
    name, version = read_manifest()
    output_file = os.path.join(OUTPUT_DIR, f"{name}-{version}.nvda-addon")
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ADDON_DIR):
            # Skip __pycache__
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for file in files:
                if file.endswith((".pyc", ".pyo")):
                    continue
                full_path = os.path.join(root, file)
                arc_name = os.path.relpath(full_path, ADDON_DIR)
                # doc/<lang>/ 配下の説明書は生成済みの readme.html が正。
                # そこに .md が残っていたら、ビルド前からの古い手書きファイル
                # か生成物への直接編集のどちらかで、どちらもユーザーに届いて
                # はならない（アドオンストアの「ヘルプ」が開くのは HTML の
                # ほうであり、.md は読まれない）。os.path.relpath は Windows
                # でバックスラッシュを返すため、比較前にスラッシュへ正規化する。
                arc_posix = arc_name.replace(os.sep, "/")
                if arc_posix.startswith("doc/") and arc_posix.endswith(".md"):
                    continue
                zf.write(full_path, arc_name)
    print(f"Built: {output_file}")
    return output_file


if __name__ == "__main__":
    build()
