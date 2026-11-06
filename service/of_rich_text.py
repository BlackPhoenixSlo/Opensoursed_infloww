"""OF message text's rich-text allow-list, at the send boundary.

OF's composer (and Infloww's script editor, docs/infloww-rich-text-rea.md) writes a message's `text` as tiptap markup:
`<p>`, `<br>`, `<strong>`, `<em>` and `<span class="...">` carrying only OF's colour and size classes. Scripts and the
chat composer hand that markup to the relay as is, so before it leaves for OF every tag and class outside that list
goes (its text stays; script/style and the like go whole; a block such as li/div/h1 ends the paragraph, so its text
is a paragraph of its own, never glued to the next). `b`/`i` become `strong`/`em`. Plain text is never touched
(`of_text`): a body that starts with a paragraph is OF markup (`is_of_html`, the test `_wrap_text_as_p` and the app's
`isOfHtml` use), and so is one holding any HTML tag (`has_html`: `<strong onclick=x>` is sanitized, "<3 u" stays).
Fansly has no markup: its sends get `of_plain`. The app's renderer applies the same list (app/lib/ofRichText.ts).

Idempotent and byte-stable on the editor's own output (`ofHtml`): text escaped as `&amp; &lt; &gt;`, U+00A0 as
`&nbsp;`, quotes left alone, `<br>` unclosed, a span's size class before its colour class (OF's wire); tags
nest as given.
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
# Blocks OF has no tag for (pasted lists, divs, headings): each is a paragraph boundary, so their texts never glue.
_BLOCK = frozenset({"div", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
                    "section", "article", "header", "footer", "aside", "nav", "main", "figure", "figcaption",
                    "address", "table", "tr", "td", "th", "hr"})
_TAG_NAMES = ("a|abbr|article|aside|audio|b|base|big|blockquote|body|br|button|center|code|dd|del|details|div|dl|dt|em|"
              "embed|figcaption|figure|font|footer|form|h[1-6]|head|header|hr|html|i|iframe|img|input|ins|label|li|"
              "link|main|mark|math|meta|nav|noscript|object|ol|option|p|pre|s|script|section|select|small|source|"
              "span|strike|strong|style|sub|summary|sup|svg|table|tbody|td|template|textarea|th|thead|title|tr|u|"
              "ul|video")
_ATTR = r"""(?:\s+[A-Za-z_:][\w:.-]*\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))"""
_TAG = re.compile(rf"<(?:{_TAG_NAMES})(?:{_ATTR})*\s*/?>|</(?:{_TAG_NAMES})\s*>", re.I)
# OF's message limit (the editor's CharacterCount, docs/infloww-rich-text-rea.md), counted on the text a fan reads.
PLAIN_MAX = 6500


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
        if tag in _BLOCK:
            self._close_all()
            return
        if tag == "br":
            self._open_p()
            self.out.append("<br>")
            return
        out = _RENAME.get(tag)
        if out == "p":
            self._close_all()  # a paragraph never nests: close what the last one left open
        elif out:
            self._open_p()
        if out == "span":
            classes = [c for c in (dict(attrs).get("class") or "").split() if c in _CLASSES]
            # OF's wire order (measured, a chat send from onlyfans.com 2026-11-06): size class, then colour class.
            cls = " ".join(sorted(dict.fromkeys(classes), key=lambda c: not c.startswith("m-editor-fs__")))
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
        if self.drop:
            return
        if tag == "br":
            self._open_p()
            self.out.append("<br>")
        elif tag in _BLOCK:
            self._close_all()

    def handle_endtag(self, tag):
        if self.drop:
            if tag == self.drop_tag:
                self.drop -= 1
            return
        if tag == "br":
            self._open_p()
            self.out.append("<br>")  # `</br>` reads as a line break in every browser
            return
        if tag in _BLOCK:
            self._close_all()
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for _src, out in reversed(self.stack[i:]):
                    if out:
                        self.out.append(f"</{out}>")
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self.drop:
            return
        if not self._in_p():
            data = data.lstrip()  # between blocks: layout whitespace, never a paragraph of its own
            if not data:
                return
            self._open_p()
        self.out.append(_esc(data))

    def _in_p(self) -> bool:
        return any(out == "p" for _src, out in self.stack)

    def _open_p(self) -> None:
        """Text, a mark or a break outside any paragraph (after a block): it starts one."""
        if not self._in_p():
            self.out.append("<p>")
            self.stack.insert(0, ("p", "p"))  # under what is open: a dropped tag's end closes only itself

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


def has_html(text: str | None) -> bool:
    """Whether `text` holds markup: OF's own (`is_of_html`) or an HTML tag anywhere (`<strong onclick=x>`, `</b>`).
    A tag is a known HTML name with nothing or only `name=value` attributes after it, so plain text such as
    "<3 u", "code <VIP20>" or "<i love you>" is never read as markup."""
    return is_of_html(text) or (isinstance(text, str) and bool(_TAG.search(text)))


def of_text(text):
    """A message `text` as it may leave for OF: markup sanitized, plain text (and None) unchanged. Text with a tag
    that is not OF's paragraph markup keeps its line breaks (`\n` -> `<br>`) inside the paragraph it gets."""
    if not isinstance(text, str) or not has_html(text):
        return text
    if is_of_html(text):
        return sanitize_of_html(text)
    return sanitize_of_html(text.replace("\r\n", "\n").replace("\n", "<br>"))


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
    as a space (app/lib/ofRichTextEditor.ts `ofPlainText`); plain text as is."""
    if not has_html(text):
        return text or ""
    s = re.sub(r"^<p>|</p>$", "", of_text(text))
    s = re.sub(r"</p><p>|<br>", "\n", s)
    return _html.unescape(re.sub(r"<[^>]*>", "", s)).replace("\xa0", " ")


def plain_length(text: str | None) -> int:
    """`text`'s length as the fan reads it (markup: its plain text), the length OF's limit counts."""
    return len(of_plain(text))
