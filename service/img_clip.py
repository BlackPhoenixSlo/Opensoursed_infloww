"""service/img_clip.py — `/img`'s small clips: a Range request's answer read whole, so img_api can keep it on disk.

A vault GIF is an OF mp4 a <video> loops, and a <video> always sends Range. When upstream's answer says the object
is at most RANGE_CACHE_MAX_BYTES, img_api reads it whole (`read`), writes it to its disk cache and answers the
Range off disk: one proxy download instead of one per picker open. Anything bigger, or of unknown size, streams
through untouched: real videos are never buffered.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Literal, NamedTuple

from fastapi import HTTPException

RANGE_CACHE_MAX_BYTES = 5 * 1024 * 1024

_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")

class Clip(NamedTuple):
    kind: Literal["whole", "part"]  # what upstream's answer holds
    size: int                       # the object's size, as upstream said


def small_clip(r: Any) -> Clip | None:
    """For upstream's answer to a Range request, when the object's size is known and at most
    RANGE_CACHE_MAX_BYTES: "whole" (a 200, or a 206 `bytes 0-(n-1)/n`, what a <video> asks first) or "part"
    (any other 206), with that size. None (stream it through) otherwise, and for an encoded body (Content-Encoding:
    the decoded bytes would not match the declared size)."""
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
    """The whole clip's bytes and Content-Type. When `r` is only part of it (Safari probes `bytes=0-1`), one more
    GET without Range (`refetch`) fetches the rest. Closes every response it reads. Blocking: run in the
    threadpool. Upstream failure, or a body longer or shorter than `clip.size` (a cut transfer): HTTPException
    502, nothing kept."""
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
