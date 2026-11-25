import hashlib
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

if os.environ.get("DEMO_SHOTS_TMP") and not os.environ.get("VAULT_SPOOL_DIR"):
    os.environ["VAULT_SPOOL_DIR"] = str(Path(os.environ["DEMO_SHOTS_TMP"]) / "vault_spool")

VAULT_ID_BASE = 8_800_000_000
LIST_ID_BASE = 6_600_000_000
POST_ID_BASE = 7_700_000_000
VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
_lock = threading.Lock()
_fake: dict = {"claims": [], "carriers": [], "lists": [], "minted": {}, "made": []}
_by_key: dict[tuple, int] = {}
_posts: dict[int, list[int]] = {}


def _on() -> bool:
    return (Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-vault.json").is_file()


def _media(vid: int) -> dict:
    m = _fake["minted"][str(vid)]
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
            # no `files` on the minted media: the fake has no CDN, so no thumb url
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

    def create_vault_list(self, name) -> dict:
        if not _on():
            raise self._err
        with _lock:
            lid = LIST_ID_BASE + len(_fake["made"]) + 1
            _fake["made"].append({"id": lid, "name": str(name), "account": self.account_id})
        return {"id": lid, "name": str(name)}

    def vault_media(self, *, limit=10, offset=0, list_id=None, **_kw) -> dict:
        with _lock:
            made = _on() and list_id is not None and any(m["id"] == int(list_id) for m in _fake["made"])
            ids = list(dict.fromkeys(m for c in _fake["lists"] if c["list_id"] == int(list_id or 0)
                                     for m in c["media_ids"])) if made else []
        if not made:
            nxt = getattr(super(), "vault_media", None)
            if nxt is None:
                raise self._err
            return nxt(limit=limit, offset=offset, list_id=list_id, **_kw)
        page = ids[int(offset):int(offset) + int(limit)]
        return {"list": [{"id": m} for m in page], "hasMore": int(offset) + len(page) < len(ids)}


def wire(app, loopback, relay) -> None:
    from fastapi import Request

    async def fake(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in _fake.items()}

    app.add_api_route("/__slop/vault/fake", fake, methods=["GET"])
