"""OnlyFans' media upload at its wire, for lib/of_wire.py (its route table lists these routes: vault/media/hash,
signed/create, the S3 PUT, signed/finish, convert's claim, GET / DELETE a post). `FakeOF.upload` is one
`UploadWire`; the request handler hands it every request it did not answer itself (`handle`), and a scenario reads
its records with `snapshot()`. Everything is kept per Creator in arrival order and guarded by `FakeOF.lock`.

A claim is minted into the vault only once something REFERENCES it (a chat send's or a post's `mediaFiles` names
its processId), as OF does; one vault id per S3 object (ETag + size). A carrier post's listing (GET posts/{id})
names its media in a deterministic shuffled order (seeded by the post id): OF's order is arbitrary
(service/of_upload.py `materialize_to_vault`), so the product must attribute ids by content, not position.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_default
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, parse_qs, quote, unquote

if TYPE_CHECKING:
    from slop.lib.of_wire import FakeOF

_POST_ONE = re.compile(r"/api2/v2/posts/(\d+)")
_VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
INVALID_INPUT = {"error": {"code": 0, "message": "Invalid input."}}
RECORDS = ("uploads", "s3_puts", "claims", "carriers", "lookups", "minted")


def _form(ctype: str, raw: bytes) -> dict[str, str]:
    """A multipart/form-data body's fields (stdlib `email`), name -> text."""
    msg = BytesParser(policy=email_default).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
    return {p.get_param("name", header="content-disposition"): (p.get_payload(decode=True) or b"").decode()
            for p in msg.iter_parts()}


class UploadWire:
    def __init__(self, fake: "FakeOF"):
        self.fake = fake
        # Per Creator, in arrival order.
        self.uploads: dict[str, list[dict]] = {}   # signed/create: {t, key, client_key, parts, token, upload_id, ...}
        self.s3_puts: dict[str, list[dict]] = {}   # {t, key, part, size, md5, ok}
        self.claims: dict[str, list[dict]] = {}    # convert claims: {t, key, etag, location, bucket, name, ...}
        self.carriers: dict[str, list[dict]] = {}  # posts deleted: {t, id, media_ids}
        self.lookups: dict[str, list[dict]] = {}   # vault/media/hash reads: {t, h, size, hit}
        self.minted: dict[str, list[dict]] = {}    # vault media minted from claims: {id, etag, size, name, ...}
        self.s3: dict[str, dict] = {}              # S3 key -> the stored object {uid, size, sha256, etag, parts}
        self._s3_up: dict[str, dict] = {}          # S3 key -> {uid, rec (its `uploads` row), parts {n: (md5, bytes)}}
        self._by_pid: dict[str, dict] = {}         # processId -> its claim row
        self._vault_by_pid: dict[str, int] = {}    # processId -> the vault id it minted
        self._vault_by_etag: dict[tuple, int] = {}  # (Creator, S3 ETag, size) -> vault id
        self._seen: dict[str, tuple[int, int]] = {}  # per Creator, (sends, posts) already scanned for references

    def snapshot(self) -> dict:
        """Copies of the records (RECORDS, per Creator) and the S3 objects."""
        with self.fake.lock:
            return {**{k: {a: list(v) for a, v in getattr(self, k).items()} for k in RECORDS}, "s3": dict(self.s3)}

    def _mint_referenced(self, uid: str) -> None:
        """Give every claim of this Creator that a chat send or a post names (`mediaFiles`, by processId) its
        vault media, once per S3 object (ETag + size). Scans only the sends / posts that arrived since the last
        call (a claim is always answered before the product can name it). Holds `fake.lock`."""
        sends, posts = self.fake.sends.get(uid, []), self.fake.posts.get(uid, [])
        i, j = self._seen.get(uid, (0, 0))
        self._seen[uid] = (len(sends), len(posts))
        for b in [s.get("body") or {} for s in sends[i:]] + posts[j:]:
            for mf in b.get("mediaFiles") or ():
                pid = str(mf.get("processId")) if isinstance(mf, dict) else None
                c = self._by_pid.get(pid) if pid else None
                if c is None or c["account"] != uid or pid in self._vault_by_pid:
                    continue
                key = (uid, c["object"]["etag"], c["object"]["size"])
                vid = self._vault_by_etag.get(key)
                if vid is None:
                    vid = next(self.fake._ids)
                    kind = "video" if c["name"].lower().endswith(_VIDEO) else "photo"
                    self.fake.vault.setdefault(uid, {})[vid] = {
                        "id": vid, "type": kind, "isReady": True, "hasError": False, "canView": True,
                        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")}
                    self._vault_by_etag[key] = vid
                    self.minted.setdefault(uid, []).append({"t": time.time(), "id": vid, "etag": key[1],
                                                            "size": key[2], "name": c["name"], "processId": pid})
                self._vault_by_pid[pid] = vid

    def _s3_ok(self, h, uid: str, etag: str) -> None:
        """S3's answer to a PUT: 200, empty body, the object's (part's) ETag."""
        with self.fake.lock:
            self.fake.calls.append({"t": time.time(), "account": uid, "route": "PUT /s3/{key}", "status": 200})
        h.send_response(200)
        h.send_header("ETag", f'"{etag}"')
        h.send_header("Content-Length", "0")
        h.end_headers()

    def handle(self, h, method: str, u: SplitResult, uid: str, route: str, raw: bytes) -> bool:
        """Answer one of the upload's routes on handler `h`; False: not one of them."""
        fake, now = self.fake, time.time()
        if method == "GET" and u.path == "/api2/v2/vault/media/hash":
            q = parse_qs(u.query)
            hh, size = (q.get("h") or [""])[0], int((q.get("size") or ["0"])[0] or 0)
            with fake.lock:
                self._mint_referenced(uid)
                vid = self._vault_by_etag.get((uid, hh, size))
                media = dict(fake.vault[uid][vid]) if vid is not None else None
                self.lookups.setdefault(uid, []).append({"t": now, "h": hh, "size": size, "hit": vid})
            if media is None:
                h._record(uid, route, 404, {"error": {"code": 0, "message": "Media Not Found"}})
            else:
                h._record(uid, route, 200, media)
            return True
        if method == "POST" and u.path == "/api2/v2/upload/signed/create":
            body = json.loads(raw or b"{}")
            ours, parts = str(body.get("key") or ""), int(body.get("parts") or 1)
            key = f"upload/{uid}/{ours[len('upload/'):] if ours.startswith('upload/') else ours}"
            put = f"{fake.origin}/s3/{quote(key)}"
            with fake.lock:
                n = next(fake._ids)
                rec = {"t": now, "key": key, "client_key": ours, "parts": parts,
                       "content_type": body.get("contentType"), "user_prefix": body.get("userPrefix"),
                       "token": f"slop-ut-{n:x}", "upload_id": f"slop-mpu-{n}" if parts > 1 else None,
                       "finished": False}
                self.uploads.setdefault(uid, []).append(rec)
                self._s3_up[key] = {"uid": uid, "rec": rec, "parts": {}}
            ans = {"key": key, "getUrl": f"{fake.origin}/cdn/{key[len('upload/'):]}", "uploadToken": rec["token"]}
            if parts > 1:
                ans.update(uploadId=rec["upload_id"], keys=[
                    {"part": p, "putUrl": f"{put}?partNumber={p}&uploadId={rec['upload_id']}&X-Amz-Signature=slop"}
                    for p in range(1, parts + 1)])
            else:
                ans["putUrl"] = f"{put}?X-Amz-Signature=slop"
            h._record(uid, route, 200, ans)
            return True
        if method == "PUT" and u.path.startswith("/s3/"):
            key, q = unquote(u.path[len("/s3/"):]), parse_qs(u.query)
            part = int(q["partNumber"][0]) if "partNumber" in q else None
            md5 = hashlib.md5(raw)
            with fake.lock:
                s = self._s3_up.get(key)
                owner = s["uid"] if s else ""
                rec = s["rec"] if s else {}
                ok = s is not None and (
                    rec["upload_id"] is None and part is None
                    or rec["upload_id"] is not None and part is not None and 1 <= part <= rec["parts"]
                    and (q.get("uploadId") or [""])[0] == rec["upload_id"])
                if ok and part is None:
                    self.s3[key] = {"uid": owner, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                    "etag": md5.hexdigest(), "parts": 1}
                elif ok:
                    s["parts"][part] = (md5.digest(), raw)
                self.s3_puts.setdefault(owner, []).append({"t": now, "key": key, "part": part, "size": len(raw),
                                                           "md5": md5.hexdigest(), "ok": ok})
            if not ok:
                h._record(owner, "PUT /s3/{key}", 403, "<Error><Code>AccessDenied</Code></Error>", "application/xml")
            else:
                self._s3_ok(h, owner, md5.hexdigest())
            return True
        if method == "POST" and u.path == "/api2/v2/upload/signed/finish":
            body = json.loads(raw or b"{}")
            key = str(body.get("key") or "")
            with fake.lock:
                s = self._s3_up.get(key)
                got = s["parts"] if s else {}
                n = s["rec"]["parts"] if s else 0
                named = [(int(p.get("PartNumber") or 0), str(p.get("ETag") or "").strip('"'))
                         for p in body.get("parts") or []]
                ok = (s is not None and s["uid"] == uid and body.get("uploadId") == s["rec"]["upload_id"]
                      and sorted(got) == list(range(1, n + 1))
                      and named == [(p, got[p][0].hex()) for p in range(1, n + 1)])
                if ok:
                    sha = hashlib.sha256()
                    for p in range(1, n + 1):
                        sha.update(got[p][1])
                    etag = f"{hashlib.md5(b''.join(got[p][0] for p in range(1, n + 1))).hexdigest()}-{n}"
                    self.s3[key] = {"uid": uid, "size": sum(len(got[p][1]) for p in got),
                                    "sha256": sha.hexdigest(), "etag": etag, "parts": n}
                    s["parts"] = {}
                    s["rec"]["finished"] = True
            if not ok:
                h._record(uid, route, 400, INVALID_INPUT)
            else:
                h._record(uid, route, 200, {"ETag": f'"{etag}"'})
            return True
        if method == "POST" and u.path == "/convert/file/upload":
            f = _form(h.headers.get("Content-Type") or "", raw)
            key, location = f.get("file[Key]", ""), f.get("file[Location]", "")
            with fake.lock:
                s, obj = self._s3_up.get(key), self.s3.get(key)
                owner = s["uid"] if s else ""
                token_ok = s is not None and f.get("file[uploadToken]") == s["rec"]["token"]
                ok = token_ok and obj is not None
                pid = f"{next(fake._ids):x}{hashlib.md5(key.encode()).hexdigest()[:16]}" if ok else None
                claim = {"t": now, "account": owner, "key": key, "etag": f.get("file[ETag]", "").strip('"'),
                         "location": location, "bucket": f.get("file[Bucket]"), "name": f.get("file[name]", ""),
                         "secure": f.get("file[secure]"), "token_ok": token_ok, "processId": pid,
                         "object": dict(obj) if obj else None, "user": f.get("additional[user]"),
                         "fields": sorted(f)}
                self.claims.setdefault(owner, []).append(claim)
                if ok:
                    self._by_pid[pid] = claim
                    thumb = next(fake._ids)
            if not ok:
                h._record(owner, route, 400, INVALID_INPUT)
            else:
                h._record(owner, route, 200, {
                    "processId": pid, "host": "convert-slop", "sourceUrl": location,
                    "extra": f"slop-extra-{pid}", "thumbs": [{"id": thumb}], "files": [], "success": True})
            return True
        pm = _POST_ONE.fullmatch(u.path)
        if pm and method in ("GET", "DELETE"):
            post_id = int(pm.group(1))
            with fake.lock:
                post = next((p for p in fake.posts.get(uid, ()) if p["id"] == post_id), None)
                if any(c["id"] == post_id for c in self.carriers.get(uid, ())):
                    post = None
                if post is not None:
                    self._mint_referenced(uid)
                    ids = [self._vault_by_pid[str(mf["processId"])] for mf in post.get("mediaFiles") or ()
                           if isinstance(mf, dict) and str(mf.get("processId")) in self._vault_by_pid]
                    listed = [dict(fake.vault[uid][v]) for v in ids]
                    random.Random(post_id).shuffle(listed)  # OF's listing order is arbitrary (docstring)
                    if method == "DELETE":
                        self.carriers.setdefault(uid, []).append({"t": now, "id": post_id, "media_ids": ids})
            if post is None:
                h._record(uid, route, 404, {"error": {"code": 0, "message": "Post not found"}})
            elif method == "DELETE":
                h._record(uid, route, 200, {"success": True})
            else:
                h._record(uid, route, 200, {"id": post_id, "text": post.get("text") or "",
                                            "postedAt": post.get("postedAt"), "media": listed,
                                            "mediaCount": len(listed)})
            return True
        return False
