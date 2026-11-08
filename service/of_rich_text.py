"""OF message text's rich-text allow-list, at the send boundary.

OF's composer (and Infloww's script editor, docs/infloww-rich-text-rea.md) writes a message's `text` as tiptap markup:
`<p>`, `<br>`, `<strong>`, `<em>` and `<span class="...">` carrying only OF's colour and size classes. Scripts and the
chat composer hand that markup to the relay as is, so before it leaves for OF every tag and class outside that list
goes (its text stays; script/style and the like go whole; a block such as li/div/h1 ends the paragraph, so its text
is a paragraph of its own, never glued to the next). `b`/`i` become `strong`/`em`. `of_text` reads a text one of
four ways (app/lib/ofRichText.ts `hasHtml` / `ofText` / `ofPlain` the same; one case table pins both:
service/tests/fixtures/of_rich_text_cases.json):
  - OF markup (`is_of_html`: it starts with a paragraph): sanitized;
  - fail closed (`_fails_closed`: an `on...=` handler after a `<letter`, whatever the name or quoting, a
    script/style/iframe/svg/math/... name, whatever follows, or a name `_KNOWN` lacks given an `attr=`, as
    `<x style=...>`): the whole text escaped into one paragraph
    (`escape_as_of_html`, the chat send's plain wrap), so the fan reads it exactly as written and nothing in it is live;
    "my <style is everything>" and "<img src=x onerror=a()>" both go as the text they are;
  - bare formatting (a known HTML name closed as written or given an `attr=`: "hey <b>babe</b>"): sanitized, each
    other `<name ...>` in it kept as text ("<b>SALE</b> use <code VIP20>" keeps the code);
  - plain text (everything else: "<3 u", "code <VIP20>", "<i love you>", "<link in bio>"): never touched.
Fansly has no markup: its sends get `of_plain`.

The sanitizer reads tags with its own tokenizer (`_TOKEN`, app/lib/ofRichText.ts `TAG`, the same regex), not
html.parser, whose handling of an unclosed or odd tag changes between Python releases: a `<` that opens no complete tag
is text, comments, doctypes and `<?...>` hold none. Idempotent and byte-stable on the editor's own output (`ofHtml`):
text escaped as `&amp; &lt; &gt;`, U+00A0 as `&nbsp;`, quotes left alone, `<br>` unclosed, a span's size class before
its colour class (OF's wire); tags nest as given.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from typing import Literal

COLOR_CLASSES = ("m-editor-fc__gray", "m-editor-fc__blue-1", "m-editor-fc__blue-2", "m-editor-fc__default")
SIZE_CLASSES = ("m-editor-fs__lg", "m-editor-fs__l", "m-editor-fs__default", "m-editor-fs__s", "m-editor-fs__sm")
_CLASSES = frozenset(COLOR_CLASSES + SIZE_CLASSES)
_RENAME = {"p": "p", "strong": "strong", "b": "strong", "em": "em", "i": "em", "span": "span"}
_DROP_CONTENT = frozenset({"script", "style", "template", "noscript", "iframe", "object", "textarea", "title", "head"})
# HTML's whitespace, the tokenizer's (not \v, not U+00A0): the same class on both sides (app/lib/ofRichText.ts `WS`).
_WS = "\t\n\f\r "
_IS_HTML = re.compile(r"^[\t\n\f\r ]*<p[\t\n\f\r >]", re.I)
# Blocks OF has no tag for (pasted lists, divs, headings): each is a paragraph boundary, so their texts never glue.
_BLOCK = frozenset({"div", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
                    "section", "article", "header", "footer", "aside", "nav", "main", "figure", "figcaption",
                    "address", "table", "tr", "td", "th", "hr"})
# The HTML names `has_html` knows: one of them, well-formed or given an `attr=`, is a tag (any other name given an
# `attr=` fails closed, `_fails_closed`).
_KNOWN = frozenset("""a abbr address article aside audio b base big blockquote body br button center code dd del details
    div dl dt em embed figcaption figure font footer form h1 h2 h3 h4 h5 h6 head header hr html i iframe img input ins
    label li link main mark math meta nav noscript object ol option p pre s script section select small source span
    strike strong style sub summary sup svg table tbody td template textarea th thead title tr u ul video""".split())
# Names that fail closed whatever follows (the text is escaped, `_fails_closed`): what runs code, styles the page or
# loads a document, what the allow-list drops whole, and the foreign-content roots whose children set handlers and
# links through attribute values (`<svg x><set attributeName=onclick ...>`).
_ACTIVE = _DROP_CONTENT | {"embed", "svg", "math"}
# A tag-shaped run, its name as the browser reads it: `<name` / `</name` up to its `>`, the next `<` or the end.
_RUN = re.compile(r"<(/?)([A-Za-z][^\t\n\f\r /<>]*)([^<>]*)(>?)")
_ATTR_EQ = re.compile(r"""(?:^|[\t\n\f\r /"'])[^\t\n\f\r /<>="']+[\t\n\f\r ]*=""")
_OPEN = re.compile(r"<[A-Za-z]")
# An event handler, on any name, quote-blind: scanned from the first tag opener to the end of the text.
_HANDLER = re.compile(r"""[\t\n\f\r /"']on[A-Za-z0-9_]+[\t\n\f\r ]*=""", re.I)
# OF's message limit (the editor's CharacterCount, docs/infloww-rich-text-rea.md), counted on the text a fan reads
# in UTF-16 code units (`plain_length`).
PLAIN_MAX = 6500
# What a route takes as a message text before it is read at all (the saved-reply and chat-send bodies' `max_length`,
# a 422): OF markup around a plain text of at most PLAIN_MAX. A full-length text with every word its own colour, size
# and bold is ~13x its plain text; x20 leaves room (a caption library's own cap is x10).
MARKUP_MAX = PLAIN_MAX * 20


def is_of_html(text: str | None) -> bool:
    """Whether `text` is OF markup (starts with a paragraph) rather than plain text."""
    return bool(text) and bool(_IS_HTML.match(text))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\xa0", "&nbsp;")


def escape_as_of_html(text: str, br: str = "<br>") -> str:
    """`text` as one OF paragraph a fan reads exactly as written (nothing in it a tag): trimmed of HTML whitespace,
    escaped (`_esc`), each line break a `br`. The chat send's plain wrap (`of_client._wrap_text_as_p`, `<br />`) and
    `of_text`'s fail-closed escape (`<br>`, so the result is byte-stable through `sanitize_of_html`)."""
    return "<p>" + _esc(text.strip(_WS).replace("\r\n", "\n")).replace("\n", br) + "</p>"


# A tag (its name up to HTML whitespace, `/` or `>`; no `<` or NUL in it), whose attributes may quote a `>`; or what
# holds no text: a comment, a doctype or `<![CDATA[...]>` (the browser's bogus comment), a `<?...>`. Any other `<` is
# text. app/lib/ofRichText.ts `TAG`, the same regex. Linear: no part of a token crosses a `<` (a quoted value holds
# none, a comment no `<!--`), so a failed match ends at the next `<` and every `<` is tried once.
_TOKEN = re.compile(r"""<(/?)([a-zA-Z][^\t\n\r\f />\0<]*)(?=[\t\n\r\f />])((?:[^<>"']|"[^"<]*"|'[^'<]*')*)>"""
                    r"""|<!--(?:(?!<!--).)*?-->|<!(?!--)[^<>]*>|<\?[^<>]*>""", re.S)
_SELF_CLOSED = re.compile(r"/[\t\n\f\r ]*$")
_CLASS_ATTR = re.compile(r"""(?:^|[\t\n\f\r /"'])class[\t\n\f\r ]*=[\t\n\f\r ]*(?:"([^"]*)"|'([^']*)'|([^\t\n\f\r >]+))""",
                         re.I)


@dataclass(slots=True)
class _Frame:
    """An open tag on `_Sanitizer.stack`: its source name, the tag it is written as (None: none), and that tag's
    opening while it is still unwritten (else "")."""
    src: str
    out: str | None
    opening: str = ""


class _Sanitizer:
    """Tags as given, with one rule from tiptap's parse (and app/lib/ofRichText.ts `parseOfHtml`): text and line breaks
    make a paragraph, marks do not. A mark is written once text reaches it (`_flush`), so a mark with no text in it
    (`<i>` alone, `<b></b>`) is nothing, and `<b> bold move` outside a paragraph starts one at its first word."""

    def __init__(self) -> None:
        self.out: list[str] = []
        self.stack: list[_Frame] = []  # a paragraph only ever at [0]
        self.unwritten: int | None = None  # the lowest stack index holding an unwritten mark
        self.opened: dict[str, int] = {}  # source tag -> how many are on the stack
        self.drop = 0
        self.drop_tag = ""

    def feed(self, html: str) -> None:
        at = 0
        for m in _TOKEN.finditer(html):
            if m.start() > at:
                self.handle_data(_html.unescape(html[at:m.start()]))
            at = m.end()
            if not m.group(2):
                continue  # a comment, doctype, `<?...>`: no text
            tag, attrs = m.group(2).lower(), m.group(3)
            if m.group(1):
                self.handle_endtag(tag)
            elif _SELF_CLOSED.search(attrs):
                self.handle_startendtag(tag)
            else:
                self.handle_starttag(tag, attrs)
        if at < len(html):
            self.handle_data(_html.unescape(html[at:]))

    def handle_starttag(self, tag: str, attrs: str) -> None:
        if self.drop:
            if tag == self.drop_tag:
                self.drop += 1
            return
        if tag in _DROP_CONTENT:
            self.drop, self.drop_tag = 1, tag
            return
        if tag in _BLOCK:
            self._close_all()
            return
        if tag == "br":
            self._br()
            return
        out = _RENAME.get(tag)
        if out == "p":
            self._close_all()  # a paragraph never nests: close what the last one left open
            self.out.append("<p>")
            self._push(_Frame(tag, out))
            return
        opening = f"<{out}>" if out else ""
        if out == "span":
            c = _CLASS_ATTR.search(attrs)
            value = _html.unescape(next((g for g in c.groups() if g is not None), "")) if c else ""
            classes = [c for c in value.split() if c in _CLASSES]
            # OF's wire order (measured, a chat send from onlyfans.com 2026-11-06): size class, then colour class.
            cls = " ".join(sorted(dict.fromkeys(classes), key=lambda c: not c.startswith("m-editor-fs__")))
            out, opening = ("span", f'<span class="{cls}">') if cls else (None, "")
        self._push(_Frame(tag, out, opening))

    def handle_startendtag(self, tag: str) -> None:
        if self.drop:
            return
        if tag == "br":
            self._br()
        elif tag in _BLOCK:
            self._close_all()

    def handle_endtag(self, tag: str) -> None:
        if self.drop:
            if tag == self.drop_tag:
                self.drop -= 1
            return
        if tag == "br":
            self._br()  # `</br>` reads as a line break in every browser
            return
        if tag in _BLOCK or tag == "p":
            self._close_all()  # `</p>` ends the paragraph and every mark, open or not (tiptap's parse)
            return
        if not self.opened.get(tag):
            return
        for i in range(len(self.stack) - 1, -1, -1):  # what it passes is closed with it: linear overall
            if self.stack[i].src == tag:
                self._close(self.stack[i:])
                self._cut(i)
                return

    def handle_data(self, data: str) -> None:
        if self.drop:
            return
        if not self._in_p():
            data = data.lstrip(_WS)  # between blocks: layout whitespace, never a paragraph of its own
            if not data:
                return
            self._open_p()
        self._flush()
        self.out.append(_esc(data))

    def _push(self, frame: _Frame) -> None:
        if frame.opening and self.unwritten is None:
            self.unwritten = len(self.stack)
        self.stack.append(frame)
        self.opened[frame.src] = self.opened.get(frame.src, 0) + 1

    def _cut(self, i: int) -> None:
        for f in self.stack[i:]:
            self.opened[f.src] -= 1
        del self.stack[i:]
        if self.unwritten is not None and self.unwritten >= i:
            self.unwritten = None

    def _in_p(self) -> bool:
        return bool(self.stack) and self.stack[0].out == "p"

    def _open_p(self) -> None:
        """Text or a break outside any paragraph (after a block): it starts one."""
        if not self._in_p():
            self.out.append("<p>")
            self.stack.insert(0, _Frame("p", "p"))  # under what is open: a dropped tag's end closes only itself
            self.opened["p"] = self.opened.get("p", 0) + 1
            if self.unwritten is not None:
                self.unwritten += 1

    def _br(self) -> None:
        self._open_p()
        self.out.append("<br>")

    def _flush(self) -> None:
        """Text is coming: write the marks around it not yet written."""
        if self.unwritten is None:
            return
        for f in self.stack[self.unwritten:]:
            if f.opening:
                self.out.append(f.opening)
                f.opening = ""
        self.unwritten = None

    def _close(self, frames: list[_Frame]) -> None:
        for f in reversed(frames):
            if f.out and not f.opening:
                self.out.append(f"</{f.out}>")

    def _close_all(self) -> None:
        self._close(self.stack)
        self._cut(0)

    def result(self) -> str:
        self._close_all()
        return "".join(self.out)


def sanitize_of_html(html: str) -> str:
    """`html` with only OF's message tags and classes left (see the module doc)."""
    p = _Sanitizer()
    p.feed(html)
    return p.result()


def _fails_closed(text: str) -> bool:
    """A tag that may be hostile whatever its syntax: an `_ACTIVE` name, whatever follows (`<svg x>`, `<style tips>`),
    a name `_KNOWN` lacks given an `attr=` (`<x style=...>`, `<applet code=x>`, `<frame src=...>`), or, quote-blind,
    an `on...=` handler anywhere after the first `<letter`, on any name (`<x.y onclick=a()>`,
    `<img src=x onerror=a() hidden>`). `of_text` escapes such a text whole rather than read it as markup."""
    for m in _RUN.finditer(text):
        name = m.group(2).lower()
        if name in _ACTIVE or (name not in _KNOWN and _ATTR_EQ.search(m.group(3))):
            return True
    m = _OPEN.search(text)
    return bool(m and _HANDLER.search(text, m.start()))


def _is_tag(m: re.Match) -> bool:
    """A known HTML name closed as written (`</b>`, `<br/>`) or given an `attr=` (`<a href=x>`)."""
    rest = m.group(3)
    return m.group(2).lower() in _KNOWN and bool(_ATTR_EQ.search(rest) or (m.group(4) and rest.strip(_WS) in ("", "/")))


_Kind = Literal["of", "escape", "bare"] | None


def _kind(text: str) -> _Kind:
    """How `of_text` reads `text` (module doc): "of", "escape", "bare", or None (plain text)."""
    if is_of_html(text):
        return "of"
    if _fails_closed(text):
        return "escape"
    if any(_is_tag(m) for m in _RUN.finditer(text)):
        return "bare"
    return None


def has_html(text: str | None) -> bool:
    """Whether the send boundary rewrites `text` (`of_text`): OF markup, a text that fails closed (escaped whole), or
    bare formatting (sanitized). Prose in angles is plain and goes as written: "<3 u", "code <VIP20>",
    "<i love you>", "<link in bio>", "<video coming soon>" (app/lib/ofRichText.ts `hasHtml`, one case table:
    service/tests/fixtures/of_rich_text_cases.json)."""
    return isinstance(text, str) and _kind(text) is not None


def of_text(text):
    """A message `text` as it may leave for OF (module doc): OF markup and bare formatting sanitized (bare tags keep
    their line breaks, `\n` -> `<br>`, inside the paragraph they get), a text that fails closed escaped whole into
    one paragraph, plain text (and None) unchanged. Outside OF markup no word outside a tag is ever dropped (a name
    whose content the allow-list drops whole fails closed; a bare text's `<name ...>` that is no tag is kept as
    text, `_only_tags`)."""
    if not isinstance(text, str):
        return text
    kind = _kind(text)
    if kind == "of":
        return sanitize_of_html(text)
    if kind == "escape":
        return escape_as_of_html(text)
    if kind == "bare":
        return sanitize_of_html(_only_tags(text).replace("\r\n", "\n").replace("\n", "<br>"))
    return text


def _only_tags(text: str) -> str:
    """Bare formatting with each tag-shaped run that is no tag (`_is_tag`) escaped, so the sanitizer keeps the prose
    around the tags as written: `<b>SALE</b> use <code VIP20>` keeps `<code VIP20>`, `<b>x</b> <name>` its name."""
    return _RUN.sub(lambda m: m.group(0) if _is_tag(m) else "&lt;" + m.group(0)[1:], text)


_FORMAT_TAG = re.compile(r"<(?:strong|em|span)[\s>]")


def of_rich_html(body: str | None) -> str | None:
    """A scraped OF body's sanitized markup when it carries formatting (bold, italic, an OF colour or size class),
    else None: plain text, and markup that is only paragraphs and breaks, need no copy beside the plain text."""
    if not is_of_html(body):
        return None
    clean = sanitize_of_html(body)
    return clean if _FORMAT_TAG.search(clean) else None


def of_plain(text: str | None) -> str:
    """The text a fan reads: markup (sanitized first) as one line per paragraph or `<br>`, entities decoded, U+00A0
    as a space (app/lib/ofRichText.ts `ofPlain`); plain text as is."""
    if not has_html(text):
        return text or ""
    s = re.sub(r"^<p>|</p>$", "", of_text(text))
    s = re.sub(r"</p><p>|<br>", "\n", s)
    return _html.unescape(re.sub(r"<[^>]*>", "", s)).replace("\xa0", " ")


def drops_all_text(raw: str | None, text: str | None) -> bool:
    """Whether `text` (`raw`'s `of_text`) keeps nothing a fan would read of a `raw` that held something (`<img src=x>`,
    every word inside a dropped tag): a script stores such a text never, blank. OF's own empty markup (`<p></p>`, a
    media-only script's text) is not that."""
    return bool((raw or "").strip()) and not of_plain(text).strip() and not is_of_html(raw)


def plain_length(text: str | None) -> int:
    """`text`'s length as the fan reads it (markup: its plain text), in UTF-16 code units: OF's limit is its editor's
    CharacterCount, `textCounter: S => S.length` (measured in the Infloww SPA's copy of OF's editor,
    docs/infloww-rich-text-rea.md), so an emoji outside the BMP counts 2, as the app's `plainLength` does. A paragraph
    boundary counts 1 (OF's counts 0): never more lenient than OF."""
    return len(of_plain(text).encode("utf-16-le", "surrogatepass")) // 2
