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

# Fan names, message bodies and tip notes are fan-typed: formula-looking text gets a leading ' (app/lib/csv.ts keeps the same rule)
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NOT_A_FORMULA = re.compile(r"-|[-+]?\d+(\.\d+)?", re.ASCII)


def safe_cell(v: Any) -> Any:
    if isinstance(v, str) and v.startswith(_FORMULA_START) and not _NOT_A_FORMULA.fullmatch(v):
        return "'" + v
    return v


async def query_rows(s: AsyncSession, q: Any) -> AsyncIterator[Any]:
    async for row in await s.stream(q.limit(CSV_MAX_ROWS + 1).execution_options(yield_per=500)):
        yield row


async def stream_csv(
    rows: AsyncIterator[Any],
    header: Sequence[str],
    to_row: Callable[[Any], Sequence[Any]],
    *,
    truncated_width: int | None = None,
) -> AsyncIterator[bytes]:
    cap = CSV_MAX_ROWS
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
    async def body() -> AsyncIterator[bytes]:
        async with get_session() as s:
            async for chunk in stream_csv(rows(s), header, to_row, truncated_width=truncated_width):
                yield chunk

    return StreamingResponse(body(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        # upper bound: Starlette flushes headers before the body
        "X-Row-Count": str(CSV_MAX_ROWS),
        "Cache-Control": "no-store",
    })


def safe_filename_part(raw: str | None, fallback: str = "") -> str:
    return (raw or fallback).replace(":", "").replace("/", "-")[:32]
