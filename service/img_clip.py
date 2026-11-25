from __future__ import annotations

import re
from typing import Any, Callable, Literal, NamedTuple

from fastapi import HTTPException

RANGE_CACHE_MAX_BYTES = 5 * 1024 * 1024

_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")

class Clip(NamedTuple):
    kind: Literal["whole", "part"]
    size: int


def small_clip(r: Any) -> Clip | None:
    # An encoded body streams through: the decoded bytes would not match the declared size.
    if (r.headers.get("Content-Encoding") or "identity").strip().lower() != "identity":
        return None
    if r.status_code == 206:
        m = _CONTENT_RANGE.fullmatch((r.headers.get("Content-Range") or "").strip())
        if not m:
            return None
        n = int(m.group(3))
        kind: Literal["whole", "part"] = "whole" if m.group(1) == "0" and int(m.group(2)) == n - 1 else "part"
    else:
        try:
            n = int(r.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        kind = "whole"
    return Clip(kind, n) if 0 < n <= RANGE_CACHE_MAX_BYTES else None


def read(r: Any, clip: Clip, refetch: Callable[[], Any]) -> tuple[bytes, str]:
    # Safari probes bytes=0-1, so a partial answer needs one more GET without Range.
    try:
        if clip.kind == "part":
            r.close()
            r = refetch()
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail="upstream non-2xx on the whole clip")
        data = bytearray()
        for chunk in r.iter_content(chunk_size=64 * 1024):
            data.extend(chunk)
            if len(data) > clip.size:
                raise HTTPException(status_code=502, detail="clip larger than upstream said")
        if len(data) < clip.size:
            raise HTTPException(status_code=502, detail="clip shorter than upstream said")
        return bytes(data), r.headers.get("Content-Type", "application/octet-stream")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream fetch failed: {e}")
    finally:
        try:
            r.close()
        except Exception:
            pass
