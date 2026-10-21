"""Server-side CSV exports, shared by `/admin/paid-messages` (messages.py),
`/admin/stats/sales-records` (stats.py), `/admin/tips-list` and
`/admin/top-tippers` (transactions.py).

Streamed so memory stays bounded; the file size (~50-200 MB at full cap) is
the real ceiling, not RAM. Past `CSV_MAX_ROWS` rows the file ends in a
TRUNCATED sentinel line, and each route sends `X-Row-Count` = the cap (an
upper bound: Starlette flushes headers before the body) so the UI can warn.

Every text cell a spreadsheet would read as a formula (one starting with
= + - @, a tab or a CR) is written with a leading ' so it opens as text: fan
names, message bodies and tip notes are typed by fans. Numbers, and text that
is just a number ("-12.50"), are left alone.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, AsyncIterator, Callable, Sequence

from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session

CSV_MAX_ROWS = 50_000
TRUNCATED_LINE = "# TRUNCATED — narrow date range or filters"

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
# Starts like a formula but is not one: a number ("-12.50", ASCII digits only),
# or the lone "-" placeholder an empty cell shows. app/lib/csv.ts keeps the
# same rule.
_NOT_A_FORMULA = re.compile(r"-|[-+]?\d+(\.\d+)?", re.ASCII)


def safe_cell(v: Any) -> Any:
    """`v`, with a leading ' when it is text a spreadsheet would run as a formula."""
    if isinstance(v, str) and v.startswith(_FORMULA_START) and not _NOT_A_FORMULA.fullmatch(v):
        return "'" + v
    return v


async def query_rows(s: AsyncSession, q: Any) -> AsyncIterator[Any]:
    """Query `q`'s rows streamed, one past the cap at most (so `stream_csv`
    can tell a truncated file)."""
    async for row in await s.stream(q.limit(CSV_MAX_ROWS + 1).execution_options(yield_per=500)):
        yield row


async def stream_csv(
    rows: AsyncIterator[Any],
    header: Sequence[str],
    to_row: Callable[[Any], Sequence[Any]],
    *,
    truncated_width: int | None = None,
) -> AsyncIterator[bytes]:
    """Yield the header, then one CSV line per row of `rows` (via `to_row`,
    each cell through `safe_cell`), stopping at `CSV_MAX_ROWS` with the
    TRUNCATED sentinel line, which has `truncated_width` cells (default: the
    header's width). Each chunk is flushed as it is written; the StringIO is
    reset so it never grows. `rows` is `query_rows` of a query, or the rows a
    route built itself (Sales records credits each sale in Python)."""
    cap = CSV_MAX_ROWS  # read per call so a test can lower it
    buf = io.StringIO()
    writer = csv.writer(buf)

    def write(cells: Sequence[Any]) -> None:
        writer.writerow([safe_cell(v) for v in cells])

    def flush() -> bytes:
        out = buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)
        return out

    write(header)
    yield flush()
    written = 0
    async for row in rows:
        if written >= cap:
            write([TRUNCATED_LINE] + [""] * ((truncated_width or len(header)) - 1))
            yield flush()
            break
        write(to_row(row))
        written += 1
        yield flush()


def download(
    filename: str,
    rows: Callable[[AsyncSession], AsyncIterator[Any]],
    header: Sequence[str],
    to_row: Callable[[Any], Sequence[Any]],
    *,
    truncated_width: int | None = None,
) -> StreamingResponse:
    """The streamed `text/csv` attachment of `rows(session)`. The session is
    opened inside the body's generator so it stays open for the download."""
    async def body() -> AsyncIterator[bytes]:
        async with get_session() as s:
            async for chunk in stream_csv(rows(s), header, to_row, truncated_width=truncated_width):
                yield chunk

    return StreamingResponse(body(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Row-Count": str(CSV_MAX_ROWS),  # upper bound; the UI relies on the TRUNCATED line
        "Cache-Control": "no-store",
    })


def safe_filename_part(raw: str | None, fallback: str = "") -> str:
    """A filter value as typed, made safe for a download filename."""
    return (raw or fallback).replace(":", "").replace("/", "-")[:32]
