from __future__ import annotations

UPLOAD_SHAPE = "each new file: 1 signed/create, ceil(size/5MiB) S3 PUTs, signed/finish iff multipart"
ONE_CLAIM = "each new file: exactly 1 convert claim"
S3_BYTES = "fake S3 holds each new file's exact bytes (sha256)"
DEDUPE_KEY = "per new file the product hashed and answered its S3 ETag as the dedupe key"
CLAIM_ETAG = "per new file the convert claim's ETag == the fake S3 ETag == the harness's S3 ETag"
CLAIM_TARGET = "each convert claim names its S3 object: OF's key + uploadToken, Location / Bucket from the putUrl"
REUPLOAD_ONE = "single-part re-upload of the same bytes: dedupe hit, 0 signed/create, 0 PUT, 0 claim"
REUPLOAD_MULTI = "multipart re-upload of the same bytes: dedupe hit, 0 signed/create, 0 PUT, 0 claim"
SEND = "each send with a fresh claim: 200, one OF message, mediaFiles == the upload's send_with"
IMPORT = "vault import: every item done, one vault id per file (a dupe its earlier id), carriers deleted"
OFFHOST = "no curl_cffi call left loopback; the convert claim reached the fake"
AUDIT_ROWS = "each 2xx upload / send: its audit row (actions); each send: its outbound messages row"
UPLOAD, SEND_ROUTE = "POST /api/of/v2/upload", "POST /api/of/v2/chats/:id/messages"
BUDGET = {r: f"p95 {r} (A + B at --users) within the scenario's P95_MS" for r in (UPLOAD, SEND_ROUTE)}


def _dedupe_uses_md5() -> None:
    import of_upload
    real = of_upload.s3_etag_and_md5

    def md5_as_etag(path, part_size=of_upload._PART_SIZE):
        _key, md5_hex, size = real(path, part_size)
        return md5_hex, md5_hex, size

    of_upload.s3_etag_and_md5 = md5_as_etag


def _convert_claimed_twice() -> None:
    import of_upload
    real = of_upload.UploadMixin.convert_register

    def twice(self, **kw):
        real(self, **kw)
        return real(self, **kw)

    of_upload.UploadMixin.convert_register = twice


def _upload_on_loop() -> None:
    import asyncio

    import of_upload
    import server
    real = of_upload.UploadMixin.upload_media

    def on_loop(self, *a, **kw):
        req = server._request_ctx.get()
        if req is None or req.url.path != "/api/of/v2/upload":
            return real(self, *a, **kw)

        async def inline():
            return real(self, *a, **kw)

        return asyncio.run_coroutine_threadsafe(inline(), server._main_loop).result()

    of_upload.UploadMixin.upload_media = on_loop


def register(Fault) -> dict:
    return {
        "upload-dedupe-uses-md5": Fault(_dedupe_uses_md5, (REUPLOAD_MULTI, DEDUPE_KEY)),
        "upload-convert-claimed-twice": Fault(_convert_claimed_twice, (ONE_CLAIM,)),
        "upload-on-loop": Fault(_upload_on_loop, (BUDGET[UPLOAD], BUDGET[SEND_ROUTE], AUDIT_ROWS)),
    }
