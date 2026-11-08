#!/usr/bin/env python3
"""Growth > Scripts' Excel import and copy between Creators (service/scripts_import_api.py).

Import reads every sheet of an .xlsx in Infloww's format: the sheet name is the tag, row 1 names the `name`, `text`
and `note` columns, a blank row is skipped, a sheet over 1000 rows refuses the file, and a bad or duplicate row is a
failed row in the result, never an error. Copy moves scripts between Creators with their name, text, tags, notes and
sequence, drops media (ADR-0008), and skips a name the target already has. Both sit under /admin/saved-replies/, so
Role enforcement refuses a chatter whose role lacks Scripts, and each account goes through
`assert_account_owned`.

The seam is the Relay over HTTP with real session cookies from the shared two-Agency fixture.

Run: ./venv/bin/python service/tests/test_scripts_import.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import io  # noqa: E402
import zipfile  # noqa: E402
from xml.sax.saxutils import escape  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, SavedReply, SavedReplySequence, UserAccount  # noqa: E402
import employees  # noqa: E402
import permissions  # noqa: E402
from xlsx_io import read_xlsx  # noqa: E402

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
B = IDS["creator_b"]
OWNER_A = fx.login_owner("agency_a_owner")
MASTER = fx.login_owner("agency_master")
CHATTER_A = fx.login_chatter("chatter_a")

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _book(sheets: dict[str, list[list[str]]]) -> bytes:
    """A workbook with one sheet per entry, cells as inline strings (B2-style refs, so gaps stay gaps)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        entries = "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>'
                          for i, n in enumerate(sheets, start=1))
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{_NS}" xmlns:r="{_REL}"><sheets>{entries}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
                       f'<Relationship Id="rId{i}" Type="x" Target="worksheets/sheet{i}.xml"/>'
                       for i in range(1, len(sheets) + 1)) + "</Relationships>")
        for i, rows in enumerate(sheets.values(), start=1):
            body = "".join(
                f'<row r="{r}">' + "".join(
                    f'<c r="{chr(65 + c)}{r}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
                    for c, v in enumerate(row) if v) + "</row>"
                for r, row in enumerate(rows, start=1))
            z.writestr(f"xl/worksheets/sheet{i}.xml", f'<worksheet xmlns="{_NS}"><sheetData>{body}</sheetData></worksheet>')
    return buf.getvalue()


def _import(client, data: bytes, acc: str = A):
    return client.post(f"/admin/saved-replies/import?account_id={acc}",
                       files={"file": ("scripts.xlsx", data, "application/octet-stream")})


def _list(client, acc: str = A) -> list[dict]:
    r = client.get(f"/admin/saved-replies?account_id={acc}")
    assert r.status_code == 200, r.text
    return r.json()["list"]


def _wipe(acc: str = A) -> None:
    async def go() -> None:
        async with get_session() as s:
            await s.execute(delete(SavedReply).where(SavedReply.account_id == acc))
    asyncio.run(go())


# ── Excel import ─────────────────────────────────────────────────────

def case_each_sheet_is_a_tag_and_columns_are_read_by_header():
    _wipe()
    data = _book({
        "Openers": [["name", "text", "note"], ["hi", "hey you", "first msg"], ["", "", ""], ["ask", "how was your day?"]],
        # Header in another order and case; "Notes" is read as the note column.
        "VIP": [["Text", "Notes", "Name"], ["missed you", "whales only", "vip hello"]],
    })
    r = _import(OWNER_A, data)
    assert r.status_code == 200, r.text
    assert r.json() == {"total": 3, "success_count": 3, "fail_count": 0, "failed": []}, r.json()
    got = {x["title"]: (x["text"], x["tags"], x["notes"]) for x in _list(OWNER_A)}
    assert got == {"hi": ("hey you", ["Openers"], "first msg"), "ask": ("how was your day?", ["Openers"], None),
                   "vip hello": ("missed you", ["VIP"], "whales only")}, got


def case_a_header_naming_no_known_column_reads_a_b_c():
    _wipe()
    r = _import(OWNER_A, _book({"T": [["Script", "Message", "Comment"], ["n1", "t1", "c1"]]}))
    assert r.status_code == 200 and r.json()["success_count"] == 1, r.text
    assert [(x["title"], x["text"], x["notes"]) for x in _list(OWNER_A)] == [("n1", "t1", "c1")]


def case_bad_and_duplicate_rows_fail_with_a_reason_and_the_rest_import():
    _wipe()
    assert OWNER_A.post(f"/admin/saved-replies?account_id={A}", json={"title": "Taken", "text": "x"}).status_code == 200
    rows = [["name", "text", "note"],
            ["taken", "case-insensitive clash with an existing script"],
            ["ok", "fine"],
            ["OK", "a repeat inside the file"],
            ["", "no name"],
            ["no text", ""],
            ["n" * 65, "long name"],
            ["long text", "t" * 1001],
            ["long note", "fine", "x" * 247],
            ["edge", "t" * 1000, "x" * 246]]
    r = _import(OWNER_A, _book({"Tag": rows}))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total"], body["success_count"], body["fail_count"]) == (9, 2, 7), body
    reasons = {(f["row"], f["reason"]) for f in body["failed"]}
    assert reasons == {(2, "duplicate name"), (4, "duplicate name"), (5, "name is required"),
                       (6, "text is required"), (7, "name longer than 64 characters"),
                       (8, "text longer than 1000 characters"), (9, "note longer than 246 characters")}, reasons
    assert all(f["sheet"] == "Tag" for f in body["failed"])
    assert sorted(x["title"] for x in _list(OWNER_A)) == ["Taken", "edge", "ok"]


def case_a_markup_cell_is_sanitized_and_its_length_is_what_a_fan_reads():
    _wipe()
    rows = [["name", "text"],
            ["rich", "<p><strong onclick=x>" + "t" * 1000 + "</strong><script>y</script></p>"],
            ["rich long", "<p>" + "t" * 1001 + "</p>"],
            ["only tags", "<p><img src=x></p>"]]
    body = _import(OWNER_A, _book({"Tag": rows})).json()
    assert (body["success_count"], {(f["row"], f["reason"]) for f in body["failed"]}) == (
        1, {(3, "text longer than 1000 characters"), (4, "text is required")}), body
    assert [x["text"] for x in _list(OWNER_A)] == ["<p><strong>" + "t" * 1000 + "</strong></p>"]


def case_a_sheet_over_1000_rows_or_a_non_xlsx_or_empty_file_is_refused():
    _wipe()
    big = [["name", "text"]] + [[f"n{i}", "t"] for i in range(1001)]
    r = _import(OWNER_A, _book({"Big": big}))
    assert r.status_code == 422 and "Exceeded maximum allowed rows (1000)" in r.json()["detail"], r.text
    r = _import(OWNER_A, b"name,text\nhi,hey\n")
    assert r.status_code == 422 and "not an Excel workbook" in r.json()["detail"], r.text
    r = _import(OWNER_A, _book({"Empty": [["name", "text", "note"]]}))
    assert r.status_code == 422 and "no scripts" in r.json()["detail"], r.text
    assert _list(OWNER_A) == []
    # 1000 rows under the header is the limit, not over it.
    r = _import(OWNER_A, _book({"Full": big[:1001]}))
    assert r.status_code == 200 and r.json()["success_count"] == 1000, r.text[:200]
    _wipe()


def case_the_template_is_one_tag_sheet_with_the_header():
    r = OWNER_A.get("/admin/saved-replies/import-template")
    assert r.status_code == 200, r.text
    assert read_xlsx(r.content) == [("Tag 1", [{0: "name", 1: "text", 2: "note"}])]


def case_import_into_another_agencys_creator_is_refused():
    r = _import(OWNER_A, _book({"T": [["name", "text"], ["x", "y"]]}), acc=B)
    assert r.status_code == 403, r.text
    assert _list(MASTER, B) == []


def case_role_enforcement_maps_both_routes_to_scripts():
    assert {permissions.route_pages(f"/admin/saved-replies/{p}", "POST") for p in ("import", "copy")} == {
        ("/growth/scripts",)}
    emp = asyncio.run(employees.get_or_create_mirror_employee(
        IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))

    def roles(pages: dict) -> None:
        r = OWNER_A.put("/admin/settings/roles", json={
            "enforce": True, "assignments": {str(emp): "r"},
            "roles": [{"id": "r", "name": "Fixture", "description": "", "permissions": pages, "scope": "all"}]})
        assert r.status_code == 200, r.text

    copy = {"from_account_ids": [A], "to_account_ids": [A]}
    roles({"/dashboard": True})
    denied = {"detail": "Your role does not allow Scripts"}
    r = _import(CHATTER_A, _book({"T": [["name", "text"], ["x", "y"]]}))
    assert r.status_code == 403 and r.json() == denied, r.text
    r = CHATTER_A.post("/admin/saved-replies/copy", json=copy)
    assert r.status_code == 403 and r.json() == denied, r.text
    roles({"/growth/scripts": True})
    assert CHATTER_A.post("/admin/saved-replies/copy", json=copy).status_code == 200
    r = OWNER_A.put("/admin/settings/roles", json={"enforce": False})
    assert r.status_code == 200, r.text


# ── Copy (Share / Import from other creators) ────────────────────────

def case_copy_keeps_text_tags_notes_and_sequence_drops_media_and_skips_taken_names():
    _wipe(A)
    _wipe(B)
    mk = lambda acc, **b: MASTER.post(f"/admin/saved-replies?account_id={acc}", json={"text": "t", **b}).json()  # noqa: E731
    s1 = mk(A, title="opener", text="hey", tags=["Openers"], notes="after 9pm", script_id="Night", script_step=1)
    s2 = mk(A, title="ppv", text="look", price=10, locked_text=True, tagged_users=[5],
            media=[{"id": 77, "type": "photo"}], previews=[77])
    mk(A, title="Kept", text="only on A")
    mk(B, title="KEPT", text="B already has this name")
    # A text-only priced script (an Infloww import's) keeps its price; a Condition option keeps its condition.
    mk(A, title="if bought", text="thanks", price=7.5, conditional="if he bought", script_id="Night", script_step=2)
    r = MASTER.post("/admin/saved-replies/copy", json={"from_account_ids": [A], "to_account_ids": [B]})
    assert r.status_code == 200 and r.json() == {
        "copied": 3, "skipped": 1, "media_dropped": 1}, r.text
    got = {x["title"]: x for x in _list(MASTER, B)}
    assert set(got) == {"opener", "ppv", "KEPT", "if bought"}, got
    o = got["opener"]
    assert (o["text"], o["tags"], o["notes"], o["script_id"], o["script_step"]) == (
        "hey", ["Openers"], "after 9pm", "Night", 1), o
    p = got["ppv"]
    assert (p["media"], p["previews"], p["price"], p["locked_text"], p["tagged_users"]) == ([], [], 0, False, []), p
    c = got["if bought"]
    assert (c["price"], c["conditional"], c["script_id"], c["script_step"]) == (7.5, "if he bought", "Night", 2), c
    # Copying again skips everything; the sources are untouched.
    r = MASTER.post("/admin/saved-replies/copy", json={"from_account_ids": [A], "to_account_ids": [B]})
    assert r.json() == {"copied": 0, "skipped": 4, "media_dropped": 0}, r.text
    a = {x["id"]: x for x in _list(MASTER, A)}
    assert a[s2["id"]]["media"] == [{"id": 77, "type": "photo"}] and a[s1["id"]]["tags"] == ["Openers"]


def case_copy_with_ids_shares_only_those_scripts():
    _wipe(A)
    _wipe(B)
    one = MASTER.post(f"/admin/saved-replies?account_id={A}", json={"title": "one", "text": "1"}).json()
    MASTER.post(f"/admin/saved-replies?account_id={A}", json={"title": "two", "text": "2"})
    # Past SQLite's bound-variable cap of old builds (999): read in chunks; past the cap, 422.
    r = MASTER.post("/admin/saved-replies/copy",
                    json={"from_account_ids": [A], "to_account_ids": [B],
                          "ids": [one["id"], *range(10**9, 10**9 + 1500)]})
    assert r.json()["copied"] == 1, r.text
    assert [x["title"] for x in _list(MASTER, B)] == ["one"]
    r = MASTER.post("/admin/saved-replies/copy",
                    json={"from_account_ids": [A], "to_account_ids": [B], "ids": list(range(20_001))})
    assert r.status_code == 422, r.text


def case_copy_refuses_an_account_the_caller_does_not_hold_and_bad_bodies():
    r = OWNER_A.post("/admin/saved-replies/copy", json={"from_account_ids": [A], "to_account_ids": [B]})
    assert r.status_code == 403, r.text
    r = OWNER_A.post("/admin/saved-replies/copy", json={"from_account_ids": [B], "to_account_ids": [A]})
    assert r.status_code == 403, r.text
    r = OWNER_A.post("/admin/saved-replies/copy", json={"from_account_ids": [], "to_account_ids": [A]})
    assert r.status_code == 422, r.text
    r = OWNER_A.post("/admin/saved-replies/copy", json={"from_account_ids": [A] * 6, "to_account_ids": [A]})
    assert r.status_code == 422, r.text
    assert [x["title"] for x in _list(MASTER, B)] == ["one"]  # the previous case's copy, nothing new
    r = OWNER_A.post("/admin/saved-replies/copy", json={"from_account_ids": [A], "to_account_ids": [""]})
    assert r.status_code == 422, r.text
    # Share to all creators names no targets of its own: both at once is refused, never one silently winning.
    r = OWNER_A.post("/admin/saved-replies/copy",
                     json={"from_account_ids": [A], "to_account_ids": [A], "all_creators": True})
    assert r.status_code == 422, r.text


def _creator_c() -> str:
    """A third Creator the Master holds, so two sources can feed one target."""
    c = "1000003"
    (fx.account_registry.ACCOUNTS_DIR / c).mkdir(exist_ok=True)

    async def seed() -> None:
        async with get_session() as s:
            if await s.get(Account, c) is None:
                s.add(Account(id=c, nickname="creator_c", color="#aaaaaa"))
    asyncio.run(seed())
    return c


def _copy(src: list[str], dst: list[str], ids: list[int] | None = None) -> dict:
    r = MASTER.post("/admin/saved-replies/copy", json={"from_account_ids": src, "to_account_ids": dst, "ids": ids})
    assert r.status_code == 200, r.text
    return r.json()


def _rows(acc: str) -> list[tuple]:
    return sorted((x["script_id"] or "", x["script_step"] or 0, x["title"]) for x in _list(MASTER, acc))


def case_a_sequence_is_copied_whole_or_skipped_whole():
    """A sequence arrives whole, "N.M" options included; one whose name the target already uses is skipped whole
    (the target's partial one stays as it has it). Two sources sharing a sequence name: the first picked brings it,
    the other's is skipped, so a later share of the other adds nothing. Same-named scripts in two sequences both
    land; a loose script still skips a name the target has."""
    c = _creator_c()
    for acc in (A, B, c):
        _wipe(acc)
    mk = lambda acc, title, step, seq="Night", text=None: MASTER.post(  # noqa: E731
        f"/admin/saved-replies?account_id={acc}",
        json={"title": title, "text": text or title, "script_id": seq, "script_step": step})
    assert mk(A, "a1", 1).status_code == 200
    mk(A, "a2.1", 2)
    mk(A, "a2.2", 2)                          # step 2's second option
    mk(A, "hi", 1, seq="Day")                 # the same name in another sequence
    mk(A, "hi", 1, seq="Eve", text="hi eve")
    mk(B, "b1", 1)
    mk(B, "b3", 3)
    mk(c, "c2 renamed", 2)                    # c's own, partial Night: stays as c has it
    assert _copy([A, B], [c]) == {"copied": 2, "skipped": 5, "media_dropped": 0}
    assert _rows(c) == [("Day", 1, "hi"), ("Eve", 1, "hi"), ("Night", 2, "c2 renamed")], _rows(c)
    _wipe(c)
    assert _copy([A, B], [c]) == {"copied": 5, "skipped": 2, "media_dropped": 0}
    whole_a = [("Day", 1, "hi"), ("Eve", 1, "hi"), ("Night", 1, "a1"), ("Night", 2, "a2.1"), ("Night", 2, "a2.2")]
    assert _rows(c) == whole_a, _rows(c)
    # [A, B] then B: B's Night is skipped whole, never landing loose or beside A's.
    assert _copy([B], [c]) == {"copied": 0, "skipped": 2, "media_dropped": 0}
    assert _copy([A, B], [c]) == {"copied": 0, "skipped": 7, "media_dropped": 0}
    assert _rows(c) == whole_a, _rows(c)
    # The pick order decides: B first brings B's Night.
    _wipe(c)
    assert _copy([B, A], [c]) == {"copied": 4, "skipped": 3, "media_dropped": 0}
    assert _rows(c) == [("Day", 1, "hi"), ("Eve", 1, "hi"), ("Night", 1, "b1"), ("Night", 3, "b3")], _rows(c)
    # A loose script skips a name the target has, a step's included.
    _wipe(B)
    MASTER.post(f"/admin/saved-replies?account_id={B}", json={"title": "B1", "text": "loose"})
    assert _copy([B], [c]) == {"copied": 0, "skipped": 1, "media_dropped": 0}
    for acc in (A, B, c):
        _wipe(acc)


def case_a_tag_share_brings_each_of_its_sequences_whole():
    """A tag share selects a sequence's tagged steps only; the copy brings that whole sequence (every step and
    option, in step order), so a later share of the sequence adds nothing, and the target's own edits and deletions
    afterwards survive every re-share."""
    for acc in (A, B):
        _wipe(acc)
    mk = lambda title, step=None, seq="Night", tags=(): MASTER.post(  # noqa: E731
        f"/admin/saved-replies?account_id={A}",
        json={"title": title, "text": title, "script_id": seq if step else None, "script_step": step,
              "tags": list(tags)}).json()
    mk("n3", 3)                               # made first: the copy still inserts in step order
    mk("n2.1", 2)
    n1 = mk("n1", 1, tags=["VIP"])
    mk("n2.2", 2)
    promo = mk("promo", tags=["VIP"])
    # The VIP tag's share: its scripts' ids (as the page's `entryIds`).
    assert _copy([A], [B], ids=[n1["id"], promo["id"]]) == {"copied": 5, "skipped": 0, "media_dropped": 0}
    night = sorted((x["id"], x["title"]) for x in _list(MASTER, B) if x["script_id"] == "Night")
    assert [t for _, t in night] == ["n1", "n2.1", "n2.2", "n3"], night
    assert _copy([A], [B]) == {"copied": 0, "skipped": 5, "media_dropped": 0}
    # B renames its step 1 and deletes step 3: its own edits win over the source's.
    by_title = {x["title"]: x["id"] for x in _list(MASTER, B)}

    async def edit() -> None:
        async with get_session() as s:
            (await s.get(SavedReply, by_title["n1"])).title = "n1 mine"
            await s.delete(await s.get(SavedReply, by_title["n3"]))
    asyncio.run(edit())
    for ids in (None, [n1["id"]]):
        assert _copy([A], [B], ids=ids)["copied"] == 0
    assert _rows(B) == [("", 0, "promo"), ("Night", 1, "n1 mine"), ("Night", 2, "n2.1"), ("Night", 2, "n2.2")]
    for acc in (A, B):
        _wipe(acc)


def case_identical_copies_at_once_land_each_script_once():
    """Two identical shares at once (a double click, two tabs): one copy into a Creator at a time, so the later sees
    the earlier's rows: no duplicate script, no 500 on the sequence header's unique (account_id, name)."""
    import httpx
    import server
    for acc in (A, B):
        _wipe(acc)

    async def seed() -> None:
        async with get_session() as s:
            await s.execute(delete(SavedReplySequence).where(SavedReplySequence.account_id.in_([A, B])))
            s.add(SavedReplySequence(account_id=A, name="Race", position=1))
            for i in range(100):
                s.add(SavedReply(account_id=A, title=f"loose {i}", text=f"l{i}"))
                s.add(SavedReply(account_id=A, title=f"r{i}", text=f"r{i}", script_id="Race", script_step=i + 1))
    asyncio.run(seed())
    body = {"from_account_ids": [A], "to_account_ids": [B]}

    async def race():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://testserver",
                                     cookies=dict(MASTER.cookies)) as cl:
            return await asyncio.gather(*(cl.post("/admin/saved-replies/copy", json=body) for _ in range(4)))

    got = asyncio.run(race())
    assert [r.status_code for r in got] == [200] * 4, [r.text[:200] for r in got]
    assert sorted(r.json()["copied"] for r in got) == [0, 0, 0, 200], [r.json() for r in got]
    assert len(_list(MASTER, B)) == 200 and list(_seq_metas(MASTER, B)) == ["Race"]
    for acc in (A, B):
        _wipe(acc)


# ── Share to all creators + sequence meta + all-models overview ──────

def _mk_creator(aid: str, owner_user: str) -> None:
    """A fresh owned Creator (registry meta + Account row + user_accounts link) so the
    principal's roster (`owned_account_ids`) picks it up."""
    fx.account_registry.upsert_account(aid, nickname=f"creator_{aid}", color="#aaaaaa")

    async def go() -> None:
        async with get_session() as s:
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid, nickname=f"creator_{aid}", color="#aaaaaa"))
            if (await s.execute(select(UserAccount).where(
                    UserAccount.user_id == IDS[owner_user], UserAccount.account_id == aid))
                ).scalar_one_or_none() is None:
                s.add(UserAccount(user_id=IDS[owner_user], account_id=aid))
    asyncio.run(go())


def _seq_metas(client, acc: str) -> dict[str, dict]:
    r = client.get(f"/admin/saved-replies/sequences?account_id={acc}")
    assert r.status_code == 200, r.text
    return {m["name"]: m for m in r.json()["list"]}


def case_share_to_all_resolves_the_owned_roster_and_carries_sequence_meta():
    """`all_creators` resolves the targets to the principal's full owned roster server-side
    (no `to_account_ids` needed), copies price/media-free, carries the sequence header, and a
    re-share adds 0 rows (the no-dup proof). Sequence meta is idempotent on (account_id, name)."""
    src, d1, d2 = "1000010", "1000011", "1000012"
    for aid in (src, d1, d2):
        _mk_creator(aid, "agency_a_owner")

    async def seed() -> None:
        async with get_session() as s:
            for aid in (src, d1, d2):
                await s.execute(delete(SavedReply).where(SavedReply.account_id == aid))
                await s.execute(delete(SavedReplySequence).where(SavedReplySequence.account_id == aid))
            s.add(SavedReplySequence(account_id=src, name="NightD", position=3,
                                     created_by="07", description="warm-up"))
            s.add(SavedReply(account_id=src, title="n1", text="hey", script_id="NightD",
                             script_step=1, tags_json='["Openers"]'))
            s.add(SavedReply(account_id=src, title="n2", text="then", script_id="NightD",
                             script_step=2, media_json='[{"id": 9, "type": "photo"}]', price_cents=500))
    asyncio.run(seed())

    r = OWNER_A.post("/admin/saved-replies/copy",
                     json={"from_account_ids": [src], "all_creators": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"copied", "skipped", "media_dropped"}, body
    # The source is no target: none of its own rows counts as skipped.
    assert body["skipped"] == 0, body
    # Every other creator got both scripts, media/price dropped, the sequence header carried.
    for dst in (d1, d2):
        got = {x["title"]: x for x in _list(OWNER_A, dst)}
        assert set(got) == {"n1", "n2"}, (dst, got)
        assert (got["n1"]["script_id"], got["n1"]["script_step"], got["n1"]["tags"]) == ("NightD", 1, ["Openers"])
        assert (got["n2"]["media"], got["n2"]["price"]) == ([], 0), got["n2"]
        meta = _seq_metas(OWNER_A, dst).get("NightD")
        assert meta and (meta["position"], meta["created_by"], meta["description"]) == (3, "07", "warm-up"), meta
    # Re-share: 0 rows added (true no-op), and no duplicate meta row.
    r2 = OWNER_A.post("/admin/saved-replies/copy",
                      json={"from_account_ids": [src], "all_creators": True})
    assert r2.status_code == 200 and r2.json()["copied"] == 0, r2.text
    for dst in (d1, d2):
        assert len(_list(OWNER_A, dst)) == 2
        assert list(_seq_metas(OWNER_A, dst)) == ["NightD"]


def case_overview_lists_each_sequence_and_tag_per_account():
    """GET /admin/saved-replies/overview: a lean matrix of sequence step counts and tag
    script counts per owned Creator (no bodies). Only the principal's creators appear."""
    src, d1, d2 = "1000010", "1000011", "1000012"
    for aid in (src, d1, d2):
        _mk_creator(aid, "agency_a_owner")

    async def seed() -> None:
        async with get_session() as s:
            for aid in (src, d1, d2):
                await s.execute(delete(SavedReply).where(SavedReply.account_id == aid))
                await s.execute(delete(SavedReplySequence).where(SavedReplySequence.account_id == aid))
            # d1: SeqX (2 steps), one tagged VIP; a loose VIP script.
            s.add(SavedReply(account_id=d1, title="x1", text="a", script_id="SeqX", script_step=1,
                             tags_json='["VIP"]'))
            s.add(SavedReply(account_id=d1, title="x2", text="b", script_id="SeqX", script_step=2))
            # d2: SeqX (1 step); two loose VIP scripts.
            s.add(SavedReply(account_id=d2, title="y1", text="c", script_id="SeqX", script_step=1))
            s.add(SavedReply(account_id=d2, title="v1", text="d", tags_json='["VIP"]'))
            s.add(SavedReply(account_id=d2, title="v2", text="e", tags_json='["VIP"]'))
    asyncio.run(seed())

    r = OWNER_A.get("/admin/saved-replies/overview")
    assert r.status_code == 200, r.text
    ov = r.json()
    acc_ids = {a["id"] for a in ov["accounts"]}
    assert {src, d1, d2} <= acc_ids and B not in acc_ids, acc_ids
    seqx = next(s for s in ov["sequences"] if s["name"] == "SeqX")
    assert seqx["per_account"] == {d1: 2, d2: 1}, seqx
    vip = next(t for t in ov["tags"] if t["name"] == "VIP")
    assert vip["per_account"] == {d1: 1, d2: 2}, vip


# ── The xlsx reader ──────────────────────────────────────────────────

def _raw_sheet(cells: str) -> bytes:
    """A one-sheet workbook whose single row holds `cells` verbatim (refs written by hand)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml",
                   f'<workbook xmlns="{_NS}" xmlns:r="{_REL}"><sheets><sheet name="T" sheetId="1" r:id="rId1"/>'
                   f'<sheet name="Second" sheetId="2" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml",
                   f'<worksheet xmlns="{_NS}"><sheetData><row r="1">{cells}</row></sheetData></worksheet>')
    return buf.getvalue()


def case_a_far_cell_ref_costs_one_entry_and_past_xfd_is_ignored():
    def cell(ref: str, v: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
    data = _raw_sheet(cell("A1", "name") + cell("XFD1", "last") + cell("XFE1", "past")
                      + cell("ZZZZZZZZZ1", "huge") + "".join(cell(f"ZZZ{i}", "z") for i in range(1, 50)))
    sheets = read_xlsx(data)
    assert [n for n, _ in sheets] == ["T", "Second"]
    assert sheets[0][1] == [{0: "name", 16383: "last"}], sheets[0][1]
    assert [n for n, _ in read_xlsx(data, first_only=True)] == ["T"]
    from sensitive_words_api import read_xlsx_first_column
    assert read_xlsx_first_column(data) == ["name"]
    # Through the import: the far cells cost nothing and the header row still reads.
    r = _import(OWNER_A, data)
    assert r.status_code == 422 and "no scripts" in r.json()["detail"], r.text


def case_a_zip_bomb_is_refused_by_total_size_and_sheet_count():
    """R8: one small sheet part listed as many sheets is read once per listing."""
    import xlsx_io

    def listed(times: int) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            entries = "".join(f'<sheet name="S{i}" sheetId="{i}" r:id="rId1"/>' for i in range(1, times + 1))
            z.writestr("xl/workbook.xml", f'<workbook xmlns="{_NS}" xmlns:r="{_REL}"><sheets>{entries}</sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels",
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{_NS}"><sheetData>'
                       + "<row/>" * (xlsx_io._MAX_PART // 7) + "</sheetData></worksheet>")
        return buf.getvalue()

    data = listed(3)
    assert len(data) < 1024 * 1024, len(data)
    for bomb, why in ((data, "too large"), (listed(xlsx_io.MAX_SHEETS + 1), "more than")):
        try:
            read_xlsx(bomb)
            raise AssertionError("read")
        except ValueError as e:
            assert why in str(e), e
    assert [n for n, _ in read_xlsx(data, first_only=True)] == ["S1"]


_harness.run()
