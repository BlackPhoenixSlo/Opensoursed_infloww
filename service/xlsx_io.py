"""service/xlsx_io.py — read and write .xlsx with the standard library only.

  read_xlsx(data, first_only=False)
                             → [(sheet name, rows)], every sheet in workbook order
                               (only the first with `first_only`); a row is a
                               sparse {column index (A = 0): text}, so a far
                               cell ref costs one entry, and a ref past Excel's
                               last column (XFD) is ignored. ValueError when
                               `data` is not an .xlsx, or unpacks past the
                               size or sheet caps (a zip bomb).
  write_xlsx(rows, sheet)    → a one-sheet workbook of `rows`: a number is a
                               number cell, anything else an inline string
                               (XML-illegal characters dropped); the sheet
                               name is cleaned to what Excel takes.

Shared by Growth > Sensitive words (column A of the first sheet), the Scripts
Excel import (every sheet, columns by header) and the reports' Excel export
(`POST /admin/stats/xlsx`).
"""
from __future__ import annotations

import io
import math
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAX_PART = 20 * 1024 * 1024
# Every part read from one workbook, together: a part listed as many sheets is
# read once per listing, so the per-part cap alone does not bound a 5 MB upload.
_MAX_TOTAL = 2 * _MAX_PART
MAX_SHEETS = 100
MAX_COLS = 16384  # XFD, Excel's last column

_STATIC_PARTS = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PKG_REL_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
    "xl/_rels/workbook.xml.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PKG_REL_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'),
}


def _col_letter(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


# What XML 1.0 can hold: a control character or a lone surrogate would make the
# part unreadable (or fail to encode), so it is dropped.
_XML_ILLEGAL = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
_MAX_EXACT_INT = 2 ** 53  # an Excel number is a double; a larger int is written as text, digit for digit


def _xml_text(v: object) -> str:
    return escape(_XML_ILLEGAL.sub("", str(v)))


def _is_number(v: object) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):  # before isfinite, which overflows on a huge int
        return abs(v) <= _MAX_EXACT_INT
    return isinstance(v, float) and math.isfinite(v)


def _cell(ref: str, v: str | int | float) -> str:
    # An inline string is text, never a formula, so it needs no CSV-style escaping.
    if _is_number(v):
        return f'<c r="{ref}"><v>{v!r}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_xml_text(v)}</t></is></c>'


def sheet_name(name: str) -> str:
    """`name` as Excel takes it: none of []:*?/\\ or XML-illegal characters, at most 31 characters, "Report" when
    nothing is left."""
    name = _XML_ILLEGAL.sub("", "".join(" " if ch in "[]:*?/\\" else ch for ch in name))
    return name.strip()[:31] or "Report"


def write_xlsx(rows: list[list[str | int | float]], sheet: str) -> bytes:
    """A one-sheet workbook named `sheet` (cleaned by `sheet_name`) holding
    `rows`: numbers as number cells, the rest as inline strings."""
    sheet = sheet_name(sheet)
    body = "".join(
        f'<row r="{i}">' + "".join(_cell(f"{_col_letter(j)}{i}", v) for j, v in enumerate(row)) + "</row>"
        for i, row in enumerate(rows, start=1))
    width = max((len(r) for r in rows), default=1) or 1
    sheet_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 f'<worksheet xmlns="{_NS}"><cols><col min="1" max="{width}" width="32" customWidth="1"/></cols>'
                 f'<sheetData>{body}</sheetData></worksheet>')
    book = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{_NS}" xmlns:r="{_REL_NS}">'
            f'<sheets><sheet name={_attr(sheet)} sheetId="1" r:id="rId1"/></sheets></workbook>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, xml in _STATIC_PARTS.items():
            z.writestr(name, xml)
        z.writestr("xl/workbook.xml", book)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def _attr(v: str) -> str:
    return '"' + escape(v, {'"': "&quot;"}) + '"'


def _part(z: zipfile.ZipFile, name: str, budget: list[int]) -> ET.Element | None:
    """The part `name` parsed, its size taken from `budget[0]` (bytes left for this workbook)."""
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    budget[0] -= info.file_size
    if info.file_size > _MAX_PART or budget[0] < 0:
        raise ValueError("the workbook is too large")
    return ET.fromstring(z.read(info))


def _text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{{{_NS}}}t"))


def _col_index(ref: str) -> int | None:
    m = re.match(r"([A-Z]{1,3})\d*$", ref)
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1 if n <= MAX_COLS else None


Row = dict[int, str]


def read_xlsx(data: bytes, first_only: bool = False) -> list[tuple[str, list[Row]]]:
    """Every sheet of the workbook in order (the first only with `first_only`), as (name, rows)."""
    try:
        return _sheets(zipfile.ZipFile(io.BytesIO(data)), first_only)
    except (zipfile.BadZipFile, ET.ParseError):
        raise ValueError("the file is not an Excel workbook (.xlsx)") from None


def _sheets(z: zipfile.ZipFile, first_only: bool) -> list[tuple[str, list[Row]]]:
    budget = [_MAX_TOTAL]
    with z:
        book = _part(z, "xl/workbook.xml", budget)
        rels = _part(z, "xl/_rels/workbook.xml.rels", budget)
        if book is None or rels is None:
            raise ValueError("the file is not an Excel workbook (.xlsx)")
        targets = {r.get("Id"): r.get("Target", "") for r in rels}
        shared_root = _part(z, "xl/sharedStrings.xml", budget)
        shared = [_text(si) for si in shared_root] if shared_root is not None else []
        entries = book.findall(f"{{{_NS}}}sheets/{{{_NS}}}sheet")[:1 if first_only else None]
        if len(entries) > MAX_SHEETS:
            raise ValueError(f"the workbook has more than {MAX_SHEETS} sheets")
        out: list[tuple[str, list[Row]]] = []
        for entry in entries:
            target = targets.get(entry.get(f"{{{_REL_NS}}}id"), "")
            path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            sheet = _part(z, path, budget)
            if sheet is None:
                raise ValueError(f"the workbook's sheet {entry.get('name', '')!r} is missing")
            out.append((entry.get("name", ""), [_row(row, shared) for row in sheet.iter(f"{{{_NS}}}row")]))
    return out


def _row(row: ET.Element, shared: list[str]) -> Row:
    cells: Row = {}
    col = -1
    for c in row.findall(f"{{{_NS}}}c"):
        col = _col_index(c.get("r", "")) if c.get("r") else col + 1
        if col is None or col >= MAX_COLS:
            col = MAX_COLS
            continue
        kind, v = c.get("t"), c.find(f"{{{_NS}}}v")
        if kind == "inlineStr":
            value = _text(c)
        elif kind == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(shared):
            value = shared[int(v.text)]
        elif v is not None:
            value = v.text or ""
        else:
            value = ""
        cells[col] = value
    return cells
