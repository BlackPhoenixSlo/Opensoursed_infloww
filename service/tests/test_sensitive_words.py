#!/usr/bin/env python3
"""Growth > Sensitive words on the Relay (service/sensitive_words_api.py).

One list per Agency, as Infloww keeps it. `GET /admin/sensitive-words` is the read every composer makes, a
chatter's too (the union of its Agencies' lists when it names no Creator); everything under
`/admin/sensitive-words/` (add, update, delete, export, template, import) is owner session or Master: 401 signed
out, 403 for a chatter. A word is trimmed, inner whitespace collapsed, 1 to 32 characters, and held once whatever
its case: a repeat is a failed row in the import result, never an error. Excel import reads column A of the first
sheet under a header row; export writes the list back the same way.

The seam is the Relay over HTTP with real session cookies from the shared two-Agency fixture.

Run: ./venv/bin/python service/tests/test_sensitive_words.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import io  # noqa: E402
import zipfile  # noqa: E402

from sqlalchemy import delete, func, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import SensitiveWord  # noqa: E402
from sensitive_words_api import read_xlsx_first_column, write_column  # noqa: E402

ROUTE = "/admin/sensitive-words"
IDS = fx.seed_two_agencies()
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
ANON = _harness.make_client()


def _reset() -> None:
    async def go() -> None:
        async with get_session() as s:
            await s.execute(delete(SensitiveWord))
    asyncio.run(go())


def _count() -> int:
    async def go() -> int:
        async with get_session() as s:
            return (await s.execute(select(func.count()).select_from(SensitiveWord))).scalar_one()
    return asyncio.run(go())


def _words(client, **params) -> list[str]:
    r = client.get(ROUTE, params=params)
    assert r.status_code == 200, f"list: {r.status_code} {r.text}"
    return r.json()["words"]


def _add(client, words, status: int = 200) -> dict:
    r = client.post(f"{ROUTE}/add", json={"words": words})
    assert r.status_code == status, f"add {words}: {r.status_code} {r.text}"
    return r.json()


def _xlsx_upload(client, data: bytes):
    return client.post(f"{ROUTE}/import", files={"file": ("words.xlsx", data, "application/octet-stream")})


def _writes(client) -> list:
    return [
        ("add", client.post(f"{ROUTE}/add", json={"words": ["fixture"]})),
        ("update", client.post(f"{ROUTE}/update", json={"old": "a", "latest": "b"})),
        ("delete", client.post(f"{ROUTE}/delete", json={"words": ["a"]})),
        ("export", client.get(f"{ROUTE}/export")),
        ("template", client.get(f"{ROUTE}/template")),
        ("import", _xlsx_upload(client, write_column(["Sensitive Words", "fixture"]))),
    ]


# ── Sessions ─────────────────────────────────────────────────────────

def case_signed_out_is_401_on_the_read_and_every_write():
    _reset()
    assert ANON.get(ROUTE).status_code == 401
    for label, r in _writes(ANON):
        assert r.status_code == 401, f"{label} signed out: {r.status_code} {r.text}"
    assert _count() == 0


def case_a_chatter_reads_its_agencys_list_but_every_write_is_403():
    _reset()
    _add(OWNER_A, ["fixture alpha"])
    _add(OWNER_B, ["fixture beta"])
    assert _words(fx.login_chatter("chatter_a")) == ["fixture alpha"]
    assert _words(fx.login_chatter("chatter_b")) == ["fixture beta"]
    both = fx.login_chatter("chatter_ab")
    assert _words(both) == ["fixture alpha", "fixture beta"], "no Creator named: the union"
    assert _words(both, account_id=IDS["creator_b"]) == ["fixture beta"], "a Creator names its Agency"
    for name in ("chatter_a", "chatter_ab"):
        for label, r in _writes(fx.login_chatter(name)):
            assert r.status_code == 403, f"{label} as {name}: {r.status_code} {r.text}"
    assert _count() == 2


def case_another_agencys_list_is_invisible_and_untouched():
    _reset()
    _add(OWNER_A, ["fixture mine"])
    assert _words(OWNER_B) == []
    r = OWNER_B.post(f"{ROUTE}/delete", json={"words": ["fixture mine"]})
    assert r.status_code == 200 and r.json() == {"deleted": 0}, r.text
    r = OWNER_B.post(f"{ROUTE}/update", json={"old": "fixture mine", "latest": "x"})
    assert r.status_code == 404, r.text
    assert _words(OWNER_A) == ["fixture mine"]


# ── Add, update, delete ──────────────────────────────────────────────

def case_add_trims_holds_each_word_once_in_any_case_and_reports_each_failure():
    _reset()
    result = _add(OWNER_A, ["  Venmo  ", "cash  app", "VENMO", "", "x" * 33, "x" * 32])
    assert result["total"] == 6 and result["success_count"] == 3 and result["fail_count"] == 3, result
    assert result["failed"] == [
        {"word": "VENMO", "reason": "already in the list"},
        {"word": "", "reason": "empty"},
        {"word": "x" * 33, "reason": "longer than 32 characters"},
    ], result["failed"]
    assert _words(OWNER_A) == ["cash app", "Venmo", "x" * 32], "sorted A-Z ignoring case"
    again = _add(OWNER_A, ["venmo"])
    assert again["success_count"] == 0 and again["failed"][0]["reason"] == "already in the list", again
    _add(OWNER_A, [], status=422)
    assert OWNER_A.post(f"{ROUTE}/add", json={"words": "venmo"}).status_code == 422


def case_update_renames_a_word_and_refuses_a_clash_or_a_bad_word():
    _reset()
    _add(OWNER_A, ["paypal", "venmo"])
    r = OWNER_A.post(f"{ROUTE}/update", json={"old": "PAYPAL", "latest": " PayPal "})
    assert r.status_code == 200 and r.json() == {"word": "PayPal"}, "a case-only edit is no clash"
    assert OWNER_A.post(f"{ROUTE}/update", json={"old": "paypal", "latest": "Venmo"}).status_code == 409
    assert OWNER_A.post(f"{ROUTE}/update", json={"old": "paypal", "latest": ""}).status_code == 422
    assert OWNER_A.post(f"{ROUTE}/update", json={"old": "paypal", "latest": "y" * 33}).status_code == 422
    assert OWNER_A.post(f"{ROUTE}/update", json={"old": "nope", "latest": "z"}).status_code == 404
    assert _words(OWNER_A) == ["PayPal", "venmo"]


def case_delete_removes_the_named_words_in_any_case():
    _reset()
    _add(OWNER_A, ["paypal", "venmo", "cash app"])
    r = OWNER_A.post(f"{ROUTE}/delete", json={"words": ["PAYPAL", "cash  app", "missing"]})
    assert r.status_code == 200 and r.json() == {"deleted": 2}, r.text
    assert _words(OWNER_A) == ["venmo"]


# ── Excel ────────────────────────────────────────────────────────────

def case_export_and_template_are_xlsx_with_the_header_row():
    _reset()
    _add(OWNER_A, ["venmo", "Cash App"])
    r = OWNER_A.get(f"{ROUTE}/export")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"], r.headers
    assert 'filename="Sensitive Words.xlsx"' in r.headers["content-disposition"]
    assert read_xlsx_first_column(r.content) == ["Sensitive Words", "Cash App", "venmo"]
    t = OWNER_A.get(f"{ROUTE}/template")
    assert t.status_code == 200 and read_xlsx_first_column(t.content) == ["Sensitive Words"]


def case_import_adds_column_a_under_the_header_and_reports_the_counts():
    _reset()
    _add(OWNER_A, ["venmo"])
    r = _xlsx_upload(OWNER_A, write_column(["Sensitive Words", "paypal", "", "Venmo", "z" * 40, "onlyfans.com"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total"], body["success_count"], body["fail_count"]) == (4, 2, 2), body
    assert _words(OWNER_A) == ["onlyfans.com", "paypal", "venmo"]


def case_import_reads_shared_strings_as_excel_saves_them():
    _reset()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>'
                                      f'<sheet name="S" sheetId="1" r:id="rId7"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId7" Type="x" Target="worksheets/sheet9.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}"><si><t>Sensitive Words</t></si>'
                                           f'<si><r><t>tel</t></r><r><t>egram</t></r></si></sst>')
        z.writestr("xl/worksheets/sheet9.xml", f'<worksheet xmlns="{ns}"><sheetData>'
                                               f'<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
                                               f'<row r="2"><c r="B2" t="s"><v>0</v></c><c r="A2" t="s"><v>1</v></c></row>'
                                               f'<row r="3"><c r="A3"><v>12345</v></c></row>'
                                               f'</sheetData></worksheet>')
    r = _xlsx_upload(OWNER_A, buf.getvalue())
    assert r.status_code == 200 and r.json()["success_count"] == 2, r.text
    assert _words(OWNER_A) == ["12345", "telegram"]


def case_import_refuses_a_file_that_is_not_xlsx_or_holds_no_words():
    _reset()
    r = _xlsx_upload(OWNER_A, b"word\nvenmo\n")
    assert r.status_code == 422 and "not an Excel workbook" in r.json()["detail"], r.text
    r = _xlsx_upload(OWNER_A, write_column(["Sensitive Words"]))
    assert r.status_code == 422 and "no sensitive words" in r.json()["detail"], r.text
    assert _count() == 0


_harness.run()
