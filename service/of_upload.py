"""OFClient's media upload: hash dedupe, signed S3 multipart, the convert claim,
and vault materialization through a carrier post or a fan message; plus the
upload constants and pure helpers. One part of `of_client.OFClient`; of_client
re-exports every name here.

Module attributes tests patch (`of_client.requests`,
`of_client._CARRIER_MISSING_GRACE_S`) are read through `_oc` at call time."""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor as _Pool
from pathlib import Path
from typing import Any, NamedTuple


# Media upload (see upload_media). 5 MiB is S3's minimum for a non-final part
# and what OF's own web client uses, so it also decides where OF switches the
# signed/create response from `putUrl` to `keys[]`.
# DO NOT CHANGE THIS. The vault dedupe key IS the S3 multipart ETag, and that
# value is a mathematical function of the part size: `md5(concat of the parts'
# md5 digests)-<part count>`. Raising it to 16 MiB to cut the part count would
# silently invalidate every `GET /vault/media/hash` lookup for every file over
# one part — no error, just a permanent re-upload of everything already in the
# vault. Throughput comes from _PART_CONCURRENCY instead.
_PART_SIZE = 5 * 1024 * 1024
_HASH_CHUNK = 1024 * 1024
_S3_BASE = "https://of2transcoder.s3-accelerate.amazonaws.com/"
# Parts uploaded at once. A single S3 stream is usually throttled well below a
# server's uplink, so this is where the wall-clock win is on a fast box; on a
# home connection the uplink saturates first and the setting barely matters.
# Peak memory is this x _PART_SIZE (8 x 5 MiB = 40 MB at the default), because
# each worker reads only its own slice from its own file handle. 8 rather than 4
# because the part size is pinned at 5 MiB (see above), which makes the HAR's
# largest upload 474 parts — concurrency is the only knob left for wall-clock.
# That 40 MB is PER UPLOAD, not per process. `vault_upload` takes its import
# lock per ACCOUNT, so N accounts importing at once is N x 40 MB of relay RSS —
# which is the number this comment exists to bound, so budget it that way.
_PART_CONCURRENCY = int(os.environ.get("VAULT_UPLOAD_PART_CONCURRENCY") or 8)
# OnlyFans throttles POST /posts to about one per ten seconds — measured live
# when a batch of small files tripped `400 "Please allow 10 seconds"`. This is
# the floor a bulk import paces itself against, per CARRIER — which is why
# vault_upload puts many files' claims on one.
_CARRIER_MIN_GAP_S = 11
# How long a carrier that lists some of its claims waits for the rest before
# reading what it has. See materialize_to_vault.
_CARRIER_MISSING_GRACE_S = 30
# How long to wait on the convert claim. FLAT, not scaled by file size.
#
# THIS COMMENT IS THE CANONICAL RECORD OF THE HAR EVIDENCE. It was previously
# retold in full at eight sites, and when the "~1.4s" figure in it turned out to
# be an inference rather than a measurement, all eight were wrong at once. Every
# other place that leans on this capture now cites `_CONVERT_TIMEOUT_S` instead
# of restating the numbers — the one deliberate exception is the operator-facing
# note in `_claim_uploaded`, which spells a figure out because its reader cannot
# follow a code reference.
#
# This used to be `max(timeout,120) + (size/100MB)*60` — about 25 minutes for a
# 2.31 GiB file, doubled to ~50 on the retry — on the theory that convert's
# response time scales with the object. A HAR of the real OF web client says it
# does not: the convert call is metadata-only (~1.8 KB of form fields, NO
# bytes), and for that same 2.31 GiB .mp4 it answered success in ~9 s wall
# clock, 8.9 s of it server wait (HAR entry: time 9269.7 ms, timings.wait
# 8942.8 ms). Do NOT quote the `duration: 1395` field in that response body as
# a latency — the protocol note records it as an inference about server-side
# processing, not a measurement.
#
# The ceiling that actually bounds this wait is convert's OWN nginx, which
# gives up on its upstream at a fixed ~60 s: the twelve 504s the 443 MB .mov
# drew all came back in 60.1-60.4 s. So 120 s is roughly double the longest
# answer convert will ever give, and waiting longer buys nothing while costing
# an hour of a batch.
_CONVERT_TIMEOUT_S = int(os.environ.get("VAULT_CONVERT_TIMEOUT_S") or 120)
# The carrier post's text, and how far out it is scheduled. Module-level and
# public because they are the ONE handle a cleanup has on a carrier that was
# created but never recorded: a scheduled post carrying this text belongs to an
# import, and nothing else on the account ever writes it. Anything that mints,
# sweeps or probes carriers must use THESE, not a copy — a second spelling is a
# carrier no sweep can find. See vault_upload.sweep.
VAULT_MARKER = "FASTT VAULT UPLOAD — DO NOT PUBLISH — SAFE TO DELETE"
CARRIER_DAYS = 30


def convert_rejected(exc: BaseException) -> bool:
    """Did `convert.onlyfans.com` answer a GATEWAY error, as opposed to hanging?

    This distinction is the whole retry policy. A 504 from convert's nginx is
    the transcoder REFUSING an object after a fixed ~60s upstream timeout — the
    HAR shows twelve of them on one .mov while the big .mp4 in the same capture
    was answered first time (figures: `_CONVERT_TIMEOUT_S`). More patience
    cannot fix it, so a 504 must fail fast; only an actual transport timeout is
    worth a retry.

    Asked at BOTH decision sites — the inline retry in `upload_media` and the
    claim-retry loop in `upload_claim` — so that "is this worth waiting on?"
    has one answer. The loop cannot catch an exception (`_claim_uploaded`
    returns its failure as data), so it reads the `rejected` flag that function
    sets from this same predicate.
    """
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code in (502, 503, 504):
        return True
    # No capture group: the status is not extracted, only matched. The
    # alternation has to be grouped to sit under `\b`.
    return bool(re.search(r"convert register failed: (?:50[234])\b", str(exc)))


def post_is_gone(exc: BaseException) -> bool:
    """Does this failed `delete_post` mean the post is already not there?

    A carrier OnlyFans says does not exist cannot publish, so a 404 (or a 410)
    is the delete SUCCEEDING, not failing. Treating it as a failure is how a
    carrier that was in fact deleted — by a `finally` whose caller then raised
    before it could record the fact — became a permanent "N scheduled posts
    could not be removed" banner that no retry could ever clear.
    """
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code in (404, 410):
        return True
    # `request_json` formats its message as "<status> for <url>\n<body>"; the
    # response object is normally attached, this is the belt to that braces.
    return bool(re.match(r"^\s*(404|410)\b", str(exc)))


def s3_etag_and_md5(path: "str | Path", part_size: int = _PART_SIZE) -> tuple[str, str, int]:
    """`(dedupe_key, md5_hex, size)` for a file, in one streaming pass.

    `dedupe_key` is the ETag S3 will assign, which is what OF's
    `GET /vault/media/hash` indexes — VERIFIED LIVE 2026-09-07:
      * ≤ one part  → the plain md5 hex (S3's single-PUT ETag)
      * > one part  → `md5(concat of the parts' md5 DIGESTS)-<part count>`
    A 12.3 MB three-part upload was found by its `…-3` ETag and NOT by its
    file md5, so anything that dedupes on md5 alone silently stops working the
    moment a file crosses 5 MiB.

    `md5_hex` is still returned because the story-dupe hide-cleanup indexes on
    it. Streaming, never `read_bytes()`: this runs inside the relay that also
    serves chat.
    """
    import hashlib
    md5 = hashlib.md5()
    parts: list[bytes] = []
    size = 0
    with open(path, "rb") as fh:
        while chunk := fh.read(part_size):
            md5.update(chunk)
            parts.append(hashlib.md5(chunk).digest())
            size += len(chunk)
    md5_hex = md5.hexdigest()
    if len(parts) <= 1:
        return md5_hex, md5_hex, size
    return f"{hashlib.md5(b''.join(parts)).hexdigest()}-{len(parts)}", md5_hex, size


class UploadClaim(NamedTuple):
    """`OFClient.upload_claim`'s answer — exactly one of three outcomes:

      * fresh bytes, claimed: `media` — the one claim object a post or a
        message references (with `dedupe_key`/`size`, the S3 ETag and byte
        size the vault hash is keyed on) — waits for a carrier or a fan send
        to give it a vault id;
      * already in the vault (a dedupe hit): `vault_id`, `hidden` if the
        creator removed it there;
      * failed: neither, and `note` says why.

    `retries` is how many times the claim was re-run on bytes already in S3."""
    media: dict | None = None
    dedupe_key: str | None = None
    size: int | None = None
    vault_id: int | None = None
    hidden: bool = False
    note: str | None = None
    retries: int = 0


def remove_carrier(client, post_id) -> Any:
    """`client.delete_post(post_id)` for a vault import's carrier post (a
    scheduled post that publishes ~30 days out unless deleted), let through the
    deactivated-Creator write gate. Deactivating mid-import, or before the
    hourly sweep found an orphan, must not leave it to go live on the feed.
    The flag is set here, in whatever thread runs the delete, so a pacer that
    hops threads cannot drop it."""
    token = _CARRIER_REMOVAL.set(True)
    try:
        return client.delete_post(post_id)
    finally:
        _CARRIER_REMOVAL.reset(token)


class UploadMixin:
    """Needs `_Transport` (`get`, `post_json`, `_proxy_retry`, `http`, `user_id`,
    `user_agent`, `timeout_s`); calls ReadsMixin `me`/`get_messages`/`get_post`
    and SendsMixin `create_post`/`send_message`."""

    # ── Media upload ───────────────────────────────────────────
    # Captured live via Playwright on chat 3269723 (incogniton_fingerprint_test.png
    # resized to 407x1920). Three steps:
    #
    #   1) GET  /api2/v2/vault/media/hash?h={md5}&size={bytes}  → 404 = new,
    #          200 = exists (returns the matching media id, skipping re-upload).
    #   2) POST /api2/v2/upload/signed/create  { key, parts, contentType, secure }
    #          → { putUrl, getUrl }   — both presigned for `of2transcoder.s3-accelerate.amazonaws.com`
    #   3) PUT  {putUrl} with raw file bytes → 200, empty body + S3 etag
    #
    # The `key` field is built CLIENT-SIDE and includes the future vault media
    # id as a path segment, e.g.:
    #   upload/<uuid4>/<12-digit-numeric-id>/<filename>
    # OF picks the numeric id by `Math.floor(Math.random() * 1e12)` (looked at
    # bundle). Since 2026-10 OF rewrites that key (creator id spliced in)
    # and returns it with an `uploadToken`; the claim must use THOSE — see
    # request_signed_upload. After the S3 PUT, OF's transcoder auto-creates the vault record
    # asynchronously — no explicit finalize XHR. To use the new media in a
    # message: send `mediaFiles=[<that-numeric-id>]` in /chats/{id}/messages.
    #
    # NB: requires the `curl_cffi.requests` session (self.http) for the OF
    # calls (TLS impersonation) but the S3 PUT works with stock requests too —
    # we use self.http for consistency.

    def vault_media_lookup_hash(self, md5_hex: str, size: int) -> dict | None:
        """GET /api2/v2/vault/media/hash — dedupe check before upload.
        Returns the existing vault media dict if found, None on 404."""
        url = f"{API_BASE}/vault/media/hash"
        params = {"h": md5_hex, "size": size}
        r = self.get(url, params=params)
        if r.status_code == 404:
            return None
        if not r.ok:
            raise OFAPIError(f"{r.status_code} for {r.url}\n{r.text[:500]}", response=r)
        return r.json()

    def request_signed_upload(self, *, key: str, content_type: str,
                              parts: int = 1, secure: bool = False) -> dict:
        """POST /api2/v2/upload/signed/create → the presigned S3 target(s).

        `key` is OF's path-style id: `upload/<uuid>/<random>/<filename>`.

        The response SHAPE depends on `parts`, and the two are mutually
        exclusive — VERIFIED LIVE 2026-09-07 with parts=3:
          parts == 1 → {putUrl, getUrl}                  single PUT
          parts  > 1 → {uploadId, keys:[{part, putUrl}], getUrl}  and NO putUrl
        So a caller that asks for multipart must not look for `putUrl`, and
        must follow up with finish_signed_upload() once every part is stored.

        Since 2026-10 OF also answers with `key` and `uploadToken` (VERIFIED
        LIVE 2026-10-16). `key` is OUR key with the creator's id spliced in
        (`upload/<userId>/<uuid>/<random>/<filename>`) and is where the bytes
        actually land; convert refuses a claim that names our key or omits the
        token with 400 "Invalid input.". OF's web client sends `userPrefix`
        and reads both back as `{key: d = ourKey, uploadToken}`; so does
        upload_media.
        """
        return self.post_json(
            f"{API_BASE}/upload/signed/create",
            json_body={
                "key": key,
                "parts": parts,
                "contentType": content_type,
                "secure": secure,
                "userPrefix": "upload",
            },
        )

    def finish_signed_upload(self, *, key: str, upload_id: str,
                             parts: list[dict], secure: bool = False) -> dict:
        """POST /api2/v2/upload/signed/finish — completes a multipart S3 upload.

        `parts` is `[{"ETag": <etag>, "PartNumber": <n>}, ...]` in PartNumber
        order. Returns `{ETag: <etag of the assembled object>}`.

        That assembled ETag is S3's multipart form — `md5(concat of part
        md5s)-<count>` — and is NOT the md5 of the file. Callers that need a
        dedupe handle must keep the source md5 separately; see upload_media.
        """
        return self.post_json(
            f"{API_BASE}/upload/signed/finish",
            json_body={
                "key": key,
                "uploadId": upload_id,
                "parts": parts,
                "secure": secure,
                "userPrefix": "upload",
            },
        )

    # ANSWERED (2026-09-07). The open question here used to be why a stored S3
    # object could not be sent as `mediaFiles=[<numeric id>]`: OF binds an
    # upload through the convert claim, not through the S3 key. The missing
    # step was `convert_register` below, whose `{processId, host, extra}` is
    # what `mediaFiles` actually wants; and a claim only becomes a VAULT item
    # once something references it — see materialize_to_vault. upload_media →
    # materialize_to_vault, with upload_claim wrapping the first half.

    def convert_register(self, *, s3_etag: str, s3_location: str, s3_key: str,
                         s3_bucket: str, filename: str, secure: bool = False,
                         upload_token: str | None = None,
                         watermark_text: str | None = None,
                         watermark_position: str = "bottom_right",
                         upload_args: dict | None = None,
                         timeout_s: int | None = None) -> dict:
        """POST https://convert.onlyfans.com/file/upload (the metadata-claim
        step OF JS performs after a successful S3 PUT, on dedupe miss).

        Sends FormData with `file[ETag/Location/Key/Bucket/name/uploadToken/secure]` +
        the preset fields from /users/me.upload.geoUploadArgs, plus an
        optional watermark. Response carries `{processId, host, sourceUrl,
        extra, files, ...}` — those fields go verbatim into the next
        /chats/{id}/messages or /posts body's `mediaFiles[].`

        Important: this endpoint runs with `withCredentials: false` in OF's
        JS — no cookies. It does require Origin: https://onlyfans.com and a
        Referer; we send both via curl_cffi's chrome-impersonation defaults
        plus an explicit Origin.
        """
        try:
            from curl_cffi import CurlMime
        except ImportError as e:
            raise RuntimeError("curl_cffi.CurlMime missing — pip install curl_cffi") from e

        args = upload_args or {}
        mp = CurlMime()
        # Preset / control fields (booleans become "true"/"false" strings —
        # FormData semantics, OF's JS does Object.entries(formdata) so we
        # match by stringifying truthy → "true").
        for k, v in (args.items() if args else ()):
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    mp.addpart(name=f"{k}[{sub_k}]", data=str(sub_v))
            elif isinstance(v, bool):
                mp.addpart(name=k, data="true" if v else "false")
            elif v is not None:
                mp.addpart(name=k, data=str(v))

        # The file reference — points at the S3 object we just PUT.
        mp.addpart(name="file[ETag]", data=f'"{s3_etag}"')
        mp.addpart(name="file[Location]", data=s3_location)
        mp.addpart(name="file[Key]", data=s3_key)
        mp.addpart(name="file[Bucket]", data=s3_bucket)
        mp.addpart(name="file[name]", data=filename)
        # signed/create's `uploadToken`, echoed back in OF's own field order.
        if upload_token:
            mp.addpart(name="file[uploadToken]", data=upload_token)
        mp.addpart(name="file[secure]", data="true" if secure else "false")

        # Optional watermark (OF JS appends only if user opts in)
        if watermark_text:
            mp.addpart(name="watermark[text]", data=watermark_text)
            mp.addpart(name="watermark[position]", data=watermark_position)

        url = "https://convert.onlyfans.com/file/upload"
        r = self._proxy_retry(lambda: self.http.post(
            url, multipart=mp,
            headers={
                "Origin": "https://onlyfans.com",
                "Referer": "https://onlyfans.com/",
                "Accept": "application/json, text/plain, */*",
                "Sec-Fetch-Site": "same-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "User-Agent": self.user_agent,
            },
            timeout=timeout_s or max(self.timeout_s, 60),
        ), what="convert-upload")
        if not r.ok:
            raise OFAPIError(f"convert register failed: {r.status_code} {r.text[:400]}", response=r)
        return r.json()

    # ── convert-claim helpers ──────────────────────────────────
    # Shared by upload_media and the claim retry. They were duplicated once and
    # drifted; the claim body is one thing, so it has one owner.

    def _upload_args(self) -> dict:
        """The `geoUploadArgs` preset convert expects, with OF's own fallback."""
        me = self.me()
        return (me.get("upload") or {}).get("geoUploadArgs") or {
            "preset": "of_beta",
            "needThumbs": True,
            "additional": {"user": self.user_id},
        }

    @staticmethod
    def _send_with(claim: dict, filename: str) -> dict:
        """The `mediaFiles` entry OF's JS builds from a convert response:
        `{processId, host, name}` plus `extra` and `thumbId` when present."""
        out = {"processId": claim.get("processId"),
               "host": claim.get("host"), "name": filename}
        if "extra" in claim:
            out["extra"] = claim["extra"]
        if claim.get("thumbs"):
            out["thumbId"] = (claim["thumbs"][0] or {}).get("id")
        return out

    def upload_media(self, file_path: str | Path, *,
                     content_type: str | None = None,
                     check_dedupe: bool = True,
                     watermark_text: str | None = None) -> dict:
        """Upload a single file and register it with OF. Returns either:

        Dedupe-hit shape (file already in vault):
          {ready: true, vault_id: <int>, deduped: true, send_with: [<vault_id>], ...}

        Fresh-claim shape (file new, claim registered):
          {ready: true, vault_id: null, deduped: false,
           send_with: [{processId, host, name, ...}],  # use this in mediaFiles
           process_id, host, source_url, ...}

        On any failure: ready=false plus a `note` explaining what to do.

        Full flow:
          1. S3 ETag + size → GET /vault/media/hash (dedupe). Hit → done with
             `vault_id`. The handle is the ETag, NOT the file md5: they differ
             the moment an upload goes multipart (see s3_etag_and_md5). A hit
             may be a HIDDEN vault item — `hidden` says so.
          2. Miss → POST /upload/signed/create. One part → `putUrl`; more than
             one → `keys[]` of per-part URLs and NO putUrl.
          3. PUT the bytes to S3 — every part concurrently when multipart, then
             /upload/signed/finish to assemble them.
          4. POST https://convert.onlyfans.com/file/upload with FormData
             pointing at the S3 object (NO bytes — just etag/Location/Key/
             Bucket/name + preset fields from /users/me.upload.geoUploadArgs).
             Response contains {processId, host, sourceUrl, extra, ...} —
             these go verbatim into mediaFiles in subsequent send/post calls.

        Caller must pass `mediaFiles=result["send_with"]` straight to
        send_message() / create_post() / etc. Don't try to interpret it.
        """
        import hashlib, mimetypes, time, uuid as _uuid, random
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        # Hash by streaming, never `path.read_bytes()`: a bulk vault import runs
        # inside the relay that also serves chat, and a 1 GB file read whole was
        # 1 GB of RSS before a single byte moved.
        #
        # Two hashes, one pass. `md5_hex` is the plain file digest (kept for the
        # story-dupe hide-cleanup, which indexes on it). `dedupe_key` is the S3
        # ETag, which is what OF's /vault/media/hash actually indexes — VERIFIED
        # LIVE 2026-09-07: a 12.3 MB three-part upload was found by ETag
        # `…-3` and NOT by its md5. The two coincide only for a single-part
        # upload, which is why md5 looked correct until multipart existed.
        dedupe_key, md5_hex, size = s3_etag_and_md5(path)
        ct = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        filename = path.name

        # Step 1: dedupe — if OF already has this file's bytes, we're done.
        if check_dedupe:
            existing = self.vault_media_lookup_hash(dedupe_key, size)
            if existing:
                vault_id = existing.get("id") or existing.get("mediaId")
                # A hit can be a vault item the creator REMOVED. OF's remove is
                # `hide_vault_media`, which is one-way and leaves the bytes (and
                # therefore the ETag) indexed forever — so re-uploading the same
                # file can never bring it back, and a caller that reports this
                # as "already in vault" is telling the operator the file is
                # somewhere they cannot see it. Surface the flag; the caller
                # decides what to say.
                hidden = bool(existing.get("hidden") or existing.get("isHidden"))
                return {
                    "vault_id": vault_id,
                    "hidden": hidden,
                    "ready": True,
                    "send_with": [vault_id],
                    "upload_key": None,
                    "etag": dedupe_key,
                    "md5": md5_hex,
                    "dedupe_key": dedupe_key,
                    "size": size,
                    "filename": filename,
                    "deduped": True,
                    "existing": existing,
                    "note": (f"dedupe hit — vault_id {vault_id}"
                             + (" (HIDDEN in the vault)" if hidden else "")),
                }

        # Step 2: request the presigned S3 target(s). Anything over one part
        # size goes multipart — OF hands back per-part URLs and expects a
        # `signed/finish` to assemble them.
        # OF's JS builds the key as `upload/<uuid4>/<Math.random()*Date.now()>/<filename>`.
        random_id = int(random.random() * (time.time() * 1000))
        key = f"upload/{_uuid.uuid4()}/{random_id}/{filename}"
        part_count = max(1, -(-size // _PART_SIZE))   # ceil
        signed = self.request_signed_upload(
            key=key, content_type=ct, parts=part_count, secure=False)
        # OF stores the bytes under ITS key, not ours (it splices the creator id
        # in), and convert only accepts a claim naming that key plus the
        # `uploadToken` — see request_signed_upload. OF's JS: `{key: d = u}`.
        key = signed.get("key") or key
        upload_token = signed.get("uploadToken")
        part_urls = signed.get("keys")
        multipart = isinstance(part_urls, list) and bool(part_urls)

        # Step 3: PUT bytes to S3 (presigned — no auth needed beyond URL).
        # Through _proxy_retry like every other egress call: a CONNECT-403 blip
        # fails before any body is sent, and the PUT targets a fixed presigned
        # key, so retrying the same upload is idempotent.
        # Stays proxied: a direct PUT from the relay's one shared IP links accounts.
        def _put(url: str, body: bytes) -> str:
            r = self._proxy_retry(lambda: self.http.put(
                url, data=body,
                headers={"Content-Type": ct},
                timeout=max(self.timeout_s, 300),
            ), what="s3-upload")
            if not r.ok:
                raise OFAPIError(f"S3 PUT failed: {r.status_code} {r.text[:300]}", response=r)
            tag = (r.headers.get("etag") or "").strip('"')
            if not tag:
                raise OFAPIError("S3 PUT returned no ETag — cannot complete the upload")
            return tag

        if multipart:
            by_part = {int(k["part"]): k["putUrl"] for k in part_urls}
            missing = [n for n in range(1, part_count + 1) if n not in by_part]
            if missing:
                raise OFAPIError(
                    f"signed/create returned {len(by_part)} part URLs but "
                    f"{part_count} were requested (missing parts {missing[:5]})")
            # PAIRED WITH `fansly/fansly_shim.py`'s part loop in
            # `FanslyShimClient.upload_media`. The two are deliberately
            # separate — same S3 multipart shape, but different part sizes
            # (5 MiB pinned here by the dedupe ETag, server-chosen there),
            # different error types and different session classes — and they
            # live on sys.path together only inside the running relay. They are
            # NOT accidentally similar: a change to the retry/concurrency rule
            # here should be considered there too.
            #
            # Parts go up concurrently: a single stream to S3 is usually capped
            # well below the box's actual uplink, so on a VPS this is most of
            # the wall-clock win. Peak memory stays bounded at
            # _PART_CONCURRENCY x 5 MiB because each worker opens its OWN file
            # handle and reads only its slice — unlike the reference
            # implementation, which holds the entire file in RAM.
            #
            # Each worker also gets its OWN http session. `self.http` is one
            # curl_cffi Session and is not safe to drive from several threads;
            # an S3 PUT is presigned, so a bare session with the same proxy
            # settings is all a part needs.
            done: list[dict | None] = [None] * part_count

            def _put_part(n: int) -> None:
                sess = _oc.requests.Session(impersonate=IMPERSONATE)
                if self.http.proxies:
                    sess.proxies.update(self.http.proxies)
                try:
                    with path.open("rb") as fh:
                        fh.seek((n - 1) * _PART_SIZE)
                        chunk = fh.read(_PART_SIZE)
                    last: Exception | None = None
                    for _ in range(3):      # short CONNECT-blip tolerance (3 x 0.4 s); _proxy_retry rides longer outages
                        try:
                            r = sess.put(by_part[n], data=chunk,
                                         headers={"Content-Type": ct},
                                         timeout=max(self.timeout_s, 300))
                            if not r.ok:
                                raise OFAPIError(
                                    f"S3 PUT part {n} failed: {r.status_code} {r.text[:200]}",
                                    response=r)
                            tag = (r.headers.get("etag") or "").strip('"')
                            if not tag:
                                raise OFAPIError(f"S3 PUT part {n} returned no ETag")
                            done[n - 1] = {"ETag": tag, "PartNumber": n}
                            return
                        except OFAPIError:
                            raise
                        except Exception as e:      # transport/proxy blip
                            last = e
                            time.sleep(0.4)
                    raise last or OFAPIError(f"S3 PUT part {n} failed")
                finally:
                    try:
                        sess.close()
                    except Exception:   # noqa: BLE001 — closing must not mask the real error
                        pass

            workers = max(1, min(_PART_CONCURRENCY, part_count))
            with _Pool(max_workers=workers) as pool:
                for fut in [pool.submit(_put_part, n) for n in range(1, part_count + 1)]:
                    fut.result()        # re-raises the first failure
            if any(p is None for p in done):
                raise OFAPIError("multipart upload finished with missing parts")
            finished = self.finish_signed_upload(
                key=key, upload_id=signed["uploadId"], parts=done, secure=False)
            # OF may answer with no ETag; the assembled object's tag is then the
            # last part's, which is what OnlyStack falls back to. Either way this
            # value is only ever echoed back to convert as `file[ETag]` — the
            # dedupe handle stays `md5_hex`, computed from the source bytes.
            etag = (finished or {}).get("ETag") or done[-1]["ETag"]
            etag = str(etag).strip('"')
            # OF's JS takes Location/Bucket from part 1's putUrl. `getUrl` is
            # NOT an S3 URL any more (it is upload.onlyfans.com/...).
            put_url = by_part[1]
        else:
            # Single PUT means the whole body in memory — curl_cffi's `data`
            # takes bytes or a BytesIO and reads either whole, so there is no
            # streaming form of this call. That is fine for ONE part (5 MiB),
            # and only for one part: OF answers `parts>1` with `keys[]` and no
            # `putUrl` (VERIFIED live 2026-09-07), so a bare putUrl for a
            # multi-part object is a shape change, not a file to swallow. Fail
            # loudly rather than reading 200 MB into the relay that also serves
            # chat — the one thing this path promises never to do.
            if part_count > 1:
                raise OFAPIError(
                    f"signed/create returned a single putUrl for a "
                    f"{part_count}-part object ({size} bytes). Uploading it "
                    f"would mean holding the whole file in memory; OF's "
                    f"multipart shape must have changed — see request_signed_upload.")
            put_url = signed["putUrl"]
            etag = _put(put_url, path.read_bytes())

        # Step 4: the convert claim. ONE builder — `_claim_uploaded`, the same
        # call upload_claim's retry makes — so the first claim and a retry
        # can never send different bodies. They were built twice once and
        # drifted; the chat path is this method, so it gets the vault's claim.
        #
        # Retry once on a TRANSPORT timeout — the claim references a fixed S3
        # object, so a duplicate claim is inert (nothing ever attaches it) and is
        # far cheaper than re-uploading half a gigabyte.
        #
        # A 504 is NOT retried. It is convert's nginx reporting that the
        # transcoder refused the object — see _CONVERT_TIMEOUT_S for the capture
        # and convert_rejected for the predicate. Retrying it used to cost ~50
        # minutes per file before failing anyway.
        def _claim() -> dict:
            return self._claim_uploaded(
                upload_key=key, etag=etag, filename=filename, size=size,
                upload_token=upload_token, put_url=put_url,
                watermark_text=watermark_text, timeout_s=_CONVERT_TIMEOUT_S)

        got = _claim()
        if (not got["ready"] and not got["rejected"]
                and "timed out" in str(got["error"]).lower()):
            log_of.warning("convert claim timed out after %ss for %s (%.0f MB) "
                           "— retrying once", _CONVERT_TIMEOUT_S, filename, size / 1e6)
            got = _claim()
        if not got["ready"]:
            # Convert step failed — bytes are in S3 but no claim registered.
            # `_claim_uploaded` hands back ANY exception as data, not just
            # OFAPIError: a transport timeout is the most likely failure on a large
            # object, and letting it escape turned a recoverable "claim failed" into
            # an unhandled crash mid-batch.
            #
            # The shape here (ready:false + note) is load-bearing: upload_claim
            # reads it and re-runs ONLY the claim via _claim_uploaded, which is
            # why the S3 bytes are not wasted. Keep both fields.
            #
            # ONE predicate, asked ONCE (inside `_claim_uploaded`): the note below
            # and the `rejected` flag the retry loop reads are two halves of the
            # same answer, and asking twice is how they would ever come to disagree.
            e = got["error"]
            rejected = got["rejected"]
            # The relay log is the only place the claim's shape shows: OF's
            # 400 "Invalid input." names no field. No token value is logged.
            log_of.warning("convert claim failed for %s (%s, %d bytes, %s, key %s, "
                           "uploadToken %s): %s",
                           filename, ct, size, "multipart" if multipart else "one part",
                           key, "present" if upload_token else "MISSING", e)
            if rejected:
                # The "convert it yourself" advice is only true for a file that
                # is NOT already an mp4. On the vault-import path media_prep has
                # usually remuxed the source first, so `filename` is the mp4 it
                # produced — telling the operator to convert that to mp4 is
                # nonsense for the exact case the message was written for.
                fix = (f"The likeliest cause is the CONTAINER: try converting "
                       f"{filename} to .mp4 (h264/aac) and re-importing."
                       if not filename.lower().endswith((".mp4", ".m4v")) else
                       f"{filename} is already an .mp4, so the usual container "
                       f"advice does not apply — this one is worth retrying "
                       f"later.")
                note = (f"bytes are safely in S3 but OnlyFans' transcoder "
                        f"refused to register them ({e}). This is NOT a size "
                        f"problem — a 2.31 GiB .mp4 registers in ~9s. {fix} "
                        f"Nothing needs re-uploading to fix a claim — see "
                        f"_claim_uploaded, upload_key {key}.")
            else:
                note = f"bytes in S3 but claim failed: {e}"
            return {
                "vault_id": None,
                "ready": False,
                # Read by upload_claim's claim-retry loop: a refusal must
                # not be retried, a hang must.
                "rejected": rejected,
                "send_with": None,
                "upload_key": key,
                "upload_token": upload_token,
                "etag": etag,
                "md5": md5_hex,
                "dedupe_key": dedupe_key,
                "size": size,
                "filename": filename,
                "deduped": False,
                "existing": None,
                "note": note,
            }

        send_with = got["send_with"][0]
        return {
            "vault_id": None,           # OF assigns after a successful Send
            "ready": True,
            "send_with": [send_with],
            "upload_key": key,
            "etag": etag,
            # md5 of the *source bytes we uploaded* + size = the key OF's vault
            # dedupe indexes on (GET /vault/media/hash). After the story finishes
            # transcoding, vault_media_lookup_hash(md5, size) resolves the fresh
            # vault item OF filed from this upload — i.e. the story dupe. It does
            # NOT collide with the source vault item (whose stored master has a
            # different md5), so it's a safe handle for later hide-cleanup.
            "md5": md5_hex,
            # What GET /vault/media/hash indexes — the S3 ETag, which differs
            # from md5 once the upload is multipart. Use THIS for dedupe.
            "dedupe_key": dedupe_key,
            "size": size,
            "filename": filename,
            "deduped": False,
            "claim": got["claim"],      # full converter response (for debugging)
            "note": f"claim registered — processId {send_with.get('processId')}",
        }

    # ── Vault materialization ──────────────────────────────────
    #
    # OnlyFans has no "save this upload to my vault" endpoint. VERIFIED LIVE
    # 2026-09-07 against a real account, three ways: a registered claim on its
    # own never becomes a vault item (waited 5 min; `/vault/media/processing`
    # reported idle throughout), and neither `isDelay:false` nor
    # `preset:of_drm` — the only two fields where our convert body differed
    # from a captured OF web upload — changes that. Seven guessed
    # `POST /vault/media*` routes all answer "Route not found".
    #
    # Media enters the vault only when something REFERENCES it. So we attach
    # the claim to a carrier, read the vault id off the carrier, and delete the
    # carrier. A far-future scheduled POST is the carrier of choice:
    #   - it needs no recipient, so it works on an account with zero subscribers
    #   - an unpublished scheduled post is invisible to fans
    #   - `/chats/{id}/messages` (what the OnlyStack reference implementation
    #     uses) is recorded HERE, verified live, as sending IMMEDIATELY despite
    #     `scheduledDate` — see schedule_message. That trick mails a real fan.
    # VERIFIED LIVE: vault id resolved ~1s after the post was created, and the
    # vault item SURVIVES deletion of the carrier post.

    _VAULT_MARKER = VAULT_MARKER

    def materialize_to_vault(self, send_with: list, *,
                             carrier_days: int = CARRIER_DAYS,
                             timeout_s: int = 600,
                             poll_interval_s: float = 2.0,
                             on_carrier=None,
                             on_carrier_intent=None,
                             on_carrier_deleted=None,
                             gate=None) -> dict:
        """Put fresh upload claims into the vault on ONE carrier post.

        `send_with` is one or more claim objects (`upload_claim().media`
        entries). OnlyFans paces post creation (~1 per 10 s), not media per
        post, so a batch import puts many claims on one carrier.

        Returns `{media, carrier_post_id, carrier_deleted}`: `media` is what
        the post listed, `[{id, isReady, ...}]`, in whatever order OnlyFans
        chose. Which id is whose is not this method's to say — see
        `vault_carrier.attribute`.

        TWO hooks, because the dangerous window is the POST itself:

        `on_carrier_intent(marker)` fires BEFORE the create call goes out. It is
        the only record that exists if the response is lost — a timeout, a proxy
        error, a SIGKILL — while OnlyFans went ahead and created the post. A
        carrier nobody recorded is a scheduled post that publishes to the whole
        feed on its date, so this hook is what makes `sweep()` able to look for
        one by `marker` instead of by an id it never learned.

        `on_carrier(post_id)` fires the instant the id IS known, before any
        polling, and narrows the sweep to an exact post.

        `on_carrier_deleted(post_id)` fires from the `finally` the moment the
        carrier is gone. It exists because `carrier_deleted` in the return value
        is not reachable when the body raised — one non-2xx from `get_post`
        during a ten-minute poll and the exception propagates past a delete that
        SUCCEEDED, leaving a record that says "carrier live, never deleted"
        forever and an alarm no retry could clear.

        NEITHER hook's failure is swallowed. If the intent cannot be recorded
        the carrier is never created; if the id cannot be recorded the carrier
        is deleted again and the item fails. Both hooks write to disk, so their
        failure mode is a full or read-only volume — the same condition that
        makes an unrecorded carrier likely in the first place.

        `gate(thunk)` runs each OnlyFans WRITE — the carrier create and its
        delete — through a caller-supplied pacer, defaulting to calling the
        thunk directly. Inside the relay it is the per-account write gate, so a
        carrier can never land in the slot an automation's fan message reserved.

        The carrier is deleted in a `finally`, and `carrier_deleted` says
        whether that actually succeeded — a False there needs operator action.
        """
        import time as _time
        from datetime import datetime, timedelta, timezone

        run = gate or (lambda thunk: thunk())
        posted_at = (datetime.now(timezone.utc)
                     + timedelta(days=carrier_days)).isoformat()
        # MEASURED LIVE: OnlyFans throttles post creation to roughly one per ten
        # seconds and answers `400 {"message":"Please allow 10 seconds"}` when
        # you outrun it — which a batch of small files does easily, since their
        # uploads finish in under a second. Wait it out rather than failing the
        # item: the bytes are already claimed and the retry is nearly free.
        # A `gate` avoids provoking it at all; standalone callers pass none and
        # get this local retry as the backstop.
        if on_carrier_intent is not None:
            # DELIBERATELY NOT wrapped in try/except. This hook is the only
            # record that will exist if the create call's response is lost, and
            # it writes to the same spool volume the import is filling — the
            # realistic failure is ENOSPC or a read-only remount, exactly when a
            # carrier is most likely to be created without being recorded.
            # Swallowing the failure and posting anyway is the F1 hole reopened:
            # a scheduled post nothing can find, publishing to the whole feed on
            # its date. An import that stops here is recoverable; that is not.
            on_carrier_intent(self._VAULT_MARKER)
        resp = None
        for attempt in range(4):
            try:
                resp = run(lambda: self.create_post(
                    self._VAULT_MARKER, media_files=send_with,
                    carrier_posted_at=posted_at, auto_tag=False))
                break
            except OFAPIError as e:
                if "allow 10 seconds" not in str(e) or attempt == 3:
                    raise
                log_of.info("carrier post throttled — waiting %ss (attempt %d/3)",
                            _CARRIER_MIN_GAP_S, attempt + 1)
                _time.sleep(_CARRIER_MIN_GAP_S)
        post_id = resp.get("id") if isinstance(resp, dict) else None
        if post_id is None:
            raise OFAPIError(
                f"vault carrier post returned no id: {str(resp)[:300]}")
        media: list = []
        try:
            if on_carrier is not None:
                # Inside the try, so a hook that cannot record the id still gets
                # the carrier DELETED by the finally below, and the caller is
                # told the item failed. Logging and polling on regardless left a
                # live carrier that nothing on disk knew about.
                on_carrier(post_id)
            # Done the moment every claim is LISTED with an id — ready or not.
            # The id is the real, permanent vault id from its first appearance
            # (MEASURED: a 23-minute video's row appears within seconds and
            # reports isReady=false for many minutes, finishing on its own long
            # after the carrier is gone; even images list isReady=false at
            # first). Waiting for isReady kept a video's neighbours on a live
            # carrier for up to `timeout_s`.
            deadline = _time.time() + timeout_s
            settled_at = None
            while _time.time() < deadline:
                media = [m for m in (self.get_post(post_id).get("media") or [])
                         if m.get("id") is not None]
                if len(media) >= len(send_with):
                    break
                if media:
                    # Some listed, a claim MISSING. A slow row must not be cut
                    # off by its quicker neighbours, but a claim OnlyFans
                    # silently drops — MEASURED LIVE 2026-10-22: a .webp
                    # accepted by convert never appeared on its carrier nor
                    # under its hash — must not hold the rest for `timeout_s`.
                    settled_at = settled_at or _time.time()
                    if _time.time() - settled_at >= _oc._CARRIER_MISSING_GRACE_S:
                        break
                _time.sleep(poll_interval_s)
        finally:
            deleted = False
            try:
                run(lambda: remove_carrier(self, post_id))
                deleted = True
            except Exception as e:
                # "It is not there" is the delete succeeding.
                deleted = post_is_gone(e)
                if not deleted:
                    log_of.error("VAULT CARRIER LEFT BEHIND: post %s could not be "
                                 "deleted (%s) — it PUBLISHES on %s",
                                 post_id, e, posted_at)
            if deleted and on_carrier_deleted is not None:
                # The record has to be right even when the body above is on its
                # way out with an exception: `carrier_deleted` in the return
                # value never arrives on that path, and the on-disk item would
                # keep claiming a live carrier for the rest of the run's life.
                try:
                    on_carrier_deleted(post_id)
                except Exception:  # noqa: BLE001
                    log_of.exception(
                        "vault: could not record that carrier %s was deleted — "
                        "the sweep will re-check it against OnlyFans", post_id)

        return {"media": media, "carrier_post_id": post_id,
                "carrier_deleted": deleted}

    def materialize_via_message(self, send_with: list, fan_id: int, *,
                                dedupe_key: str | None = None,
                                size: int | None = None,
                                polls: int = 5,
                                poll_interval_s: float = 3.0,
                                gate=None) -> dict:
        """Turn a fresh upload claim into a vault id by SENDING it to a fan.

        Infloww's "Link a fan account": "Infloww will automatically send media
        to this account so that it appears in your Creator's vault" — the
        creator and that account must be subscribed to each other, or OnlyFans
        refuses the send (raised as `FanSendRefused`). Unlike the carrier this
        leaves something behind on purpose: a free message in that one chat,
        which is the operator's own choice of fan (usually a test account of
        their own).

        The sent message's media id IS the vault id. It is read off the send's
        answer, else off the chat — a page pinned to the sent message's own id,
        so newer messages cannot push it out of view — a few times (`polls`),
        else by the S3-ETag hash. Bounded on purpose: these reads are unpaced,
        and the send has already happened, so a read that fails is a reason to
        try the hash, never to fail a file whose message went out. Returns
        `{vault_id, still_transcoding, message_id, note}` (no carrier).
        """
        import time as _time

        run = gate or (lambda thunk: thunk())
        try:
            resp = run(lambda: self.send_message(fan_id, "", media_files=send_with,
                                                 auto_tag=False))
        except OFAPIError as e:
            r = e.response
            body = (r.text if r is not None else str(e)) or ""
            if (r is not None and r.status_code == 403) or "cannot send" in body.lower():
                raise FanSendRefused(
                    f"OnlyFans refused the send to fan {fan_id} — the creator "
                    f"and that account must be subscribed to each other "
                    f"({body[:200]})") from e
            raise
        msg_id = resp.get("id") if isinstance(resp, dict) else None

        def ids_of(msg: dict) -> tuple[int | None, bool]:
            media = [m for m in (msg.get("media") or []) if m.get("id") is not None]
            if not media:
                return None, False
            return media[0]["id"], media[0].get("isReady") is False

        vault_id, transcoding = ids_of(resp if isinstance(resp, dict) else {})
        for _ in range(polls if msg_id is not None else 0):
            if vault_id is not None:
                break
            _time.sleep(poll_interval_s)
            try:
                # `id` is an upper bound ("older than"), so msg_id + 1 puts the
                # sent message at the top of the page whatever came after it.
                page = self.get_messages(fan_id, limit=10, before_id=int(msg_id) + 1)
            except Exception as e:  # noqa: BLE001 — the send already happened
                log_of.warning("vault fan send: chat read for message %s failed: %s",
                            msg_id, e)
                continue
            for m in (page.get("list") or []) if isinstance(page, dict) else []:
                if m.get("id") == msg_id:
                    vault_id, transcoding = ids_of(m)
                    break
        if vault_id is None and dedupe_key and size:
            try:
                hit = self.vault_media_lookup_hash(dedupe_key, size)
            except Exception as e:  # noqa: BLE001 — same: never fail a sent file
                log_of.warning("vault fan send: hash lookup failed: %s", e)
                hit = None
            if hit:
                vault_id = hit.get("id")
        return {
            "vault_id": vault_id,
            "still_transcoding": bool(vault_id) and transcoding,
            "carrier_post_id": None,
            "carrier_deleted": None,
            "message_id": msg_id,
            "note": (f"vault id {vault_id} (sent to fan {fan_id})" if vault_id
                     else f"sent to fan {fan_id} (message {msg_id}) but no media "
                          f"id surfaced — it is in that chat; the vault id was "
                          f"not found"),
        }

    def _claim_uploaded(self, *, upload_key: str, etag: str, filename: str,
                        size: int = 0, upload_token: str | None = None,
                        put_url: str | None = None,
                        watermark_text: str | None = None,
                        timeout_s: int | None = None) -> dict:
        """The convert claim for bytes already sitting in S3 — THE one claim
        builder. upload_media's first claim and upload_claim's retry both
        come through here, so chat uploads and vault imports send the same body.

        `upload_key` and `upload_token` are what signed/create answered (OF's
        key, not ours — see request_signed_upload). `put_url` is the presigned
        PUT the bytes went to; OF's JS takes `file[Location]` (query stripped)
        and `file[Bucket]` (first host label) from it. A retry has no URL and
        falls back to the same S3 host OF has always handed out.

        THE CHEAP RECOVERY PATH, and it is cheap because the claim is
        metadata-only: ~1.8 KB of form fields naming an S3 object that is
        already there. Nothing is re-uploaded.

        Worth retrying because the two halves fail independently. In the HAR,
        the 443 MB .mov's hashing, signed/create, all 89 part PUTs and
        signed/finish were clean 200s; only convert failed. (That was NOT a size
        limit, as this docstring used to say — the same capture registers a far
        larger .mp4 without complaint; the suspect is the container. See
        `_CONVERT_TIMEOUT_S`.) So the expensive half survives a claim failure
        and this can be re-run on its own.

        It is also worth retrying only a bounded number of times — and a 504 is
        not worth retrying at all: it is a refusal, not congestion. That
        decision belongs to the retry loop, so a failure comes back HERE AS
        DATA: `rejected` is `convert_rejected(e)` for whatever was raised. The
        loop cannot see an exception this function swallowed, which is why it
        used to retry a refused .mov on the full `claim_retry_delays` ladder —
        ~4.3 minutes of waiting for an answer that could not change — while the
        docstrings above it claimed the opposite.

        Private: the retry that uses it lives in upload_claim, so callers
        never have to know that a `ready:false` result is half-recoverable.

        Returns the same `send_with` shape as upload_media, or `ready: False`
        plus `rejected` and a `note`.
        """
        from urllib.parse import urlparse
        location = (put_url or f"{_S3_BASE}{upload_key}").split("?")[0]
        try:
            claim = self.convert_register(
                s3_etag=etag, s3_location=location,
                s3_key=upload_key, s3_bucket=urlparse(location).netloc.split(".")[0],
                filename=filename, secure=False, upload_token=upload_token,
                watermark_text=watermark_text, upload_args=self._upload_args(),
                timeout_s=timeout_s or _CONVERT_TIMEOUT_S,
            )
        except Exception as e:  # noqa: BLE001
            return {"ready": False, "rejected": convert_rejected(e), "error": e,
                    "send_with": None, "upload_key": upload_key,
                    "upload_token": upload_token,
                    "etag": etag, "note": f"claim retry failed: {e}"}

        send_with = self._send_with(claim, filename)
        return {"ready": True, "rejected": False,
                "send_with": [send_with], "upload_key": upload_key,
                "etag": etag, "claim": claim, "deduped": False,
                "dedupe_key": etag, "size": size, "filename": filename,
                "note": f"claim re-registered — processId {send_with.get('processId')}"}

    def upload_claim(self, file_path: str | Path, *,
                     content_type: str | None = None,
                     watermark_text: str | None = None,
                     claim_retry_delays: tuple = (20, 60)) -> UploadClaim:
        """Get a file's bytes onto OnlyFans as far as a CLAIM: dedupe -> S3
        (multipart when needed) -> convert claim. The vault id comes after, from
        whatever references the claim — `materialize_to_vault` (a carrier
        post, shared by many claims) or `materialize_via_message` (a fan send).

        Returns an `UploadClaim`: fresh bytes with `media` set, a dedupe
        hit with `vault_id` set, or a failure with only `note`.

        A claim that failed AFTER the bytes reached S3 is retried
        HERE, on `claim_retry_delays`: the expensive half is done and the S3
        object persists, so re-running just the claim beats re-uploading half a
        gigabyte. A caller re-driving that from outside would have to know the
        three-step flow, and would silently stop matching it the day the flow
        changes. `claim_retry_delays` is skipped entirely when
        `convert_rejected` says convert REFUSED the object rather than hanging
        on it — see the loop below.

        A dedupe hit needs nothing after it. `hidden` is true when that id is
        a vault item the creator REMOVED: hiding is OnlyFans' only delete and
        it is one-way, so the id is real, invisible, and cannot be resurrected
        by re-uploading the same bytes. Reporting such a hit as a plain success
        is how an operator loses media for good — see vault_upload._settle.
        """
        import time as _time

        up = self.upload_media(file_path, content_type=content_type,
                               check_dedupe=True, watermark_text=watermark_text)
        claim_retries = 0
        if not up.get("ready"):
            # Bytes may still be in S3 with only the claim missing (typically a
            # convert 504). Retry the cheap half — metadata only, nothing is
            # re-uploaded. The bound matters: with a flat 120s convert timeout
            # this whole loop is ~5 minutes, where the old size-scaled budget
            # spent ~50 minutes per file before giving up. `up["note"]` from the
            # first failure survives an exhausted loop, so the operator still
            # gets the "likely the container" message.
            #
            # A REFUSAL is not retried at all. `convert_rejected` is the single
            # predicate for "convert answered, and its answer was no"; the first
            # failure already carries it, and `_claim_uploaded` hands the same
            # verdict back as data because this loop has no exception to test.
            # Without that check a refused file burned the whole ladder — 20s +
            # 60s of sleeping on top of three ~60s upstream timeouts, ~4.3
            # minutes per file, for an answer more waiting cannot change.
            if up.get("rejected"):
                claim_retry_delays = ()
            for delay in (claim_retry_delays or ()):
                if not up.get("upload_key"):
                    break
                claim_retries += 1
                log_of.warning("vault: claim failed for %s, retrying in %ss (%d/%d)",
                               up.get("filename"), delay, claim_retries,
                               len(claim_retry_delays))
                _time.sleep(delay)
                again = self._claim_uploaded(
                    upload_key=up["upload_key"], etag=up.get("etag") or "",
                    filename=up.get("filename") or Path(file_path).name,
                    size=up.get("size") or 0, upload_token=up.get("upload_token"),
                    watermark_text=watermark_text)
                if again.get("ready"):
                    up = {**up, **again, "md5": up.get("md5"),
                          "dedupe_key": up.get("dedupe_key") or again.get("dedupe_key")}
                    break
                if again.get("rejected"):
                    # Convert answered no again. Stop; keep the FIRST note,
                    # which is the one that explains the likely cause, rather
                    # than the bare "claim retry failed" from this attempt.
                    log_of.warning("vault: convert refused %s again — not retrying",
                                   up.get("filename"))
                    break
        if not up.get("ready"):
            return UploadClaim(note=up.get("note"), retries=claim_retries)
        if up.get("deduped"):
            return UploadClaim(vault_id=up.get("vault_id"),
                               hidden=bool(up.get("hidden")), retries=claim_retries)
        return UploadClaim(media=up["send_with"][0], dedupe_key=up.get("dedupe_key"),
                           size=up.get("size"), retries=claim_retries)


# Last, not first: of_client imports this module while it loads, and these
# names are read only when a method runs, so either import order works.
import of_client as _oc  # noqa: E402 — module object: patched attrs read at call time
from of_client import (  # noqa: E402
    API_BASE, FanSendRefused, IMPERSONATE, OFAPIError, _CARRIER_REMOVAL, log_of,
)
