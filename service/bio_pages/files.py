from __future__ import annotations

import os
import shutil
import asyncio
import secrets
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from bio_pages import decide
from bio_pages.assets import contained_file

log = logging.getLogger("of-relay.bio-files")


class WriteFailed(OSError):
    pass


def new_id(n: int) -> str:
    return "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(n))


def files_dir() -> Path:
    return Path(os.environ.get("BIO_FILES_DIR") or Path(__file__).resolve().parents[1] / "bio_files")


def safe_path(base: Path, collection: str, rid: str, filename: str) -> Path | None:
    if (collection in decide.FILE_COLLECTIONS and decide.RECORD_ID.fullmatch(rid)
            and decide.FILENAME.fullmatch(filename) and not filename.startswith(".")):
        return contained_file(base, collection, rid, filename)
    return None


def write(base: Path, collection: str, rid: str, filename: str, data: bytes) -> Path:
    d = base / collection / rid
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{filename}.tmp"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, d / filename)
    finally:
        tmp.unlink(missing_ok=True)
    return d / filename


async def discard(collection: str, rid: str, name: str | None = None) -> None:
    try:
        await asyncio.to_thread(remove, files_dir(), collection, rid, name)
    except OSError:
        log.warning("bio admin: file cleanup failed %s/%s", collection, rid)


@asynccontextmanager
async def staged(collection: str, rid: str, name: str, data: bytes | None):
    try:
        if data is not None:
            try:
                await asyncio.to_thread(write, files_dir(), collection, rid, name, data)
            except OSError as exc:
                raise WriteFailed() from exc
        yield
    except BaseException:
        if data is not None:
            await discard(collection, rid, name)
            try:
                await asyncio.to_thread((files_dir() / collection / rid).rmdir)
            except OSError:
                pass  # another file may share this row dir
        raise


def remove(base: Path, collection: str, rid: str, filename: str | None = None) -> None:
    if not decide.RECORD_ID.fullmatch(rid):
        return
    if filename is None:
        if (base / collection / rid).exists():
            shutil.rmtree(base / collection / rid)
        return
    if decide.FILENAME.fullmatch(filename) and not filename.startswith("."):
        (base / collection / rid / filename).unlink(missing_ok=True)
