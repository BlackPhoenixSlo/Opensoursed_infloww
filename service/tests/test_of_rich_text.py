"""service/tests/test_of_rich_text.py — OF rich text's allow-list at the send boundary, as tables.

`of_rich_text.sanitize_of_html` keeps p, br, strong, em and span with OF's colour / size classes (b/i renamed), drops
every other tag (its text kept; script/style whole), and is byte-stable on the app editor's own markup. `of_text`
leaves plain text alone. The chat send (`_wrap_text_as_p`), the 1:1 queue and the mass bodies all pass through it.

Run:  ./venv/bin/python service/tests/test_of_rich_text.py   (or under pytest)
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from automations._wordfilter import OutboundGuard, OutboundWordsBlocked  # noqa: E402
from of_client import OUTBOUND_TEXT_GUARD, OFClient, _guard_outbound, _wrap_text_as_p  # noqa: E402
from of_rich_text import is_of_html, of_plain, of_text, sanitize_of_html  # noqa: E402

BLUE_BOLD = '<p><strong><span class="m-editor-fc__blue-1 m-editor-fs__l">Hey babe</span></strong></p>'

# (name, input, sanitized)
TABLE = [
    ("editor output is stable", BLUE_BOLD, BLUE_BOLD),
    ("infloww nesting span > strong", '<p><span class="m-editor-fc__blue-1"><strong>x</strong></span></p>',
     '<p><span class="m-editor-fc__blue-1"><strong>x</strong></span></p>'),
    ("folded blank line", "<p>a<br><br>b</p>", "<p>a<br><br>b</p>"),
    ("br variants", "<p>a<br/>b<br />c</br>d</p>", "<p>a<br>b<br>c<br>d</p>"),
    ("b and i renamed", "<p><b>x</b><i>y</i></p>", "<p><strong>x</strong><em>y</em></p>"),
    ("unknown classes dropped", '<p><span class="m-editor-fc__gray evil m-editor-fs__sm">x</span></p>',
     '<p><span class="m-editor-fc__gray m-editor-fs__sm">x</span></p>'),
    ("span without OF class unwrapped", '<p><span class="x" style="color:red">x</span></p>', "<p>x</p>"),
    ("attributes dropped", '<p onclick="a()"><strong style="x">x</strong></p>', "<p><strong>x</strong></p>"),
    ("script dropped whole", "<p>a<script>alert(1)</script>b</p>", "<p>ab</p>"),
    ("img and link dropped, text kept", '<p><img src=x onerror=1><a href="//e">link</a></p>', "<p>link</p>"),
    ("entities kept escaped", "<p>&lt;3 &amp; &nbsp;x &quot;q&quot;</p>", '<p>&lt;3 &amp; &nbsp;x "q"</p>'),
    ("unclosed marks closed", "<p><strong>a<em>b</p><p>c", "<p><strong>a<em>b</em></strong></p><p>c</p>"),
    ("stray end tag ignored", "<p>a</strong></p>", "<p>a</p>"),
    ("class quote cannot escape", '<p><span class="m-editor-fc__gray&quot; onclick=&quot;x">x</span></p>', "<p>x</p>"),
    ("empty paragraph kept", "<p></p><p>x</p>", "<p></p><p>x</p>"),
    ("uppercase tags", "<P><STRONG>x</STRONG></P>", "<p><strong>x</strong></p>"),
]


def case_sanitize_table():
    for name, html, want in TABLE:
        got = sanitize_of_html(html)
        assert got == want, (name, got)
        assert sanitize_of_html(got) == got, ("idempotent", name)


def case_plain_text_untouched():
    for text in ("hi", "a <3 b", "x & y\nz", "", None, "  <b>not a paragraph</b>"):
        assert of_text(text) == text, text
        assert not is_of_html(text), text
    assert is_of_html("  <p>x</p>") and is_of_html('<p class="a">x</p>') and not is_of_html("<pre>x</pre>")


def case_chat_send_wraps_or_sanitizes():
    assert _wrap_text_as_p("hi\nthere") == "<p>hi<br />there</p>"  # plain: byte-identical to before
    assert _wrap_text_as_p(BLUE_BOLD) == BLUE_BOLD
    assert _wrap_text_as_p('<p>x<img src=x onerror=1></p>') == "<p>x</p>"


def case_queue_and_mass_bodies_sanitize():
    dirty = '<p><strong>x</strong><iframe src="//e">y</iframe></p>'
    body = OFClient._mass_body(text=dirty, user_ids=[1], user_lists=None, excluded_users=None,
                               excluded_user_lists=None, price=0, locked_text=False, media_files=None,
                               previews=None, filters=None, online_only=False)
    assert body["text"] == "<p><strong>x</strong></p>", body["text"]
    body = OFClient._mass_body(text="plain <3", user_ids=[1], user_lists=None, excluded_users=None,
                               excluded_user_lists=None, price=0, locked_text=False, media_files=None,
                               previews=None, filters=None, online_only=False)
    assert body["text"] == "plain <3", body["text"]


def _guarded(text, words, mode):
    guard = OutboundGuard(words, mode)
    tok = OUTBOUND_TEXT_GUARD.set(guard)
    try:
        return _guard_outbound(text), guard
    finally:
        OUTBOUND_TEXT_GUARD.reset(tok)


def case_word_guard_reads_markup_as_text():
    assert of_plain("<p>a<br>b</p><p>c &amp; d</p>") == "a\nb\nc & d"
    # a banned word that is also a class name's part: the class survives, the guard passes once
    dirty = BLUE_BOLD.replace("</p>", '<img src=x></p>')
    got, g = _guarded(dirty, ["blue"], "mask")
    assert got == BLUE_BOLD and g.passed == 1, (got, g.passed)
    # a hit in the text: masked plain text goes (formatting dropped), never a mangled tag
    got, g = _guarded(BLUE_BOLD, ["babe"], "mask")
    assert got == "Hey b***" and g.passed == 1, got
    # a word split across tags is still caught; block mode raises as before
    try:
        _guarded("<p><strong>ba</strong>be</p>", ["babe"], "block")
        raise AssertionError("not blocked")
    except OutboundWordsBlocked:
        pass
    # plain text: as before
    assert _guarded("hey babe", ["babe"], "mask")[0] == "hey b***"
    assert _guard_outbound(BLUE_BOLD) == BLUE_BOLD  # no guard set: unchanged


_harness.run()
