#!/usr/bin/env python3
"""The reports' exports (roadmap W5 5.9): CSV formula escaping and the Excel export.

Every server CSV streams through `csv_export.stream_csv`, which writes each cell through `safe_cell`: a string a
spreadsheet would run as a formula (starting =, +, -, @, tab or carriage return) gets a leading quote, so it opens
as text; a number, a string that is a plain number ("-12.50") and a lone "-" are left alone.
`POST /admin/stats/xlsx` writes the rows Creator reports and Employee reports send as a one-sheet .xlsx
(`xlsx_io.write_xlsx`, number cells for numbers, XML-illegal characters dropped, an int past a double's exact range
as text), reading nothing, refusing a row wider than Excel's or too many cells; it is behind the reports' page grant and the "export" Function permission
(test_role_enforcement.py).

The seam is `stream_csv` itself, and the Relay over HTTP with real session cookies from the shared two-Agency
fixture.

Run: ./venv/bin/python service/tests/test_report_export.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import csv  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import zipfile  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import csv_export  # noqa: E402
import stats  # noqa: E402
import xlsx_io  # noqa: E402
from xlsx_io import read_xlsx  # noqa: E402

ROUTE = "/admin/stats/xlsx"
IDS = fx.seed_two_agencies()
OWNER_A = fx.login_owner("agency_a_owner")
ANON = _harness.make_client()


def _csv(rows, header=("a", "b")) -> list[list[str]]:
    async def gen():
        for r in rows:
            yield r

    async def go() -> bytes:
        return b"".join([c async for c in csv_export.stream_csv(gen(), header, lambda r: r)])
    return list(csv.reader(io.StringIO(asyncio.run(go()).decode())))


def case_a_formula_like_string_opens_as_text():
    out = _csv([["=HYPERLINK(\"http://x\")", "+1+cmd"], ["-2+3", "@SUM(A1)"], ["\tx", "\rx"]])
    assert out[1:] == [["'=HYPERLINK(\"http://x\")", "'+1+cmd"], ["'-2+3", "'@SUM(A1)"], ["'\tx", "'\rx"]], out


def case_numbers_plain_number_strings_and_a_lone_dash_stay_as_they_are():
    out = _csv([[-5, -12.5], ["-12.50", "+3"], ["12", ""], [None, "a-b"], ["-", "--"]])
    assert out[1:] == [["-5", "-12.5"], ["-12.50", "+3"], ["12", ""], ["", "a-b"], ["-", "'--"]], out


def case_the_header_and_the_truncated_line_go_through_the_same_escape():
    cap = csv_export.CSV_MAX_ROWS
    csv_export.CSV_MAX_ROWS = 1
    try:
        out = _csv([["x", "y"], ["z", "w"]], header=("=h", "b"))
    finally:
        csv_export.CSV_MAX_ROWS = cap
    assert out == [["'=h", "b"], ["x", "y"], [csv_export.TRUNCATED_LINE, ""]], out


def case_xlsx_writes_the_rows_sent_with_numbers_as_number_cells():
    r = OWNER_A.post(ROUTE, json={"sheet": "Creator reports", "rows": [
        ["Creator", "Total earnings"], ["=Ann", 12.5], ["Bo", -3], ["", None]]})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml"), r.headers
    [(name, rows)] = read_xlsx(r.content)
    assert name == "Creator reports"
    assert [[row.get(0), row.get(1)] for row in rows] == [
        ["Creator", "Total earnings"], ["=Ann", "12.5"], ["Bo", "-3"], ["", ""]], rows
    sheet = zipfile.ZipFile(io.BytesIO(r.content)).read("xl/worksheets/sheet1.xml").decode()
    # A number is a number cell; a formula-like string an inline string, which Excel never runs.
    assert '<c r="B2"><v>12.5</v></c>' in sheet and '<c r="B3"><v>-3</v></c>' in sheet, sheet
    assert '<c r="A2" t="inlineStr">' in sheet and "<f>" not in sheet, sheet


def case_xlsx_cleans_the_sheet_name_and_caps_the_rows():
    r = OWNER_A.post(ROUTE, json={"sheet": "a/b:c*d?[e]\\f" + "x" * 40, "rows": [["1"]]})
    assert r.status_code == 200, r.text
    [(name, _)] = read_xlsx(r.content)
    assert name == "a b c d  e  f" + "x" * 18, name
    r = OWNER_A.post(ROUTE, json={"sheet": "", "rows": []})
    assert read_xlsx(r.content)[0][0] == "Report"
    cap = csv_export.CSV_MAX_ROWS
    csv_export.CSV_MAX_ROWS = 2
    try:
        r = OWNER_A.post(ROUTE, json={"rows": [["a"], ["b"], ["c"]]})
    finally:
        csv_export.CSV_MAX_ROWS = cap
    assert r.status_code == 413, r.text


def case_a_non_ascii_digit_string_is_not_a_plain_number():
    out = _csv([["-١٢", "+٣"]])  # Arabic-Indic digits: not a number to a spreadsheet, so escaped as the app does
    assert out[1:] == [["'-١٢", "'+٣"]], out


def case_xlsx_drops_xml_illegal_characters_from_cells_and_the_sheet_name():
    # Sent as JSON escapes, the only way a lone surrogate travels.
    body = json.dumps({"sheet": "Re\x01port\ud800", "rows": [["a\x00b\x1fc", "x\ud800y\udfffz", "t\tn\nr"]]})
    r = OWNER_A.post(ROUTE, content=body, headers={"content-type": "application/json"})
    assert r.status_code == 200, r.text
    [(name, rows)] = read_xlsx(r.content)
    assert name == "Report", name
    assert [rows[0].get(i) for i in range(3)] == ["abc", "xyz", "t\tn\nr"], rows


def case_xlsx_writes_a_huge_int_as_its_digits():
    big, top = 10 ** 400, 2 ** 53
    r = OWNER_A.post(ROUTE, json={"rows": [[big, top, top + 1]]})
    assert r.status_code == 200, r.text
    [(_, rows)] = read_xlsx(r.content)
    assert [rows[0].get(i) for i in range(3)] == [str(big), str(top), str(top + 1)], rows
    sheet = zipfile.ZipFile(io.BytesIO(r.content)).read("xl/worksheets/sheet1.xml").decode()
    # Within a double's exact range a number cell; past it text, digit for digit.
    assert f'<c r="B1"><v>{top}</v></c>' in sheet and '<c r="C1" t="inlineStr">' in sheet, sheet


def case_xlsx_refuses_an_over_wide_row_and_too_many_cells():
    r = OWNER_A.post(ROUTE, json={"rows": [[""] * (xlsx_io.MAX_COLS + 1)]})
    assert r.status_code == 413, r.text
    assert OWNER_A.post(ROUTE, json={"rows": [[""] * xlsx_io.MAX_COLS]}).status_code == 200
    cap = stats.XLSX_MAX_CELLS
    stats.XLSX_MAX_CELLS = 5
    try:
        assert OWNER_A.post(ROUTE, json={"rows": [["a", "b", "c"], ["d", "e"]]}).status_code == 200
        r = OWNER_A.post(ROUTE, json={"rows": [["a", "b", "c"], ["d", "e", "f"]]})
    finally:
        stats.XLSX_MAX_CELLS = cap
    assert r.status_code == 413, r.text


def case_xlsx_refuses_a_bad_body_and_the_signed_out():
    assert OWNER_A.post(ROUTE, json={"rows": [[{"a": 1}]]}).status_code == 422
    assert OWNER_A.post(ROUTE, json={"rows": "x"}).status_code == 422
    assert ANON.post(ROUTE, json={"rows": []}).status_code == 401


_harness.run()
