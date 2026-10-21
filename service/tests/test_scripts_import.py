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

from sqlalchemy import delete  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, SavedReply  # noqa: E402
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
    r = MASTER.post("/admin/saved-replies/copy", json={"from_account_ids": [A], "to_account_ids": [B]})
    assert r.status_code == 200 and r.json() == {
        "copied": 2, "skipped": 1, "media_dropped": 1, "sequence_dropped": 0}, r.text
    got = {x["title"]: x for x in _list(MASTER, B)}
    assert set(got) == {"opener", "ppv", "KEPT"}, got
    o = got["opener"]
    assert (o["text"], o["tags"], o["notes"], o["script_id"], o["script_step"]) == (
        "hey", ["Openers"], "after 9pm", "Night", 1), o
    p = got["ppv"]
    assert (p["media"], p["previews"], p["price"], p["locked_text"], p["tagged_users"]) == ([], [], 0, False, []), p
    # Copying again skips everything; the sources are untouched.
    r = MASTER.post("/admin/saved-replies/copy", json={"from_account_ids": [A], "to_account_ids": [B]})
    assert r.json() == {"copied": 0, "skipped": 3, "media_dropped": 0, "sequence_dropped": 0}, r.text
    a = {x["id"]: x for x in _list(MASTER, A)}
    assert a[s2["id"]]["media"] == [{"id": 77, "type": "photo"}] and a[s1["id"]]["tags"] == ["Openers"]


def case_copy_with_ids_shares_only_those_scripts():
    _wipe(A)
    _wipe(B)
    one = MASTER.post(f"/admin/saved-replies?account_id={A}", json={"title": "one", "text": "1"}).json()
    MASTER.post(f"/admin/saved-replies?account_id={A}", json={"title": "two", "text": "2"})
    r = MASTER.post("/admin/saved-replies/copy",
                    json={"from_account_ids": [A], "to_account_ids": [B], "ids": [one["id"]]})
    assert r.json()["copied"] == 1, r.text
    assert [x["title"] for x in _list(MASTER, B)] == ["one"]


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


def case_copy_never_puts_two_scripts_at_one_sequence_step():
    """Sources sharing a sequence name with each other, or with the target, would land two scripts on one step:
    the later one arrives outside any sequence and is counted."""
    c = "1000003"  # a third Creator the Master holds, so two sources can feed one target
    (fx.account_registry.ACCOUNTS_DIR / c).mkdir(exist_ok=True)

    async def seed() -> None:
        async with get_session() as s:
            if await s.get(Account, c) is None:
                s.add(Account(id=c, nickname="creator_c", color="#aaaaaa"))
    asyncio.run(seed())
    for acc in (A, B, c):
        _wipe(acc)
    mk = lambda acc, title, step: MASTER.post(  # noqa: E731
        f"/admin/saved-replies?account_id={acc}",
        json={"title": title, "text": title, "script_id": "Night", "script_step": step})
    assert mk(A, "a1", 1).status_code == 200
    mk(A, "a2", 2)
    mk(B, "b1", 1)
    mk(B, "b3", 3)
    mk(c, "c2", 2)
    r = MASTER.post("/admin/saved-replies/copy", json={"from_account_ids": [A, B], "to_account_ids": [c]})
    assert r.status_code == 200 and r.json() == {
        "copied": 4, "skipped": 0, "media_dropped": 0, "sequence_dropped": 2}, r.text
    got = {x["title"]: (x["script_id"], x["script_step"]) for x in _list(MASTER, c)}
    assert got == {"c2": ("Night", 2), "a1": ("Night", 1), "a2": (None, None),
                   "b1": (None, None), "b3": ("Night", 3)}, got
    for acc in (A, B, c):
        _wipe(acc)


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
