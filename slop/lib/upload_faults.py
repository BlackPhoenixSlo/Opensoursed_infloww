"""The media upload's break-it-once faults (scenarios/2026-11-02-of-upload-wire.py) and its check names (the
scenario imports them, so a target can never name a check that does not exist). lib/faults.py merges
`register(Fault)` into FAULTS. Each patches a product function in the relay (service/of_upload.py), never the repo.

Declared gaps: no fault proves CLAIM_ETAG (YAGNI; an open finding in the PR) or AUDIT_ROWS (the open lock
finding's check, the scenario's KNOWN_RED at medium --users=200).
"""
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


def _dedupe_uses_md5() -> None:
    """`s3_etag_and_md5` hands back the plain file md5 as the dedupe key: right for one part, wrong for every
    multipart file (S3's ETag there is md5 of the part digests + `-N`), so its re-upload misses the hash."""
    import of_upload
    real = of_upload.s3_etag_and_md5

    def md5_as_etag(path, part_size=of_upload._PART_SIZE):
        _key, md5_hex, size = real(path, part_size)
        return md5_hex, md5_hex, size

    of_upload.s3_etag_and_md5 = md5_as_etag


def _convert_claimed_twice() -> None:
    """`convert_register` POSTs the claim twice (a retry with no failure); the second answer is used."""
    import of_upload
    real = of_upload.UploadMixin.convert_register

    def twice(self, **kw):
        real(self, **kw)
        return real(self, **kw)

    of_upload.UploadMixin.convert_register = twice


def register(Fault) -> dict:
    return {
        # slop/run of-upload-wire --break
        "upload-dedupe-uses-md5": Fault(_dedupe_uses_md5, (REUPLOAD_MULTI, DEDUPE_KEY)),
        # slop/run of-upload-wire --break --fault=upload-convert-claimed-twice --baseline=slop/evidence/<run-dir>
        "upload-convert-claimed-twice": Fault(_convert_claimed_twice, (ONE_CLAIM,)),
    }
