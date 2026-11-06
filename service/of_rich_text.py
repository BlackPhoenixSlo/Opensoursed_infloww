"""OF message text's rich-text allow-list, at the send boundary.

OF's composer (and Infloww's script editor, docs/infloww-rich-text-rea.md) writes a message's `text` as tiptap markup:
`<p>`, `<br>`, `<strong>`, `<em>` and `<span class="...">` carrying only OF's colour and size classes. Scripts and the
chat composer hand that markup to the relay as is, so before it leaves for OF every tag and class outside that list
goes (its text stays; script/style and the like go whole). `b`/`i` become `strong`/`em`. Plain text is never touched
(`of_text`): only a body that starts with a paragraph is markup, the same test `_wrap_text_as_p` and the app's
`isOfHtml` use. The app's renderer applies the same list (app/lib/ofRichText.ts).

Idempotent and byte-stable on the editor's own output (`ofHtml`): text escaped as `&amp; &lt; &gt;`, U+00A0 as
`&nbsp;`, quotes left alone, `<br>` unclosed, classes in their order.
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser

COLOR_CLASSES = ("m-editor-fc__gray", "m-editor-fc__blue-1", "m-editor-fc__blue-2", "m-editor-fc__default")
SIZE_CLASSES = ("m-editor-fs__lg", "m-editor-fs__l", "m-editor-fs__default", "m-editor-fs__s", "m-editor-fs__sm")
_CLASSES = frozenset(COLOR_CLASSES + SIZE_CLASSES)
_RENAME = {"p": "p", "strong": "strong", "b": "strong", "em": "em", "i": "em", "span": "span"}
_DROP_CONTENT = frozenset({"script", "style", "template", "noscript", "iframe", "object", "textarea", "title", "head"})
_IS_HTML = re.compile(r"^\s*<p[\s>]", re.I)


def is_of_html(text: str | None) -> bool:
    """Whether `text` is OF markup (starts with a paragraph) rather than plain text."""
    return bool(text) and bool(_IS_HTML.match(text))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\xa0", "&nbsp;")


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, str | None]] = []  # (source tag, emitted tag or None)
        self.drop = 0
        self.drop_tag = ""

    def handle_starttag(self, tag, attrs):
        if self.drop:
            if tag == self.drop_tag:
                self.drop += 1
            return
        if tag in _DROP_CONTENT:
            self.drop, self.drop_tag = 1, tag
            return
        if tag == "br":
            self.out.append("<br>")
            return
        out = _RENAME.get(tag)
        if out == "p":
            self._close_all()  # a paragraph never nests: close what the last one left open
        if out == "span":
            classes = [c for c in (dict(attrs).get("class") or "").split() if c in _CLASSES]
            cls = " ".join(dict.fromkeys(classes))
            if not cls:
                out = None
            else:
                self.out.append(f'<span class="{cls}">')
                self.stack.append((tag, out))
                return
        if out:
            self.out.append(f"<{out}>")
        self.stack.append((tag, out))

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and not self.drop:
            self.out.append("<br>")

    def handle_endtag(self, tag):
        if self.drop:
            if tag == self.drop_tag:
                self.drop -= 1
            return
        if tag == "br":
            self.out.append("<br>")  # `</br>` reads as a line break in every browser
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for _src, out in reversed(self.stack[i:]):
                    if out:
                        self.out.append(f"</{out}>")
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not self.drop:
            self.out.append(_esc(data))

    def _close_all(self) -> None:
        for _src, out in reversed(self.stack):
            if out:
                self.out.append(f"</{out}>")
        self.stack.clear()

    def result(self) -> str:
        self.close()
        self._close_all()
        return "".join(self.out)


def sanitize_of_html(html: str) -> str:
    """`html` with only OF's message tags and classes left (see the module doc)."""
    p = _Sanitizer()
    p.feed(html)
    return p.result()


def of_text(text):
    """A message `text` as it may leave for OF: markup sanitized, plain text (and None) unchanged."""
    return sanitize_of_html(text) if isinstance(text, str) and is_of_html(text) else text


def of_plain(markup: str) -> str:
    """The text a fan reads in sanitized OF markup: one line per paragraph or `<br>`, entities decoded."""
    s = re.sub(r"^<p>|</p>$", "", markup)
    s = re.sub(r"</p><p>|<br>", "\n", s)
    return _html.unescape(re.sub(r"<[^>]*>", "", s))
