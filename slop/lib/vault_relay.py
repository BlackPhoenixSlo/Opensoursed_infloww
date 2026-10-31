"""The vault import's part of the slop relay (lib/relay.py loads it: `OF` joins `_OfflineOF`'s
bases, `wire` runs at the end of its `_wire`).

OnlyFans' side of a vault import (`POST /api/of/v2/vault/upload/batch` + `/append`, run by
`vault_upload.start` on a worker thread) is faked only when a scenario writes
`$DEMO_SHOTS_TMP/of-vault.json` (`{}` is enough); without it every call re-raises the
client build's error as before.

  upload_claim(path)            OF's dedupe -> S3 -> convert claim, one call: the bytes are read
                                and recorded (name, size, sha256); a file OF already minted (same
                                md5 + size) is a dedupe hit (`vault_id`), else a fresh claim.
  create_post / get_post /      the carrier post, at OF's REST shape: the create mints one vault id
  delete_post                   per claim on it (ready at once), get_post lists them, delete ends it.
                                `materialize_to_vault` itself is the PRODUCT's
                                (`OFClient.materialize_to_vault`, run on this object), so the carrier
                                intent / id / delete hooks and the pacer gate run unchanged.
  vault_media_lookup_hash       GET /vault/media/hash: the minted media for (md5, size), or None.
  vault_media_by_id             GET /vault/media/{id}: the minted media's dict (photo / video).
  add_media_to_vault_list       POST /vault/lists/{id}/media: recorded, answered {id, mediaIds}.

  GET /__slop/vault/fake  {claims, carriers, lists, minted}: what OnlyFans received, in order.

Declared: the dedupe -> S3 -> convert pipeline (`upload_claim`, three OF hosts) is one in-process
call, not its HTTP; the bytes reaching it are the staged file the relay's own route wrote.

The vault spool (`VAULT_SPOOL_DIR`, default `service/vault_spool`) is pointed into the run's
temp dir when unset, at import time (before relay_guarded imports the service), so a slop run
never writes into the checkout.
"""

import hashlib
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

if os.environ.get("DEMO_SHOTS_TMP") and not os.environ.get("VAULT_SPOOL_DIR"):
    os.environ["VAULT_SPOOL_DIR"] = str(Path(os.environ["DEMO_SHOTS_TMP"]) / "vault_spool")

VAULT_ID_BASE = 8_800_000_000
POST_ID_BASE = 7_700_000_000
VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
_lock = threading.Lock()  # vault_upload runs on a worker thread
_fake: dict = {"claims": [], "carriers": [], "lists": [], "minted": {}}
_by_key: dict[tuple, int] = {}   # (md5, size) -> vault id
_posts: dict[int, list[int]] = {}


def _on() -> bool:
    return (Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-vault.json").is_file()


def _media(vid: int) -> dict:
    m = _fake["minted"][str(vid)]
    # No `files`: the fake has no CDN, so the mirror row gets no thumb url (the grid draws no still) rather
    # than one whose fetch goes through the offline client and fails.
    return {"id": vid, "type": m["type"], "isReady": True, "createdAt": m["at"], "hasError": False}


class OF:
    @property
    def _VAULT_MARKER(self) -> str:
        from of_client import OFClient
        return OFClient._VAULT_MARKER

    def upload_claim(self, file_path, *, content_type=None, watermark_text=None, **_kw):
        if not _on():
            raise self._err
        from of_client import UploadClaim
        p = Path(file_path)
        data = p.read_bytes()
        md5, sha = hashlib.md5(data).hexdigest(), hashlib.sha256(data).hexdigest()
        with _lock:
            hit = _by_key.get((md5, len(data)))
            _fake["claims"].append({"t": time.time(), "account": self.account_id, "name": p.name,
                                    "size": len(data), "sha256": sha, "dedupe_hit": hit})
            if hit is not None:
                return UploadClaim(vault_id=hit)
            kind = "video" if p.suffix.lower() in VIDEO else "photo"
            return UploadClaim(media={"slop_claim": md5, "name": p.name, "type": kind, "size": len(data)}, dedupe_key=md5,
                               size=len(data))

    def materialize_to_vault(self, send_with, **kw):
        if not _on():
            raise self._err
        from of_client import OFClient
        return OFClient.materialize_to_vault(self, send_with, **kw)

    def create_post(self, text, *, media_files=None, carrier_posted_at=None, **_kw) -> dict:
        if not _on():
            raise self._err
        at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with _lock:
            pid = POST_ID_BASE + len(_fake["carriers"]) + 1
            ids = []
            for c in media_files or []:
                vid = VAULT_ID_BASE + len(_fake["minted"]) + 1
                _fake["minted"][str(vid)] = {"name": c.get("name"), "type": c.get("type") or "photo", "at": at,
                                             "md5": c.get("slop_claim"), "account": self.account_id}
                _by_key[(c.get("slop_claim"), c.get("size"))] = vid
                ids.append(vid)
            _posts[pid] = ids
            _fake["carriers"].append({"t": time.time(), "post_id": pid, "text": text, "posted_at": carrier_posted_at,
                                      "media_ids": ids, "deleted": False})
        return {"id": pid}

    def get_post(self, post_id) -> dict:
        if not _on():
            raise self._err
        with _lock:
            return {"id": int(post_id), "media": [_media(v) for v in _posts.get(int(post_id), [])]}

    def delete_post(self, post_id) -> dict:
        if not _on():
            raise self._err
        with _lock:
            for c in _fake["carriers"]:
                if c["post_id"] == int(post_id):
                    c["deleted"] = True
        return {"success": True}

    def vault_media_lookup_hash(self, md5_hex, size):
        if not _on():
            raise self._err
        with _lock:
            vid = _by_key.get((md5_hex, int(size)))
            return _media(vid) if vid is not None else None

    def vault_media_by_id(self, media_id) -> dict:
        if not _on():
            raise self._err
        with _lock:
            if str(int(media_id)) not in _fake["minted"]:
                raise LookupError(f"slop: no vault media {media_id}")
            return _media(int(media_id))

    def add_media_to_vault_list(self, list_id, media_ids) -> dict:
        if not _on():
            raise self._err
        with _lock:
            _fake["lists"].append({"list_id": int(list_id), "media_ids": [int(m) for m in media_ids]})
        return {"id": int(list_id), "mediaIds": [int(m) for m in media_ids]}


def wire(app, loopback, relay) -> None:
    from fastapi import Request

    async def fake(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in _fake.items()}

    app.add_api_route("/__slop/vault/fake", fake, methods=["GET"])
