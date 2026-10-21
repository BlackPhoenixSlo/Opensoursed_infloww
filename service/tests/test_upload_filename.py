#!/usr/bin/env python3
"""POST /api/of/v2/upload keeps the chatter's file name.

The relay spools the multipart body to a temp file before handing it to
`upload_media`, and both clients (OFClient and the Fansly shim) name the
upload after `path.name` — the S3 key, the convert claim's `name`, Fansly's
`fileName`. A bare NamedTemporaryFile made every Composer upload land in the
vault as `tmpab12cd34.jpg`. The route now spools to `<tempdir>/<name>`, the
original name reduced to safe ASCII (`[A-Za-z0-9._-]`, other runs as `_`):
it cannot leave that directory, and the S3 key built from it needs no URL
encoding (keys used to be plain temp names; we cannot confirm what OF's
convert step does with an encoded or a raw `s3_location`).

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_upload_filename.py

Exit 0 = all pass.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import uuid
from pathlib import Path

# Hard-bind a throwaway DB BEFORE importing any service module (same
# PROD-fallback guard as the other service tests).
_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_upname_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SHARE_TOKEN"] = ""
os.environ.setdefault("SESSION_SECRET", "test-session-secret-do-not-use-in-prod")
os.environ.setdefault("CHATTER_SESSION_SECRET", "test-chatter-secret-do-not-use-in-prod")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from db.engine import init_db  # noqa: E402

asyncio.run(init_db())

from starlette.datastructures import Headers, UploadFile  # noqa: E402

import server  # noqa: E402
import vault_cache  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  FAIL {label}: got {got!r}, want {want!r}")


class _Client:
    """Records what upload_media saw while the spooled file still exists."""

    def __init__(self):
        self.seen: dict = {}

    def upload_media(self, file_path, *, content_type=None, **_):
        p = Path(file_path)
        self.seen = {"name": p.name, "bytes": p.read_bytes(), "ct": content_type, "path": p}
        return {"ready": True, "filename": p.name}


async def _noop_invalidate(_aid):
    return 0


vault_cache.invalidate = _noop_invalidate


def upload(filename: str | None, data: bytes = b"img", ct: str = "image/jpeg") -> tuple[dict, dict]:
    client = _Client()
    server._get_client = lambda *a, **k: client
    f = UploadFile(io.BytesIO(data), filename=filename, headers=Headers({"content-type": ct}))
    result = asyncio.run(server.of_upload_media(f))
    return client.seen, result


print("\nupload filename passthrough")
seen, result = upload("Beach-day_01.JPG")
check("upload_media sees the original name", seen["name"], "Beach-day_01.JPG")
check("the bytes reach upload_media", seen["bytes"], b"img")
check("the content type reaches upload_media", seen["ct"], "image/jpeg")
check("the response echoes the name", result["filename"], "Beach-day_01.JPG")
check("the spooled file is gone afterwards", seen["path"].exists(), False)
check("its temp directory is gone too", seen["path"].parent.exists(), False)

print("\nonly safe ASCII")
seen, _ = upload("Beach day #1 100%?.jpg")
check("spaces, #, % and ? become one _ per run", seen["name"], "Beach_day_1_100.jpg")

seen, _ = upload("Café 写真 😀 v2.png")
check("non-ASCII becomes _ too", seen["name"], "Caf_v2.png")

seen, _ = upload("写真.jpg")
check("a name with nothing ASCII left keeps its extension", seen["name"], "upload.jpg")

seen, _ = upload("../../etc/passwd.png")
check("a path in the name is reduced to its base name", seen["name"], "passwd.png")

seen, _ = upload("C:\\Users\\me\\pic.png")
check("a Windows path is reduced to its base name", seen["name"], "pic.png")

seen, _ = upload("bad\x00na\nme.mp4", ct="video/mp4")
check("control characters become _", seen["name"], "bad_na_me.mp4")

seen, _ = upload(".hidden.png")
check("no leading dot (not a hidden file)", seen["name"], "hidden.png")

seen, _ = upload(None)
check("no name falls back to upload.bin", seen["name"], "upload.bin")

seen, _ = upload("..")
check("a dot-only name falls back to upload.bin", seen["name"], "upload.bin")

seen, _ = upload("photo.jpég")
check("an extension that is not plain ASCII is not kept as one", seen["name"], "photo.jp_g")

# ASCII only, so 200 characters are 200 bytes (filesystems cap 255 bytes).
seen, _ = upload("x" * 300 + ".jpeg")
check("a long name is cut to 200 and keeps its extension",
      (len(seen["name"]), seen["name"].endswith(".jpeg")), (200, True))

seen, _ = upload("photo." + "e" * 40)
check("an absurd extension is cut with the rest of the name",
      (seen["name"], len(seen["name"]) <= 200), ("photo." + "e" * 40, True))

seen, _ = upload("photo." + "e" * 300)
check("…to 200 characters", len(seen["name"]), 200)

for raw in ("Beach day #1 100%?.jpg", "写真 😀.png", "a\x7fb.gif", None, "x" * 999):
    seen, _ = upload(raw)
    check(f"{raw!r:.30} is all [A-Za-z0-9._-]",
          all(ch.isascii() and (ch.isalnum() or ch in "._-") for ch in seen["name"]), True)

if failures:
    print(f"\n{len(failures)} FAILED")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("\nall ok")
