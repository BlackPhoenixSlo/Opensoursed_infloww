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
# HTML whitespace as the tokenizer reads it (not \v, not U+00A0); same class as app/lib/ofRichText.ts WS.
_WS = "\t\n\f\r "
_IS_HTML = re.compile(r"^[\t\n\f\r ]*<p[\t\n\f\r >]", re.I)
_BLOCK = frozenset({"div", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
                    "section", "article", "header", "footer", "aside", "nav", "main", "figure", "figcaption",
                    "address", "table", "tr", "td", "th", "hr"})
_KNOWN = frozenset("""a abbr address article aside audio b base big blockquote body br button center code dd del details
    div dl dt em embed figcaption figure font footer form h1 h2 h3 h4 h5 h6 head header hr html i iframe img input ins
    label li link main mark math meta nav noscript object ol option p pre s script section select small source span
    strike strong style sub summary sup svg table tbody td template textarea th thead title tr u ul video""".split())
# Fail closed whatever follows: code/style/document loaders and foreign-content roots (svg/math) whose children set handlers via attributes.
_ACTIVE = _DROP_CONTENT | {"embed", "svg", "math"}
_RUN = re.compile(r"<(/?)([A-Za-z][^\t\n\f\r /<>]*)([^<>]*)(>?)")
_ATTR_EQ = re.compile(r"""(?:^|[\t\n\f\r /"'])[^\t\n\f\r /<>="']+[\t\n\f\r ]*=""")
_OPEN = re.compile(r"<[A-Za-z]")
# Event handler on any name, quote-blind, scanned from the first tag opener.
_HANDLER = re.compile(r"""[\t\n\f\r /"']on[A-Za-z0-9_]+[\t\n\f\r ]*=""", re.I)
# OF's message limit (editor CharacterCount), in UTF-16 code units of the text a fan reads.
PLAIN_MAX = 6500
# Fully styled text is ~13x its plain length; x20 leaves room.
MARKUP_MAX = PLAIN_MAX * 20


def is_of_html(text: str | None) -> bool:
    return bool(text) and bool(_IS_HTML.match(text))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\xa0", "&nbsp;")


def escape_as_of_html(text: str, br: str = "<br>") -> str:
    return "<p>" + _esc(text.strip(_WS).replace("\r\n", "\n")).replace("\n", br) + "</p>"


# Same regex as app/lib/ofRichText.ts TAG; linear: no token crosses a `<`.
_TOKEN = re.compile(r"""<(/?)([a-zA-Z][^\t\n\r\f />\0<]*)(?=[\t\n\r\f />])((?:[^<>"']|"[^"<]*"|'[^'<]*')*)>"""
                    r"""|<!--(?:(?!<!--).)*?-->|<!(?!--)[^<>]*>|<\?[^<>]*>""", re.S)
_SELF_CLOSED = re.compile(r"/[\t\n\f\r ]*$")
_CLASS_ATTR = re.compile(r"""(?:^|[\t\n\f\r /"'])class[\t\n\f\r ]*=[\t\n\f\r ]*(?:"([^"]*)"|'([^']*)'|([^\t\n\f\r >]+))""",
                         re.I)


@dataclass(slots=True)
class _Frame:
    src: str
    out: str | None
    opening: str = ""


class _Sanitizer:

    def __init__(self) -> None:
        self.out: list[str] = []
        self.stack: list[_Frame] = []
        self.unwritten: int | None = None
        self.opened: dict[str, int] = {}
        self.drop = 0
        self.drop_tag = ""

    def feed(self, html: str) -> None:
        at = 0
        for m in _TOKEN.finditer(html):
            if m.start() > at:
                self.handle_data(_html.unescape(html[at:m.start()]))
            at = m.end()
            if not m.group(2):
                continue
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
            self._close_all()
            self.out.append("<p>")
            self._push(_Frame(tag, out))
            return
        opening = f"<{out}>" if out else ""
        if out == "span":
            c = _CLASS_ATTR.search(attrs)
            value = _html.unescape(next((g for g in c.groups() if g is not None), "")) if c else ""
            classes = [c for c in value.split() if c in _CLASSES]
            # OF's wire order (measured): size class, then colour class.
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
            self._br()
            return
        if tag in _BLOCK or tag == "p":
            self._close_all()
            return
        if not self.opened.get(tag):
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].src == tag:
                self._close(self.stack[i:])
                self._cut(i)
                return

    def handle_data(self, data: str) -> None:
        if self.drop:
            return
        if not self._in_p():
            data = data.lstrip(_WS)
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
        if not self._in_p():
            self.out.append("<p>")
            self.stack.insert(0, _Frame("p", "p"))
            self.opened["p"] = self.opened.get("p", 0) + 1
            if self.unwritten is not None:
                self.unwritten += 1

    def _br(self) -> None:
        self._open_p()
        self.out.append("<br>")

    def _flush(self) -> None:
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
    p = _Sanitizer()
    p.feed(html)
    return p.result()


def _fails_closed(text: str) -> bool:
    for m in _RUN.finditer(text):
        name = m.group(2).lower()
        if name in _ACTIVE or (name not in _KNOWN and _ATTR_EQ.search(m.group(3))):
            return True
    m = _OPEN.search(text)
    return bool(m and _HANDLER.search(text, m.start()))


def _is_tag(m: re.Match) -> bool:
    rest = m.group(3)
    return m.group(2).lower() in _KNOWN and bool(_ATTR_EQ.search(rest) or (m.group(4) and rest.strip(_WS) in ("", "/")))


_Kind = Literal["of", "escape", "bare"] | None


def _kind(text: str) -> _Kind:
    if is_of_html(text):
        return "of"
    if _fails_closed(text):
        return "escape"
    if any(_is_tag(m) for m in _RUN.finditer(text)):
        return "bare"
    return None


def has_html(text: str | None) -> bool:
    return isinstance(text, str) and _kind(text) is not None


def of_text(text):
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
    return _RUN.sub(lambda m: m.group(0) if _is_tag(m) else "&lt;" + m.group(0)[1:], text)


_FORMAT = re.compile(r"<(?:strong|em)>|m-editor-f[cs]__(?!default\b)")


def of_rich_html(body: str | None) -> str | None:
    if not is_of_html(body):
        return None
    clean = sanitize_of_html(body)
    if _FORMAT.search(clean):
        return clean
    plain = of_plain(clean)
    return clean if of_plain(plain) != plain else None


def of_plain(text: str | None) -> str:
    if not has_html(text):
        return text or ""
    s = re.sub(r"^<p>|</p>$", "", of_text(text))
    s = re.sub(r"</p><p>|<br>", "\n", s)
    return _html.unescape(re.sub(r"<[^>]*>", "", s)).replace("\xa0", " ")


def drops_all_text(raw: str | None, text: str | None) -> bool:
    return bool((raw or "").strip()) and not of_plain(text).strip() and not is_of_html(raw)


def plain_length(text: str | None) -> int:
    return len(of_plain(text).encode("utf-16-le", "surrogatepass")) // 2
