"""service/tests/test_of_rich_text.py — OF rich text's allow-list at the send boundary, as tables.

`of_rich_text.sanitize_of_html` keeps p, br, strong, em and span with OF's colour / size classes (b/i renamed), drops
every other tag (its text kept; script/style whole), and is byte-stable on the app editor's own markup. `of_text`
leaves plain text alone. The chat send (`_wrap_text_as_p`), the 1:1 queue, the mass and the post bodies all pass through it.

Run:  ./venv/bin/python service/tests/test_of_rich_text.py   (or under pytest)
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from automations._wordfilter import OutboundGuard, OutboundWordsBlocked  # noqa: E402
from of_client import OUTBOUND_TEXT_GUARD, OFClient, _guard_outbound, _wrap_text_as_p  # noqa: E402
from of_rich_text import has_html, is_of_html, of_plain, of_rich_html, of_text, plain_length, sanitize_of_html  # noqa: E402

BLUE_BOLD = '<p><span class="m-editor-fs__l m-editor-fc__blue-1"><strong>Hey babe</strong></span></p>'

# (name, input, sanitized)
TABLE = [
    ("editor output is stable", BLUE_BOLD, BLUE_BOLD),
    ("infloww nesting span > strong", '<p><span class="m-editor-fc__blue-1"><strong>x</strong></span></p>',
     '<p><span class="m-editor-fc__blue-1"><strong>x</strong></span></p>'),
    ("folded blank line", "<p>a<br><br>b</p>", "<p>a<br><br>b</p>"),
    ("br variants", "<p>a<br/>b<br />c</br>d</p>", "<p>a<br>b<br>c<br>d</p>"),
    ("b and i renamed", "<p><b>x</b><i>y</i></p>", "<p><strong>x</strong><em>y</em></p>"),
    ("unknown classes dropped", '<p><span class="m-editor-fc__gray evil m-editor-fs__sm">x</span></p>',
     '<p><span class="m-editor-fs__sm m-editor-fc__gray">x</span></p>'),
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
    # a block OF has no tag for ends the paragraph: its text is a paragraph of its own, never glued
    ("list items are paragraphs", "<p>a</p><ul><li>x</li><li>y</li></ul>", "<p>a</p><p>x</p><p>y</p>"),
    ("divs and headings", "<p>a</p><div>b</div><h1>c</h1><h6><b>d</b></h6>", "<p>a</p><p>b</p><p>c</p><p><strong>d</strong></p>"),
    ("block inside a paragraph splits it", "<p>a<div>b</div>c</p>", "<p>a</p><p>b</p><p>c</p>"),
    ("layout whitespace between blocks", "<p>a</p>\n<ul>\n  <li> x</li>\n</ul>", "<p>a</p><p>x</p>"),
    ("p inside li not doubled", "<p>a</p><ol><li><p>x</p></li></ol>", "<p>a</p><p>x</p>"),
    ("dropped tag after a block", '<p>a</p><div><a href="//e">l</a> b</div>', "<p>a</p><p>l b</p>"),
    ("table cells", "<p>a</p><table><tr><td>1</td><td>2</td></tr></table>", "<p>a</p><p>1</p><p>2</p>"),
    ("hr and br between blocks", "<p>a</p><hr><br>b", "<p>a</p><p><br>b</p>"),
]

# (name, text, has_html, of_text) — any HTML tag is markup; "<" in plain text is not
HAS_HTML = [
    ("heart", "<3 u", False, "<3 u"),
    ("angle code", "code <VIP20>", False, "code <VIP20>"),
    ("prose in angles", "<i love you>", False, "<i love you>"),
    ("maths", "x < y > z", False, "x < y > z"),
    ("lone open", "a <b", False, "a <b"),
    ("bare b", "hey <b>babe</b>", True, "<p>hey <strong>babe</strong></p>"),
    ("event attr", "<strong onclick=bad>Hi</strong>", True, "<p><strong>Hi</strong></p>"),
    ("quoted attr", '<img src="x" onerror="1">hi', True, "<p>hi</p>"),
    ("closing only", "hi</em>", True, "<p>hi</p>"),
    ("newlines kept as br", "hi\n<b>x</b>\r\nyo", True, "<p>hi<br><strong>x</strong><br>yo</p>"),
    ("script", "a<script>alert(1)</script>", True, "<p>a</p>"),
    ("of markup", "<p>x</p>", True, "<p>x</p>"),
]

# (name, text, plain)
PLAIN = [
    ("paragraphs and br", "<p>a<br>b</p><p>c &amp; d</p>", "a\nb\nc & d"),
    ("list", "<p>a</p><ul><li>x</li><li>y</li></ul>", "a\nx\ny"),
    ("nbsp is a space", "<p>a&nbsp;b</p>", "a b"),
    ("raw hostile markup", '<p>x<img src=x onerror=1><script>y</script></p>', "x"),
    ("bare tags", "hey <b>babe</b>", "hey babe"),
    ("plain unchanged", "a <3 &amp; b", "a <3 &amp; b"),
    ("none", None, ""),
]


def case_sanitize_table():
    for name, html, want in TABLE:
        got = sanitize_of_html(html)
        assert got == want, (name, got)
        assert sanitize_of_html(got) == got, ("idempotent", name)


def case_has_html_and_of_text_table():
    for name, text, markup, want in HAS_HTML:
        assert has_html(text) is markup, (name, text)
        got = of_text(text)
        assert got == want, (name, got)
        assert of_text(got) == got, ("idempotent", name, got)


def case_of_plain_table():
    for name, text, want in PLAIN:
        assert of_plain(text) == want, (name, of_plain(text))
    assert plain_length("<p><strong>" + "x" * 10 + "</strong></p>") == 10
    assert plain_length("plain") == 5 and plain_length(None) == 0


def case_plain_text_untouched():
    for text in ("hi", "a <3 b", "x & y\nz", "", None, "code <VIP20>"):
        assert of_text(text) == text, text
        assert not is_of_html(text), text
    assert not is_of_html("  <b>not a paragraph</b>")  # bare tags: sanitized (has_html), never the chat's markup
    assert is_of_html("  <p>x</p>") and is_of_html('<p class="a">x</p>') and not is_of_html("<pre>x</pre>")


def case_rich_html_only_when_formatted():
    """A scraped body's markup is kept (sanitized) only when it carries formatting."""
    har = '<p><span class="m-editor-fs__l m-editor-fc__blue-2"><strong>safgsfg</strong></span></p>'
    for body, want in [
        (har, har),
        ("<p><i>x</i></p>", "<p><em>x</em></p>"),
        ('<p><span class="m-editor-fc__default">x</span></p>', '<p><span class="m-editor-fc__default">x</span></p>'),
        ("<p>plain<br>two lines</p>", None),
        ('<p><span class="evil">x</span></p>', None),
        ("<p>a<script>b</script></p>", None),
        ("<strong>not a paragraph</strong>", None),
        ("plain", None), ("", None), (None, None),
    ]:
        assert of_rich_html(body) == want, (body, of_rich_html(body))


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


def case_post_bodies_sanitize():
    """New post (and Edit post / a queued post's save) from the OF Manager send its Format text markup: same list."""
    dirty = '<p onclick="x()"><b>x</b><script>a()</script><span class="m-editor-fc__blue-1 evil">y</span></p>'
    clean = '<p><strong>x</strong><span class="m-editor-fc__blue-1">y</span></p>'
    assert OFClient._post_body(dirty)["text"] == clean
    assert OFClient._post_body(BLUE_BOLD)["text"] == BLUE_BOLD
    assert OFClient._post_body("plain <3 & co")["text"] == "plain <3 & co"
    sent = {}
    client = OFClient.__new__(OFClient)
    client.put_json = lambda url, json_body: sent.update(json_body) or {}
    client.edit_post(5, text=dirty)
    assert sent["text"] == clean, sent


def _guarded(text, words, mode):
    guard = OutboundGuard(words, mode)
    tok = OUTBOUND_TEXT_GUARD.set(guard)
    try:
        return _guard_outbound(text), guard
    finally:
        OUTBOUND_TEXT_GUARD.reset(tok)


def case_word_guard_reads_markup_as_text():
    # a banned word that is also a class name's part: passes once, the markup goes on as is (the send's boundary
    # sanitizes it)
    dirty = BLUE_BOLD.replace("</p>", '<img src=x></p>')
    got, g = _guarded(dirty, ["blue"], "block")
    assert got == dirty and g.passed == 1, (got, g.passed)
    assert _wrap_text_as_p(got) == BLUE_BOLD
    # a word split across tags is still caught, in OF markup or bare tags
    for text in ("<p><strong>ba</strong>be</p>", "hey <b>ba</b>be"):
        try:
            _guarded(text, ["babe"], "block")
            raise AssertionError(f"not blocked: {text}")
        except OutboundWordsBlocked:
            pass
    # plain text: as before (mask still masks it)
    assert _guarded("hey babe", ["babe"], "mask")[0] == "hey b***"
    assert _guard_outbound(BLUE_BOLD) == BLUE_BOLD  # no guard set: unchanged


class _PostSpy(OFClient):
    """A real OFClient whose wire is a list: every POST/PUT body captured."""

    def __init__(self):
        self.bodies: list[dict] = []

    def _post_dropping_auto_cotag(self, path, body, retry_plan):
        self.bodies.append(body)
        return {"id": 1}

    def post_json(self, url, json_body=None, **_k):
        self.bodies.append(json_body)
        return {}

    put_json = post_json

    def _apply_cotags(self, body, *_a):
        return None


def case_post_edit_and_comment_bodies_sanitize():
    dirty = '<p><strong onclick="x">hi</strong><iframe src="//e">y</iframe></p>'
    clean = "<p><strong>hi</strong></p>"
    spy = _PostSpy()
    spy.create_post(dirty)
    spy.save_queued_post(7, dirty)
    spy.edit_post(7, text=dirty)
    spy.comment_on_post(7, dirty)
    spy.create_post("plain <3 & co")
    spy.edit_post(7, price=5)
    got = [b.get("text") for b in spy.bodies]
    assert got == [clean, clean, clean, clean, "plain <3 & co", None], got


def _fansly_shim():
    import sys
    from pathlib import Path
    fansly_dir = str(Path(__file__).resolve().parents[2] / "fansly")
    if fansly_dir not in sys.path:
        sys.path.insert(0, fansly_dir)
    from fansly_client import FanslySession
    from fansly_shim import FanslyShimClient
    c = FanslyShimClient(FanslySession({"accountId": "1", "token": "t", "check_key": "k", "device_id": "d",
                                        "user_agent": "Mozilla/5.0"}))
    wire: list[tuple[str, dict]] = []

    def fake(method, path, *, params=None, json_body=None, **_kw):
        wire.append((path, json_body))
        if path == "/account/me":
            return {"account": {"id": "1", "walls": [{"id": "9", "mainWall": True}]}}
        if path == "/message" or path == "/message/broadcast":
            return {"id": "5", "groupId": json_body["groupId"], "senderId": "1",
                    "content": json_body.get("content", ""), "createdAt": 0, "attachments": []}
        return {"id": "5"}
    c._request = fake
    c._known_group_ids.add("77")
    c._broadcast_group = lambda **_k: "88"
    return c, wire


# (name, text, Fansly content) — Fansly renders content literally: markup goes as the plain text a fan reads
FANSLY = [
    ("formatted script", BLUE_BOLD, "Hey babe"),
    ("two lines and a list", "<p>hi<br>there</p><ul><li>a</li></ul>", "hi\nthere\na"),
    ("bare tags", "hey <b>babe</b>", "hey babe"),
    ("plain kept", "hey <3 & co", "hey <3 & co"),
]


def case_fansly_sends_formatted_text_as_plain():
    for name, text, want in FANSLY:
        for lane in ("chat", "post", "broadcast"):
            c, wire = _fansly_shim()
            if lane == "chat":
                c.send_message("77", text)
            elif lane == "post":
                c.create_post(text)
            else:
                c.send_mass_message(text, confirm_live_broadcast=True)
            sent = [b["content"] for p, b in wire if p in ("/message", "/message/broadcast", "/post")]
            assert sent == [want], (name, lane, sent)
    # under an automation's guard too, and a banned word split by tags is still caught
    tok = OUTBOUND_TEXT_GUARD.set(OutboundGuard(["babe"], "block"))
    try:
        c, wire = _fansly_shim()
        c.send_message("77", "<p>hi <em>there</em></p>")
        assert [b["content"] for p, b in wire if p == "/message"] == ["hi there"], wire
        try:
            c.send_message("77", "<p>ba<strong>be</strong></p>")
            raise AssertionError("not blocked")
        except OutboundWordsBlocked:
            pass
    finally:
        OUTBOUND_TEXT_GUARD.reset(tok)


def case_placeholders_escape_into_markup_only():
    from automations._fan_notes import substitute_placeholders
    fan = {"home_city": "<em>X</em> & Co"}
    assert substitute_placeholders("<p>hi {name} from {city}</p>", fan, name="<b>Al</b>") == \
        "<p>hi &lt;b&gt;Al&lt;/b&gt; from &lt;em&gt;X&lt;/em&gt; &amp; Co</p>"
    assert of_plain(of_text(substitute_placeholders("<p>{city}</p>", fan))) == "<em>X</em> & Co"
    # a plain template keeps the values' bytes
    assert substitute_placeholders("hi {name} from {city}", fan, name="Al") == "hi Al from <em>X</em> & Co"


def case_csv_export_is_plain():
    from types import SimpleNamespace
    from messages_query import _csv_row
    row = SimpleNamespace(**{k: None for k in ("message_id", "account_id", "fan_id", "of_username",
                                               "of_display_name", "direction", "created_at", "media_count",
                                               "price_cents", "is_paid", "is_tip", "purchased_at",
                                               "sent_by_employee_id", "employee_name", "automation_kind")})
    row.body = "<p>a &amp; b</p><p>" + "y" * 2500 + "</p>"
    cell = _csv_row(row, {})[8]
    assert cell == ("a & b\n" + "y" * 2500)[:2000], cell[:20]


# OF's own wire (measured: onlyfans.com web app, POST /api2/v2/chats/:id/messages, 2026-11-06; OF echoed it, 200).
OF_WIRE = '<p><span class="m-editor-fs__l m-editor-fc__blue-2"><strong>safgsfg</strong></span></p>'


def case_of_wire_format_round_trips_byte_exact():
    from of_rich_text import of_plain, of_text, sanitize_of_html
    assert sanitize_of_html(OF_WIRE) == OF_WIRE
    assert of_text(OF_WIRE) == OF_WIRE
    assert of_plain(OF_WIRE) == "safgsfg"


_harness.run()
