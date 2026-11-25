from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor as _Pool
from pathlib import Path
from typing import Any, NamedTuple


# DO NOT CHANGE: the vault dedupe key is the S3 multipart ETag, a function of part size; changing it silently voids every /vault/media/hash lookup. Throughput comes from _PART_CONCURRENCY.
_PART_SIZE = 5 * 1024 * 1024
_HASH_CHUNK = 1024 * 1024
_S3_BASE = "https://of2transcoder.s3-accelerate.amazonaws.com/"
# Peak memory is this x _PART_SIZE per upload; vault_upload locks per account, so N accounts importing = N x that in relay RSS.
_PART_CONCURRENCY = int(os.environ.get("VAULT_UPLOAD_PART_CONCURRENCY") or 8)
# OF throttles POST /posts to ~1 per 10 s (measured: 400 "Please allow 10 seconds"); the floor a bulk import paces against per carrier.
_CARRIER_MIN_GAP_S = 11
_CARRIER_MISSING_GRACE_S = 30
# Flat, not size-scaled: convert is metadata-only (answered a 2.3 GiB file in ~9 s) and its own nginx 504s at ~60 s, so waiting longer buys nothing.
_CONVERT_TIMEOUT_S = int(os.environ.get("VAULT_CONVERT_TIMEOUT_S") or 120)
# The one handle a cleanup has on an unrecorded carrier: mint, sweep and probe must use this, never a copy.
VAULT_MARKER = "FASTT VAULT UPLOAD — DO NOT PUBLISH — SAFE TO DELETE"
CARRIER_DAYS = 30


# A 504 from convert is the transcoder refusing the object after ~60 s: fail fast; only a transport timeout is worth a retry.
def convert_rejected(exc: BaseException) -> bool:
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code in (502, 503, 504):
        return True
    return bool(re.search(r"convert register failed: (?:50[234])\b", str(exc)))


# A 404/410 on delete_post means the post is already gone: the delete succeeded.
def post_is_gone(exc: BaseException) -> bool:
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code in (404, 410):
        return True
    return bool(re.match(r"^\s*(404|410)\b", str(exc)))


# dedupe_key is the S3 ETag (md5 of part digests + -N when multipart), not the file md5; streams, never read_bytes (runs in the relay that serves chat).
def s3_etag_and_md5(path: "str | Path", part_size: int = _PART_SIZE) -> tuple[str, str, int]:
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
    media: dict | None = None
    dedupe_key: str | None = None
    size: int | None = None
    vault_id: int | None = None
    hidden: bool = False
    note: str | None = None
    retries: int = 0


# Lets the carrier delete through the deactivated-Creator write gate: left alone it publishes ~30 days out.
def remove_carrier(client, post_id) -> Any:
    token = _CARRIER_REMOVAL.set(True)
    try:
        return client.delete_post(post_id)
    finally:
        _CARRIER_REMOVAL.reset(token)


class UploadMixin:


    def vault_media_lookup_hash(self, md5_hex: str, size: int) -> dict | None:
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


    def convert_register(self, *, s3_etag: str, s3_location: str, s3_key: str,
                         s3_bucket: str, filename: str, secure: bool = False,
                         upload_token: str | None = None,
                         watermark_text: str | None = None,
                         watermark_position: str = "bottom_right",
                         upload_args: dict | None = None,
                         timeout_s: int | None = None) -> dict:
        try:
            from curl_cffi import CurlMime
        except ImportError as e:
            raise RuntimeError("curl_cffi.CurlMime missing — pip install curl_cffi") from e

        args = upload_args or {}
        mp = CurlMime()
        for k, v in (args.items() if args else ()):
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    mp.addpart(name=f"{k}[{sub_k}]", data=str(sub_v))
            elif isinstance(v, bool):
                mp.addpart(name=k, data="true" if v else "false")
            elif v is not None:
                mp.addpart(name=k, data=str(v))

        mp.addpart(name="file[ETag]", data=f'"{s3_etag}"')
        mp.addpart(name="file[Location]", data=s3_location)
        mp.addpart(name="file[Key]", data=s3_key)
        mp.addpart(name="file[Bucket]", data=s3_bucket)
        mp.addpart(name="file[name]", data=filename)
        if upload_token:
            mp.addpart(name="file[uploadToken]", data=upload_token)
        mp.addpart(name="file[secure]", data="true" if secure else "false")

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


    def _upload_args(self) -> dict:
        me = self.me()
        return (me.get("upload") or {}).get("geoUploadArgs") or {
            "preset": "of_beta",
            "needThumbs": True,
            "additional": {"user": self.user_id},
        }

    @staticmethod
    def _send_with(claim: dict, filename: str) -> dict:
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
                     watermark_text: str | None = None,
                     thumb_size: str | None = None) -> dict:
        import hashlib, mimetypes, time, uuid as _uuid, random
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        dedupe_key, md5_hex, size = s3_etag_and_md5(path)
        ct = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        filename = path.name

        if check_dedupe:
            existing = self.vault_media_lookup_hash(dedupe_key, size)
            if existing:
                vault_id = existing.get("id") or existing.get("mediaId")
                # A hit can be an item the creator removed: hide is one-way and the ETag stays indexed, so re-uploading never restores it.
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

        random_id = int(random.random() * (time.time() * 1000))
        key = f"upload/{_uuid.uuid4()}/{random_id}/{filename}"
        part_count = max(1, -(-size // _PART_SIZE))
        signed = self.request_signed_upload(
            key=key, content_type=ct, parts=part_count, secure=False)
        # OF stores bytes under ITS key (creator id spliced in); convert only accepts a claim naming it plus uploadToken.
        key = signed.get("key") or key
        upload_token = signed.get("uploadToken")
        part_urls = signed.get("keys")
        multipart = isinstance(part_urls, list) and bool(part_urls)

        # Stays proxied (a direct PUT from the relay's shared IP links accounts); the presigned key is fixed, so a retry is idempotent.
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
            # Paired with FanslyShimClient.upload_media's part loop: a retry/concurrency change here should be considered there too. Each worker uses its own http session (self.http is not thread-safe).
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
                    for _ in range(3):
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
                        except Exception as e:
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
                    fut.result()
            if any(p is None for p in done):
                raise OFAPIError("multipart upload finished with missing parts")
            finished = self.finish_signed_upload(
                key=key, upload_id=signed["uploadId"], parts=done, secure=False)
            etag = (finished or {}).get("ETag") or done[-1]["ETag"]
            etag = str(etag).strip('"')
            put_url = by_part[1]
        else:
            # A bare putUrl for a multi-part object is a shape change: fail loudly rather than read it whole into the relay that serves chat.
            if part_count > 1:
                raise OFAPIError(
                    f"signed/create returned a single putUrl for a "
                    f"{part_count}-part object ({size} bytes). Uploading it "
                    f"would mean holding the whole file in memory; OF's "
                    f"multipart shape must have changed — see request_signed_upload.")
            put_url = signed["putUrl"]
            etag = _put(put_url, path.read_bytes())

        # Retry once on a transport timeout only (the claim names a fixed S3 object); a 504 is convert refusing the object.
        def _claim() -> dict:
            return self._claim_uploaded(
                upload_key=key, etag=etag, filename=filename, size=size,
                upload_token=upload_token, put_url=put_url,
                watermark_text=watermark_text, timeout_s=_CONVERT_TIMEOUT_S,
                thumb_size=thumb_size)

        got = _claim()
        if (not got["ready"] and not got["rejected"]
                and "timed out" in str(got["error"]).lower()):
            log_of.warning("convert claim timed out after %ss for %s (%.0f MB) "
                           "— retrying once", _CONVERT_TIMEOUT_S, filename, size / 1e6)
            got = _claim()
        if not got["ready"]:
            # ready:false + note is load-bearing: upload_claim re-runs only the claim from it.
            e = got["error"]
            rejected = got["rejected"]
            log_of.warning("convert claim failed for %s (%s, %d bytes, %s, key %s, "
                           "uploadToken %s): %s",
                           filename, ct, size, "multipart" if multipart else "one part",
                           key, "present" if upload_token else "MISSING", e)
            if rejected:
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
            "vault_id": None,
            "ready": True,
            "send_with": [send_with],
            "upload_key": key,
            "etag": etag,
            # md5 of the source bytes is the story-dupe hide-cleanup handle; dedupe_key (S3 ETag) is what /vault/media/hash indexes.
            "md5": md5_hex,
            "dedupe_key": dedupe_key,
            "size": size,
            "filename": filename,
            "deduped": False,
            "claim": got["claim"],
            "note": f"claim registered — processId {send_with.get('processId')}",
        }


    _VAULT_MARKER = VAULT_MARKER

    # OF has no save-to-vault route (measured): a claim enters the vault only when referenced, so a far-future carrier post (no recipient).
    # Not a chat message with scheduledDate: OF sends that at once to a real fan.
    def materialize_to_vault(self, send_with: list, *,
                             carrier_days: int = CARRIER_DAYS,
                             timeout_s: int = 600,
                             poll_interval_s: float = 2.0,
                             on_carrier=None,
                             on_carrier_intent=None,
                             on_carrier_deleted=None,
                             gate=None) -> dict:
        import time as _time
        from datetime import datetime, timedelta, timezone

        run = gate or (lambda thunk: thunk())
        posted_at = (datetime.now(timezone.utc)
                     + timedelta(days=carrier_days)).isoformat()
        # Deliberately not wrapped in try/except: this is the only record if the create response is lost, so a failure must stop the import rather than post an unrecorded carrier.
        if on_carrier_intent is not None:
            on_carrier_intent(self._VAULT_MARKER)
        resp = None
        for attempt in range(4):
            try:
                resp = run(lambda: self.create_post(
                    self._VAULT_MARKER, media_files=send_with,
                    carrier_posted_at=posted_at, auto_tag=False))
                break
            except OFAPIError as e:
                import of_write
                if not of_write.is_rate_limited(e) or attempt == 3:
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
            # Inside the try so a hook that can't record the id still gets the carrier deleted by the finally.
            if on_carrier is not None:
                on_carrier(post_id)
            # Done once every claim is listed with an id, ready or not: the id is permanent from first sight (a video stays isReady=false for minutes).
            deadline = _time.time() + timeout_s
            settled_at = None
            while _time.time() < deadline:
                media = [m for m in (self.get_post(post_id).get("media") or [])
                         if m.get("id") is not None]
                if len(media) >= len(send_with):
                    break
                if media:
                    # A claim OF silently drops (measured: an accepted .webp never listed) must not hold the rest for timeout_s.
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
                deleted = post_is_gone(e)
                if not deleted:
                    log_of.error("VAULT CARRIER LEFT BEHIND: post %s could not be "
                                 "deleted (%s) — it PUBLISHES on %s",
                                 post_id, e, posted_at)
            if deleted and on_carrier_deleted is not None:
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
                # `id` is an upper bound, so msg_id + 1 puts the sent message at the top of the page.
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
                        timeout_s: int | None = None,
                        thumb_size: str | None = None) -> dict:
        from urllib.parse import urlparse
        location = (put_url or f"{_S3_BASE}{upload_key}").split("?")[0]
        try:
            args = self._upload_args()
            if thumb_size:
                args = {**args, "additional": {**(args.get("additional") or {}), "customThumbSize": thumb_size}}
            claim = self.convert_register(
                s3_etag=etag, s3_location=location,
                s3_key=upload_key, s3_bucket=urlparse(location).netloc.split(".")[0],
                filename=filename, secure=False, upload_token=upload_token,
                watermark_text=watermark_text, upload_args=args,
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
        import time as _time

        up = self.upload_media(file_path, content_type=content_type,
                               check_dedupe=True, watermark_text=watermark_text)
        claim_retries = 0
        if not up.get("ready"):
            # A refusal is never retried: waiting cannot change convert's answer.
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


import of_client as _oc  # noqa: E402 — module object: patched attrs read at call time
from of_client import (  # noqa: E402
    API_BASE, FanSendRefused, IMPERSONATE, OFAPIError, _CARRIER_REMOVAL, log_of,
)
