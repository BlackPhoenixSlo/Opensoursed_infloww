"""Bio file storage shared by the public bio app (reads) and the relay's owner admin API (writes).

Layout `<files_dir>/<collection>/<row id>/<filename>` (PocketBase's), collection `profiles` or `links`. One
containment rule for every reader: `safe_path`.
"""
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
    """A staged file could not be written."""


def new_id(n: int) -> str:
    """A PocketBase-style id: `n` lowercase letters or digits."""
    return "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(n))


def files_dir() -> Path:
    """BIO_FILES_DIR, else service/bio_files."""
    return Path(os.environ.get("BIO_FILES_DIR") or Path(__file__).resolve().parents[1] / "bio_files")


def safe_path(base: Path, collection: str, rid: str, filename: str) -> Path | None:
    """The regular file a request names beneath `base`, or None (bad collection/id/name, dotfile, symlink out)."""
    if (collection in decide.FILE_COLLECTIONS and decide.RECORD_ID.fullmatch(rid)
            and decide.FILENAME.fullmatch(filename) and not filename.startswith(".")):
        return contained_file(base, collection, rid, filename)
    return None


def write(base: Path, collection: str, rid: str, filename: str, data: bytes) -> Path:
    """Atomically write `data` (tmp + rename) as a new file; returns its path."""
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
    """Best-effort cleanup after a committed replacement or a failed staged write."""
    try:
        await asyncio.to_thread(remove, files_dir(), collection, rid, name)
    except OSError:
        log.warning("bio admin: file cleanup failed %s/%s", collection, rid)


@asynccontextmanager
async def staged(collection: str, rid: str, name: str, data: bytes | None):
    """Write a candidate off-loop and remove it, including its empty row dir, on failure."""
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
    """Delete one file, or the row's whole dir with `filename=None`; a missing one is fine. Raises OSError."""
    if not decide.RECORD_ID.fullmatch(rid):
        return
    if filename is None:
        if (base / collection / rid).exists():
            shutil.rmtree(base / collection / rid)
        return
    if decide.FILENAME.fullmatch(filename) and not filename.startswith("."):
        (base / collection / rid / filename).unlink(missing_ok=True)
