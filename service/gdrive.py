# Key-only auth: Drive answers 404, not 403, for an unshared file, so a bad id and a private file look the same.
from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("of-relay.gdrive")

API = "https://www.googleapis.com/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
_NATIVE_PREFIX = "application/vnd.google-apps."

# Drive serves HTML on some error paths; it would land on disk as a corrupt file that fails only at the S3 PUT.
_HTML_SNIFF = b"<"

# Per-read timeout cannot bound a trickling transfer, which would hold the account's liveness claim indefinitely.
DOWNLOAD_MAX_S = float(os.environ.get("VAULT_DOWNLOAD_MAX_S") or 2 * 3600)


class GDriveError(RuntimeError):
    pass


@dataclass(frozen=True)
class DriveRef:
    id: str
    kind: str
    resource_key: str | None = None


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int | None
    resource_key: str | None = None
    md5: str | None = None
    folders: tuple[str, ...] = ()


def folder_tags(f: DriveFile) -> list[str]:
    return list(f.folders[1:] or f.folders[:1])


def api_key() -> str:
    try:
        import secrets_store
        if k := secrets_store.get("GOOGLE_DRIVE_API_KEY"):
            return k.strip()
    except Exception:
        log.debug("secrets_store unavailable; falling back to env", exc_info=True)
    if k := (os.environ.get("GOOGLE_DRIVE_API_KEY") or "").strip():
        return k
    raise GDriveError(
        "No GOOGLE_DRIVE_API_KEY configured. Add one in Settings → AI keys → "
        "Google Drive, or set it "
        "in the relay environment. Create the key at console.cloud.google.com → "
        "APIs & Services → Credentials, with the Drive API enabled."
    )


def parse_link(link: str) -> DriveRef:
    s = (link or "").strip()
    if not s:
        raise GDriveError("empty Google Drive link")

    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", s):
        return DriveRef(id=s, kind="unknown")

    u = urlparse(s if "://" in s else f"https://{s}")
    if "drive.google.com" not in u.netloc and "docs.google.com" not in u.netloc:
        raise GDriveError(f"not a Google Drive link: {link}")

    q = parse_qs(u.query)
    rkey = (q.get("resourcekey") or [None])[0]

    if m := re.search(r"/folders/([A-Za-z0-9_-]+)", u.path):
        return DriveRef(id=m.group(1), kind="folder", resource_key=rkey)
    if m := re.search(r"/file/d/([A-Za-z0-9_-]+)", u.path):
        return DriveRef(id=m.group(1), kind="file", resource_key=rkey)
    if m := re.search(r"/d/([A-Za-z0-9_-]+)", u.path):
        return DriveRef(id=m.group(1), kind="unknown", resource_key=rkey)
    if fid := (q.get("id") or [None])[0]:
        return DriveRef(id=fid, kind="unknown", resource_key=rkey)

    raise GDriveError(f"could not find a file or folder id in: {link}")


def _headers(*refs) -> dict:
    pairs = [f"{r.id}/{r.resource_key}" for r in refs
             if r is not None and getattr(r, "resource_key", None)]
    return {"X-Goog-Drive-Resource-Keys": ",".join(pairs)} if pairs else {}


def _explain(status: int, body: str, what: str) -> GDriveError:
    low = (body or "").lower()
    if "<title>sorry" in low or "unusual traffic" in low:
        return GDriveError(
            f"{what}: Google is rate-limiting this key or IP (it served its "
            f"\"Sorry…\" page, not an API error). Wait a few minutes; avoid "
            f"re-downloading files you already have.")
    if status == 404:
        return GDriveError(
            f"{what}: not found, or not shared publicly. With an API key these "
            f"are indistinguishable — open the link in a private window to "
            f"check that 'Anyone with the link' is set.")
    if status == 403:
        if "abusive" in low:
            return GDriveError(f"{what}: Drive flagged this file as abusive and "
                               f"refuses to serve it.")
        if "cannotdownload" in low.replace("_", ""):
            return GDriveError(f"{what}: the owner disabled downloading for this file.")
        if "quota" in low or "ratelimit" in low:
            return GDriveError(f"{what}: Drive API quota exceeded — retry later, "
                               f"or raise the quota on the key's project.")
        return GDriveError(f"{what}: access denied by Drive ({body[:200]})")
    if status == 400 and "api key not valid" in low:
        return GDriveError(f"{what}: the GOOGLE_DRIVE_API_KEY is not valid, or the "
                           f"Drive API is not enabled on its project.")
    return GDriveError(f"{what}: Drive returned {status} — {body[:200]}")


_LOCAL = threading.local()


# Per thread: requests.Session is not thread-safe and two imports run on two worker threads.
def _session():
    s = getattr(_LOCAL, "session", None)
    if s is None:
        import requests
        s = _LOCAL.session = requests.Session()
    return s


# Key as a HEADER, never a `key=` query param: requests puts the full URL into ConnectionError text, which is stored and rendered.
def _auth() -> dict:
    return {"x-goog-api-key": api_key()}


def redact(text: str) -> str:
    text = str(text)
    try:
        key = api_key()
    except GDriveError:
        return text
    return text.replace(key, "<GOOGLE_DRIVE_API_KEY>") if key else text


def _get(url: str, *, params: dict, refs, what: str, **kw):
    try:
        return _session().get(url, params=params,
                              headers={**_auth(), **_headers(*refs)}, **kw)
    except GDriveError:
        raise
    except Exception as e:  # noqa: BLE001 — transport errors must be redacted too
        raise GDriveError(f"{what}: {redact(e)}") from None


def metadata(ref: DriveRef) -> DriveFile:
    r = _get(f"{API}/{ref.id}",
             params={"fields": "id,name,mimeType,size,md5Checksum,resourceKey,"
                               "shortcutDetails",
                     "supportsAllDrives": "true"},
             refs=(ref,), what=f"Drive item {ref.id}", timeout=30)
    if not r.ok:
        raise _explain(r.status_code, r.text, f"Drive item {ref.id}")
    d = r.json()
    if d.get("mimeType") == SHORTCUT_MIME:
        target = (d.get("shortcutDetails") or {}).get("targetId")
        if not target:
            raise GDriveError(f"{d.get('name')}: shortcut with no target")
        return metadata(DriveRef(id=target, kind="unknown",
                                 resource_key=ref.resource_key))
    return DriveFile(id=d["id"], name=d.get("name") or d["id"],
                     mime_type=d.get("mimeType") or "application/octet-stream",
                     size=int(d["size"]) if d.get("size") else None,
                     # A resource key belongs to one file: a child must not get its parent folder's (404).
                     resource_key=d.get("resourceKey") or ref.resource_key,
                     md5=d.get("md5Checksum"))


# max_files is a budget for the whole tree, not per folder; keep nextPageToken in fields or only one page returns.
def list_folder(ref: DriveRef, *, recursive: bool = True,
                max_files: int = 500, _depth: int = 0,
                _path: tuple[str, ...] = ()) -> list[DriveFile]:
    if _depth > 8:
        log.warning("gdrive: folder nesting deeper than 8, stopping at %s", ref.id)
        return []
    out: list[DriveFile] = []
    token = None
    while True:
        params = {
            "q": f"'{ref.id}' in parents and trashed=false",
            "fields": "nextPageToken, files(id,name,mimeType,size,md5Checksum,"
                      "resourceKey,shortcutDetails)",
            "pageSize": "200",
            "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
        }
        if token:
            params["pageToken"] = token
        r = _get(API, params=params, refs=(ref,),
                 what=f"Drive folder {ref.id}", timeout=30)
        if not r.ok:
            raise _explain(r.status_code, r.text, f"Drive folder {ref.id}")
        page = r.json()
        for d in page.get("files") or []:
            mime = d.get("mimeType") or ""
            rkey = d.get("resourceKey")
            if mime == FOLDER_MIME:
                if recursive and len(out) < max_files:
                    out.extend(list_folder(
                        DriveRef(id=d["id"], kind="folder", resource_key=rkey),
                        recursive=True, max_files=max_files - len(out),
                        _depth=_depth + 1,
                        _path=_path + (d.get("name") or d["id"],)))
                    if len(out) >= max_files:
                        return out[:max_files]
                continue
            if mime == SHORTCUT_MIME:
                try:
                    out.append(replace(
                        metadata(DriveRef(id=d["id"], kind="unknown",
                                          resource_key=rkey)),
                        folders=_path))
                except GDriveError as e:
                    log.warning("gdrive: skipping shortcut %s — %s", d.get("name"), e)
                if len(out) >= max_files:
                    log.warning("gdrive: folder %s hit the %d-file cap", ref.id, max_files)
                    return out[:max_files]
                continue
            out.append(DriveFile(id=d["id"], name=d.get("name") or d["id"],
                                 mime_type=mime,
                                 size=int(d["size"]) if d.get("size") else None,
                                 resource_key=rkey,
                                 md5=d.get("md5Checksum"),
                                 folders=_path))
            if len(out) >= max_files:
                log.warning("gdrive: folder %s hit the %d-file cap", ref.id, max_files)
                return out[:max_files]
        token = page.get("nextPageToken")
        if not token:
            return out


def is_uploadable(f: DriveFile) -> tuple[bool, str]:
    if f.mime_type.startswith(_NATIVE_PREFIX):
        return False, f"Google-native file ({f.mime_type.rsplit('.', 1)[-1]}) has no media to upload"
    if not f.mime_type.startswith(("image/", "video/", "audio/")):
        return False, f"unsupported type {f.mime_type}"
    return True, ""


def resolve(links: list[str], *, max_files: int = 500) -> list[DriveFile]:
    seen: set[str] = set()
    out: list[DriveFile] = []
    for link in links:
        remaining = max_files - len(out)
        if remaining <= 0:
            log.warning("gdrive: %d-file cap reached, not resolving %d more link(s)",
                        max_files, len(links) - links.index(link))
            break
        ref = parse_link(link)
        meta = metadata(ref)
        files = (list_folder(DriveRef(id=meta.id, kind="folder",
                                      resource_key=meta.resource_key),
                             max_files=remaining, _path=(meta.name,))
                 if meta.mime_type == FOLDER_MIME else [meta])
        for f in files:
            if f.id not in seen:
                seen.add(f.id)
                out.append(f)
    return out


def download(f: DriveFile, dest_dir: str | Path, *,
             max_bytes: int | None = None,
             min_free_bytes: int | None = None,
             max_seconds: float = DOWNLOAD_MAX_S) -> Path:
    if max_bytes is not None and f.size is not None and f.size > max_bytes:
        raise GDriveError(
            f"{f.name}: {f.size / 1e6:.0f} MB exceeds the {max_bytes / 1e6:.0f} MB limit")

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Drive names are user-supplied: basename only so "../../etc/x" cannot escape the spool dir.
    safe = re.sub(r"[^\w.\- ]+", "_", Path(f.name).name).strip() or f.id
    dest = dest_dir / f"{f.id}_{safe}"

    # allow_redirects=False: requests keeps custom headers across hosts, so x-goog-api-key would leak; follow by hand without it.
    r = _get(f"{API}/{f.id}",
             params={"alt": "media", "supportsAllDrives": "true"},
             refs=(f,), what=f"downloading {f.name}", stream=True, timeout=120,
             allow_redirects=False)
    for _ in range(5):
        if r.status_code not in (301, 302, 303, 307, 308):
            break
        location = r.headers.get("location")
        if not location:
            break
        r.close()
        try:
            r = _session().get(location, stream=True, timeout=120,
                               allow_redirects=False)
        except Exception as e:  # noqa: BLE001
            raise GDriveError(f"downloading {f.name}: {redact(e)}") from None
    if not r.ok:
        raise _explain(r.status_code, r.text, f"downloading {f.name}")

    written = 0
    since_check = 0
    deadline = time.monotonic() + max_seconds
    _FREE_CHECK_EVERY = 64 * 1024 * 1024
    try:
        with dest.open("wb") as fh:
            for chunk in r.iter_content(1024 * 256):
                if not chunk:
                    continue
                if not written and chunk.lstrip()[:1] == _HTML_SNIFF:
                    raise GDriveError(
                        f"{f.name}: Drive served an HTML page instead of the file "
                        f"— it is probably not publicly shared.")
                written += len(chunk)
                if time.monotonic() > deadline:
                    raise GDriveError(
                        f"{f.name}: gave up after {max_seconds / 60:.0f} minutes "
                        f"({written / 1e6:.0f} MB in) — the download is not "
                        f"making progress")
                if max_bytes is not None and written > max_bytes:
                    raise GDriveError(
                        f"{f.name}: exceeded the {max_bytes / 1e6:.0f} MB limit mid-download")
                since_check += len(chunk)
                if min_free_bytes is not None and since_check >= _FREE_CHECK_EVERY:
                    since_check = 0
                    if shutil.disk_usage(dest_dir).free < min_free_bytes:
                        raise GDriveError(
                            f"{f.name}: stopping the download — free disk would "
                            f"fall below the {min_free_bytes / 1e9:.1f} GB floor")
                fh.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    log.info("gdrive: downloaded %s (%d bytes) -> %s", f.name, written, dest.name)
    return dest
