#!/usr/bin/env python3
"""Vault batch-upload unit tests — plain asserts, no pytest, no network.

Run: ./venv/bin/python service/tests/test_vault_upload.py

These cover the three pieces where a silent wrong answer is expensive and a
live test is too slow or too destructive to run often:

  * the S3 ETag, because it is OF's dedupe key and is NOT the file md5 once an
    upload goes multipart. Getting it wrong doesn't fail loudly — it just
    re-uploads every large file forever.
  * Drive link parsing, because a dropped `resourcekey` turns a working public
    link into a 404 that reads as "not shared".
  * the run-state reconciler, because a run whose process died must report
    `interrupted`, never a permanent `running` that locks the account out.
  * the carrier INTENT record, because it is written before the create call and
    is the only thing that can find a carrier whose response was lost.
  * a dedupe hit on a HIDDEN vault item, because reporting it as done is how an
    operator loses media that no re-upload can ever restore.
  * the Drive API key never reaching a stored error string.
  * the size limits, because an override that stops being honoured halfway
    through the pipeline fails silently and expensively.
  * the intent hook's FAILURE, because swallowing it and posting anyway is the
    unrecoverable case the intent record exists to prevent.
  * the sweep's liveness rule, because deleting a carrier belonging to a run
    that is still polling fails an item whose media is already on OnlyFans —
    and writing the sweep's stale snapshot back loses everything that run wrote.
  * the import lock, because a pid alone is not an identity: container pids are
    recycled, and "locked out forever" is the failure the lock must not cause.
  * the write gate, because it is what keeps a carrier out of the slot an
    automation's fan message reserved.

The live half — carrier minting, multipart PUTs, dedupe against the real vault
— is exercised by scripts/probe_vault_upload.py against a real session.
"""
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gdrive              # noqa: E402
import of_client           # noqa: E402
import vault_carrier      # noqa: E402
import vault_upload        # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  FAIL {label}: got {got!r}, want {want!r}")


def check_raises(label: str, fn, exc) -> None:
    try:
        fn()
    except exc:
        print(f"  ok   {label}")
        return
    except Exception as e:  # noqa: BLE001
        failures.append(f"{label}: raised {type(e).__name__}, want {exc.__name__}")
        print(f"  FAIL {label}: raised {type(e).__name__}, want {exc.__name__}")
        return
    failures.append(f"{label}: did not raise {exc.__name__}")
    print(f"  FAIL {label}: did not raise")


# ── S3 ETag / dedupe key ──────────────────────────────────────────────────
print("\ns3_etag_and_md5")
import hashlib

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    part = 1024                       # tiny parts so the test stays in memory

    one = td / "one.bin"
    one.write_bytes(b"a" * 500)
    key, md5, size = of_client.s3_etag_and_md5(one, part_size=part)
    check("single part: key is the plain md5", key, hashlib.md5(b"a" * 500).hexdigest())
    check("single part: md5 matches key", md5, key)
    check("single part: size", size, 500)

    # Exactly one part is still SINGLE-part — S3 only switches format once a
    # second part exists. An off-by-one here silently breaks 5 MiB files.
    exact = td / "exact.bin"
    exact.write_bytes(b"b" * part)
    key, _, size = of_client.s3_etag_and_md5(exact, part_size=part)
    check("exactly one part: no -N suffix", "-" in key, False)
    check("exactly one part: size", size, part)

    over = td / "over.bin"
    over.write_bytes(b"c" * (part + 1))
    key, md5, size = of_client.s3_etag_and_md5(over, part_size=part)
    expect = (hashlib.md5(
        hashlib.md5(b"c" * part).digest() + hashlib.md5(b"c").digest()
    ).hexdigest() + "-2")
    check("two parts: composite etag", key, expect)
    check("two parts: md5 differs from key", md5 != key, True)
    check("two parts: md5 is still the whole-file digest",
          md5, hashlib.md5(b"c" * (part + 1)).hexdigest())
    check("two parts: size", size, part + 1)

    three = td / "three.bin"
    three.write_bytes(b"d" * (part * 2 + 7))
    key, _, _ = of_client.s3_etag_and_md5(three, part_size=part)
    check("three parts: suffix counts parts", key.rsplit("-", 1)[1], "3")

    empty = td / "empty.bin"
    empty.write_bytes(b"")
    key, md5, size = of_client.s3_etag_and_md5(empty, part_size=part)
    check("empty file: md5 of nothing", key, hashlib.md5(b"").hexdigest())
    check("empty file: size", size, 0)


# ── Google Drive link parsing ─────────────────────────────────────────────
print("\ngdrive.parse_link")
cases = [
    ("https://drive.google.com/file/d/1AbC_dEf/view?usp=sharing", "file", "1AbC_dEf", None),
    ("https://drive.google.com/drive/folders/1Fold_er?usp=drive_link", "folder", "1Fold_er", None),
    ("https://drive.google.com/open?id=1Open_id", "unknown", "1Open_id", None),
    ("https://drive.google.com/uc?export=download&id=1Uc_id&resourcekey=0-AbC",
     "unknown", "1Uc_id", "0-AbC"),
    ("https://docs.google.com/document/d/1Doc_id/edit", "unknown", "1Doc_id", None),
    ("1BareIdLooksLikeThis", "unknown", "1BareIdLooksLikeThis", None),
    # resourcekey must survive on the /file/d/ shape too, not just ?id=
    ("https://drive.google.com/file/d/1Keyed/view?resourcekey=0-XyZ", "file", "1Keyed", "0-XyZ"),
]
for link, kind, fid, rkey in cases:
    ref = gdrive.parse_link(link)
    check(f"kind  {link[:46]:46}", ref.kind, kind)
    check(f"id    {link[:46]:46}", ref.id, fid)
    check(f"rkey  {link[:46]:46}", ref.resource_key, rkey)

for bad in ("", "   ", "https://example.com/file/d/x", "https://drive.google.com/"):
    check_raises(f"rejects {bad!r}", lambda b=bad: gdrive.parse_link(b), gdrive.GDriveError)

print("\ngdrive.is_uploadable")
F = gdrive.DriveFile
for name, mime, ok in (("a.jpg", "image/jpeg", True), ("v.mp4", "video/mp4", True),
                       ("s.mp3", "audio/mpeg", True), ("d.pdf", "application/pdf", False),
                       ("sheet", "application/vnd.google-apps.spreadsheet", False),
                       ("dir", gdrive.FOLDER_MIME, False)):
    got, _ = gdrive.is_uploadable(F("i", name, mime, 1))
    check(f"{name} ({mime})", got, ok)

print("\ngdrive._headers")
check("no resourcekey -> no header", gdrive._headers(gdrive.DriveRef("a", "file")), {})
check("resourcekey -> joined header",
      gdrive._headers(gdrive.DriveRef("a", "file", "k1")),
      {"X-Goog-Drive-Resource-Keys": "a/k1"})


# ── run-state reconciliation ──────────────────────────────────────────────
print("\nvault_upload._reconcile")
running = {"run_id": "r", "account_id": "42", "status": "running"}
vault_upload._live.pop("42", None)
check("running row + dead process -> interrupted",
      vault_upload._reconcile(running)["status"], "interrupted")
vault_upload._live["42"] = "r"
try:
    check("running row + live process -> running",
          vault_upload._reconcile(running)["status"], "running")
    # Liveness is per RUN: an older run of an account that is busy with a NEW
    # import has not somehow come back to life.
    vault_upload._live["42"] = "r2"
    check("older run + account busy with a newer one -> interrupted",
          vault_upload._reconcile(running)["status"], "interrupted")
finally:
    vault_upload._live.pop("42", None)
check("finished row is untouched",
      vault_upload._reconcile({"status": "done", "account_id": "42"})["status"], "done")

# The `mirroring` window. `_mirror_landed` holds the record at `running` on
# purpose while it writes the local mirror, and that window is now up to
# `_VAULT_MIRROR_TIMEOUT_S` of serial OF reads — minutes, sitting exactly where
# every file has ALREADY reached the creator's vault. A restart inside it used
# to report a fully successful import as "the relay restarted mid-run", and the
# operator's documented next move is to re-run the batch onto OF's byte dedupe.
mirroring = {"run_id": "r", "account_id": "42", "status": "running",
             "phase": "mirroring", "terminal_status": "done"}
check("a restart mid-MIRROR reports the run's decided status, not `interrupted`",
      vault_upload._reconcile(mirroring)["status"], "done")
check("…and does not leave a second status field for the next reader",
      vault_upload._reconcile(mirroring)["terminal_status"], None)
check("a failed run that died mirroring is still failed, not interrupted",
      vault_upload._reconcile({**mirroring, "terminal_status": "failed"})["status"],
      "failed")
check("mirroring with nothing decided yet falls back to interrupted",
      vault_upload._reconcile({**mirroring, "terminal_status": None})["status"],
      "interrupted")
check("a stale hint on any OTHER phase is ignored — only mirroring holds a "
      "decided status open",
      vault_upload._reconcile({**mirroring, "phase": "uploading"})["status"],
      "interrupted")

print("\nvault_upload._item")
it = vault_upload._item("x.jpg", "/tmp/x.jpg", "local", 10)
check("starts pending", it["status"], "pending")
check("no carrier yet", it["carrier_post_id"], None)
check("carrier_deleted starts unknown, not False", it["carrier_deleted"], None)

print("\ncaps are readable from the environment")
check("MAX_FILES is an int", isinstance(vault_upload.MAX_FILES, int), True)
check("MAX_BYTES tracks MAX_MB", vault_upload.MAX_BYTES, vault_upload.MAX_MB * 1024 * 1024)

# ── the carrier intent record (the worst failure this feature can cause) ──
# A carrier post that outlives its run publishes to the creator's whole feed.
# The dangerous case is not "we forgot to delete it" — it is "the create call's
# response never came back, so no id was ever learned". The ONLY thing that can
# find such a post is a record written before the POST went out.
print("\nof_client.materialize_to_vault: the intent record precedes the POST")


class _Recorder:
    """A stand-in `self` for the unbound method — no session, no network."""
    _VAULT_MARKER = of_client.VAULT_MARKER
    timeout_s = 30

    def __init__(self, create_raises=None):
        self.order: list[str] = []
        self.deleted: list = []
        self._create_raises = create_raises

    def create_post(self, text, **kw):
        self.order.append(f"create:{text}")
        if self._create_raises:
            raise self._create_raises
        return {"id": 9001}

    def get_post(self, post_id):
        return {"media": [{"id": 555, "isReady": True}]}

    def delete_post(self, post_id):
        self.order.append("delete")
        self.deleted.append(post_id)
        return {}


rec = _Recorder()
seen_intent: list = []
res = of_client.OFClient.materialize_to_vault(
    rec, [{"processId": "p"}],
    on_carrier_intent=lambda marker: (seen_intent.append(marker),
                                      rec.order.append("intent")),
    on_carrier=lambda pid: rec.order.append(f"carrier:{pid}"))
check("intent is recorded BEFORE the create call",
      rec.order[:2], ["intent", f"create:{of_client.VAULT_MARKER}"])
check("the intent carries the marker a sweep searches for",
      seen_intent, [of_client.VAULT_MARKER])
check("the id hook still fires straight after the create",
      rec.order[2], "carrier:9001")
check("the carrier's media come back as listed", res["media"],
      [{"id": 555, "isReady": True}])
check("the carrier is deleted", rec.deleted, [9001])

# The scenario the record exists for: the POST is sent, the response is lost.
lost = _Recorder(create_raises=TimeoutError("read timed out"))
intents: list = []
try:
    of_client.OFClient.materialize_to_vault(
        lost, [{"processId": "p"}],
        on_carrier_intent=lambda marker: intents.append(marker))
except TimeoutError:
    pass
check("a lost create response still leaves an intent behind",
      intents, [of_client.VAULT_MARKER])

# And the sweep can act on it: a marker-bearing scheduled post whose id no run
# owns is deletable, which is the only handle on a carrier nobody recorded.
print("\nvault_upload._sweep_scheduled")


class _Scheduled:
    def __init__(self, rows, fail=False):
        self.rows = rows
        self.deleted: list = []
        self.fail = fail
        self.offsets: list[int] = []

    def schedules_later_post(self, limit=10, offset=0):
        if self.fail:
            raise RuntimeError("session went stale")
        self.offsets.append(offset)
        return {"list": self.rows[offset:offset + limit]}

    def delete_post(self, pid):
        self.deleted.append(pid)
        return {}


sched = _Scheduled([
    {"id": 1, "rawText": f"<p>{of_client.VAULT_MARKER}</p>"},
    {"id": 2, "rawText": "a real scheduled post the creator wrote"},
    {"id": 3, "text": of_client.VAULT_MARKER},
])
got, lost_count, complete = vault_upload._sweep_scheduled(sched, "42", lambda: {"3"})
check("deletes the unrecorded carrier, markup and all", sched.deleted, [1])
check("leaves the creator's own post alone", 2 in sched.deleted, False)
check("leaves a carrier a run already tracks to that run", 3 in sched.deleted, False)
check("reports what it deleted", (got, lost_count), (1, 0))
check("a listing that ran to the end is a COMPLETE scan", complete, True)

# A queue longer than one page: the carrier is 30 days out, so it is on the
# LAST page. Truncating at page 1 reported "clean" and let it publish.
long_queue = ([{"id": 1000 + n, "rawText": "a real post"} for n in range(250)]
              + [{"id": 7, "rawText": of_client.VAULT_MARKER}])
paged = _Scheduled(long_queue)
_page_orig = vault_upload._SCHEDULE_PAGE
vault_upload._SCHEDULE_PAGE = 100
try:
    got, _, complete = vault_upload._sweep_scheduled(paged, "42", lambda: set())
finally:
    vault_upload._SCHEDULE_PAGE = _page_orig
check("pages past the first 100 to reach a far-future carrier", paged.deleted, [7])
check("and says so", (got, complete), (1, True))
check("walking the pages means walking the offsets", paged.offsets, [0, 100, 200])

# "Could not list" must NEVER read the same as "listed, found nothing" — this
# is the only recovery path an unrecorded carrier has.
broke = _Scheduled([], fail=True)
got, lost_count, complete = vault_upload._sweep_scheduled(broke, "42", lambda: set())
check("a failed listing is an incomplete scan", complete, False)
check("and is COUNTED as a failure, so the relay shouts", lost_count, 1)


# ── a dedupe hit on a HIDDEN vault item is never 'done' ───────────────────
print("\nvault_upload._upload_one: hidden dedupe hit")


class _FakeClient:
    """`upload_claim` answers `claim` (a fresh claim by default). A carrier
    records its intent, then raises `raises` or lists `vault_id`."""
    def __init__(self, claim=None, *, vault_id=1, raises=None):
        self.claim = claim or of_client.UploadClaim(media={"processId": "p"})
        self.vault_id, self.raises = vault_id, raises

    def upload_claim(self, path):
        return self.claim

    def materialize_to_vault(self, send_with, *, on_carrier_intent, **_):
        on_carrier_intent(of_client.VAULT_MARKER)
        if self.raises:
            raise self.raises
        return {"media": [{"id": self.vault_id}], "carrier_post_id": None,
                "carrier_deleted": None}


def _one(state, item, client, limits):
    """One file the way a run uploads it: staged, then carried."""
    up = vault_upload._Uploader(state, client, None, None, limits)
    with up.running():
        up.add(item)


def _run_state(td: Path, run_id: str = "42-20260101T000000-abc123") -> dict:
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    (td / run_id).mkdir(parents=True, exist_ok=True)
    return vault_upload._new_state(run_id, "42", None)


_spool_root_orig = vault_upload.SPOOL_ROOT
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    state = _run_state(td)
    media = td / "photo.jpg"
    media.write_bytes(b"x" * 32)
    item = vault_upload._item("photo.jpg", str(media), "local", 32)
    state["items"] = [item]
    client = _FakeClient(of_client.UploadClaim(vault_id=77, hidden=True))
    _one(state, item, client, vault_upload.Limits())
    check("a hidden hit is NOT reported done", item["status"], "skipped")
    check("the operator is told why", "HIDDEN" in (item["error"] or ""), True)
    check("the id is not passed off as an import", item["vault_id"], 77)
    check("a dedupe hit records no carrier intent, because it posts nothing",
          item["carrier_intent"], None)

    # A visible hit is still an ordinary success.
    item2 = vault_upload._item("ok.jpg", str(media), "local", 32)
    state["items"] = [item2]
    _one(state, item2, _FakeClient(of_client.UploadClaim(vault_id=78)),
         vault_upload.Limits())
    check("a visible dedupe hit is done", item2["status"], "done")

    # And the intent SURVIVES a lost response, on disk, in the run record.
    # (The traceback that path logs is the point of the test, not a failure.)
    logging.getLogger("of-relay.vault_upload").setLevel(logging.CRITICAL)
    item3 = vault_upload._item("big.mov", str(media), "local", 32)
    state["items"] = [item3]
    _one(state, item3, _FakeClient(raises=OSError("read timed out")),
         vault_upload.Limits())
    logging.getLogger("of-relay.vault_upload").setLevel(logging.NOTSET)
    check("a failed carrier keeps its intent", bool(item3["carrier_intent"]), True)
    check("…and fails the file", item3["status"], "failed")
    on_disk = vault_upload.read_state(state["run_id"]) or {}
    check("and the intent is on DISK, not just in memory",
          bool((on_disk.get("items") or [{}])[0].get("carrier_intent")), True)

    # ── the max_bytes override is honoured after compression ──────────────
    print("\nvault_upload.Limits: an override reaches the post-compression check")
    small = vault_upload._item("photo.jpg", str(media), "local", 32)
    state["items"] = [small]
    _one(state, small, _FakeClient(),
         vault_upload.Limits(max_bytes=16))
    check("32 bytes is refused by a 16-byte ceiling", small["status"], "skipped")
    check("the message quotes the OVERRIDE, not the module constant",
          "over the 0 MB per-file limit" in (small["error"] or ""), True)
    passing = vault_upload._item("photo.jpg", str(media), "local", 32)
    state["items"] = [passing]
    _one(state, passing, _FakeClient(),
         vault_upload.Limits(max_bytes=1024))
    check("and the same file passes a 1 KB ceiling", passing["status"], "done")
vault_upload.SPOOL_ROOT = _spool_root_orig

# The target-vs-ceiling invariant is only real when media_prep's size-targeted
# pass can actually run. Enforcing it for a run in which `compress()` is never
# called logs a loud error about a situation that cannot arise, which is how
# people learn to scroll past loud errors.
_HATCH_ON = 200 * 1024 * 1024
check("the compression target is forced below the upload ceiling — with the "
      "escape hatch ON",
      vault_upload.Limits(compress_over_bytes=_HATCH_ON,
                          max_bytes=100 * 1024 * 1024,
                          target_bytes=300 * 1024 * 1024).checked().target_bytes
      < 100 * 1024 * 1024, True)
check("a sane pair is left alone",
      vault_upload.Limits(compress_over_bytes=_HATCH_ON,
                          max_bytes=200, target_bytes=100).checked().target_bytes, 100)
check("and with the hatch OFF the same pair is not touched, because nothing "
      "would ever re-encode to that target",
      vault_upload.Limits(max_bytes=100 * 1024 * 1024,
                          target_bytes=300 * 1024 * 1024).checked().target_bytes,
      300 * 1024 * 1024)

# ── two ceilings only pay for themselves when something SHRINKS the file ──
# A fetch ceiling above the upload ceiling exists so media_prep can judge a
# file it has on disk. But remux and pass-through do not make anything smaller,
# so with the hatch off a file between the two numbers is a multi-gigabyte
# download spent to reach a skip — the exact bug can_shrink exists to prevent.
print("\nvault_upload.Limits: one ceiling unless something can shrink")
_off = vault_upload.Limits().checked()
check("by default the fetch ceiling collapses onto the upload ceiling",
      _off.max_download_bytes, _off.max_bytes)
_on = vault_upload.Limits(compress_over_bytes=_HATCH_ON).checked()
check("with the hatch on it is allowed to be larger again",
      _on.max_download_bytes > _on.max_bytes, True)
_cli = vault_upload.Limits(max_bytes=500 * 1024 * 1024).checked()
check("`--max-mb 500` means 500 MB in the FETCH pass too, not 5 GB",
      _cli.max_download_bytes, 500 * 1024 * 1024)
check("...and cap_for agrees for a video, which is the caller that reads it",
      vault_upload.cap_for("clip.mp4", "video/mp4", _cli), 500 * 1024 * 1024)
_wide = vault_upload.Limits(max_bytes=6000 * 1024 * 1024,
                            compress_over_bytes=_HATCH_ON).checked()
check("a --max-mb ABOVE the fetch ceiling raises the fetch ceiling with it, "
      "rather than refusing to download what it would happily upload",
      _wide.max_download_bytes, 6000 * 1024 * 1024)


# ── caps ─────────────────────────────────────────────────────────────────
print("\nvault_upload._apply_caps")
plan = [vault_upload._item(f"clip{n}.mp4", f"/tmp/clip{n}.mp4", "local",
                           900 * 1024 * 1024) for n in range(3)]
plan += [vault_upload._item(f"p{n}.jpg", f"/tmp/p{n}.jpg", "local", 1000)
         for n in range(3)]
vault_upload._apply_caps(plan, vault_upload.Limits(max_files=4))
# Oversized video is kept (compression is what rescues it) — and therefore
# COUNTS, which is the bug: 3 videos + 3 photos with a cap of 4 is 4, not 6.
kept = [i for i in plan if i["status"] == "pending"]
check("oversized video counts against the batch cap", len(kept), 4)
check("the overflow says why",
      "batch cap" in (plan[-1]["error"] or ""), True)

# Sized against the DEFAULT ceiling, which is now 4000 MB: the point of the
# check is that a non-video gets the upload cap and not the (larger) download
# cap, not the specific number.
huge = [vault_upload._item("dump.zip", "/tmp/dump.zip", "local",
                           (vault_upload.MAX_MB + 100) * 1024 * 1024)]
vault_upload._apply_caps(huge, vault_upload.Limits())
check("a large non-video is skipped, and says ffmpeg cannot prepare it",
      huge[0]["status"] == "skipped"
      and "not video ffmpeg can prepare" in huge[0]["error"], True)


# ── the Drive API key never reaches disk or the screen ───────────────────
print("\ngdrive.redact")
_KEY = "AIza-not-a-real-key-0000000000000000000"
_api_key_orig = gdrive.api_key
gdrive.api_key = lambda: _KEY
try:
    leaky = (f"ConnectionError: HTTPSConnectionPool(host='www.googleapis.com') "
             f"url: /drive/v3/files?alt=media&key={_KEY}")
    check("the key is scrubbed out of an error string",
          _KEY in gdrive.redact(leaky), False)
    check("the rest of the message survives",
          "ConnectionError" in gdrive.redact(leaky), True)
    check("the key is sent as a header, never a query parameter",
          gdrive._auth(), {"x-goog-api-key": _KEY})

    # End to end: whatever the download raises, the run record must not carry it.
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        vault_upload.SPOOL_ROOT = td
        _dl = gdrive.download
        gdrive.download = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError(f"proxy died on ...&key={_KEY}"))
        try:
            it = vault_upload._item("v.mp4", None, "gdrive", 10)
            it.update(drive_id="abc", mime_type="video/mp4")
            items = [it]
            vault_upload._fetch_drive(items, td, vault_upload.Limits(),
                                      lambda _items: None)
        finally:
            gdrive.download = _dl
        check("a stored item error never contains the key",
              _KEY in (items[0]["error"] or ""), False)
        check("the failure is still reported", items[0]["status"], "failed")
    vault_upload.SPOOL_ROOT = _spool_root_orig
finally:
    gdrive.api_key = _api_key_orig


# ── run ids are validated before they touch a path ───────────────────────
print("\nvault_upload._run_dir")
for bad in ("../../etc", "..", "run.json", "42-2026-01-01-abc"):
    check_raises(f"rejects {bad!r}", lambda b=bad: vault_upload._run_dir(b), ValueError)
check("accepts a generated id",
      vault_upload._run_dir("42-20260101T000000-abc123").name,
      "42-20260101T000000-abc123")


# ── one predicate for 'can this be compressed?' ──────────────────────────
print("\nmedia_prep.can_shrink")
import media_prep  # noqa: E402
_ffmpeg_orig = media_prep.have_ffmpeg
media_prep.have_ffmpeg = lambda: True
try:
    check("a Drive video mime says yes", media_prep.can_shrink("clip.flv", "video/x-flv"), True)
    check("and the suffix agrees, so a fetched .flv is not then refused",
          media_prep.can_shrink("clip.flv", None), True)
    check("an image is no", media_prep.can_shrink("a.jpg", "image/jpeg"), False)
    check("a local video with no mime falls back to the suffix",
          media_prep.can_shrink("a.mkv"), True)
    check("an unknown local file is no", media_prep.can_shrink("a.zip"), False)
finally:
    media_prep.have_ffmpeg = _ffmpeg_orig
media_prep.have_ffmpeg = lambda: False
try:
    check("without ffmpeg nothing is compressible — so nothing is fetched "
          "under the big download ceiling either",
          media_prep.can_shrink("a.mp4", "video/mp4"), False)
finally:
    media_prep.have_ffmpeg = _ffmpeg_orig


# ── an intent that cannot be RECORDED must stop the carrier being CREATED ──
# The whole feature rests on this. The intent hook writes to the same spool
# volume the import is filling, so its realistic failure is ENOSPC — precisely
# when a carrier is most likely to be created and never recorded. Logging the
# failure and posting anyway is an unrecoverable scheduled post on a real feed.
print("\nof_client.materialize_to_vault: a failed intent hook aborts the POST")

blocked = _Recorder()
check_raises(
    "an intent hook that raises propagates",
    lambda: of_client.OFClient.materialize_to_vault(
        blocked, [{"processId": "p"}],
        on_carrier_intent=lambda marker: (_ for _ in ()).throw(
            OSError("No space left on device"))),
    OSError)
check("and NO carrier post was created", blocked.order, [])

# The id hook is the same argument one step later: if the id cannot be written
# down, the carrier is deleted again rather than left live and untracked.
untracked = _Recorder()
check_raises(
    "an on_carrier hook that raises propagates too",
    lambda: of_client.OFClient.materialize_to_vault(
        untracked, [{"processId": "p"}],
        on_carrier=lambda pid: (_ for _ in ()).throw(OSError("read-only fs"))),
    OSError)
check("and the carrier it could not record is deleted again",
      untracked.deleted, [9001])


# ── every OnlyFans write goes through the injected gate ───────────────────
# The gate is what keeps a carrier out of the slot an automation's fan message
# reserved. Four writes need it, and until now every test passed `None`.
print("\nthe write gate: all four writes, and pacing that is policy not identity")

gated: list[str] = []


def _recording_gate(thunk):
    gated.append("write")
    return thunk()


class _GateClient:
    """Records what it was handed, and leaves a carrier for cleanup to chase."""
    def __init__(self):
        self.gate_seen = "not passed"
        self.writes: list = []

    def upload_claim(self, path):
        return of_client.UploadClaim(media={"processId": path})

    def materialize_to_vault(self, send_with, *, on_carrier_intent, on_carrier,
                             gate, **_):
        self.gate_seen = gate
        on_carrier_intent(of_client.VAULT_MARKER)
        on_carrier(9001)
        # Never `on_carrier_deleted`: the carrier's own delete failed, so
        # _cleanup_carriers has to retry it — through the gate.
        return {"media": [{"id": 5}], "carrier_post_id": 9001,
                "carrier_deleted": False}

    def delete_post(self, pid):
        self.writes.append(("delete", pid))
        return {}

    def add_media_to_vault_list(self, list_id, ids):
        self.writes.append(("file", list_id, tuple(ids)))
        return {}


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    media = td / "a.jpg"
    media.write_bytes(b"x" * 8)
    gc_ = _GateClient()
    st = vault_upload.start("42", client=gc_, local_paths=[str(media)],
                            list_id=7, gate=_recording_gate,
                            limits=vault_upload.Limits(pace_s=0))
    check("the run finished", st["status"], "done")
    check("the gate reaches of_client, which owns the carrier POST and DELETE",
          gc_.gate_seen is _recording_gate, True)
    check("the carrier cleanup retry went through the gate",
          ("delete", 9001) in gc_.writes, True)
    check("so did the foldering call", ("file", 7, (5,)) in gc_.writes, True)
    check("and both were counted by the gate", len(gated), 2)

vault_upload.SPOOL_ROOT = _spool_root_orig
vault_upload.LOCK_DIR = _spool_root_orig / "locks"


# ── a stale lock whose pid was recycled is stale ──────────────────────────
# Container pids are small and recycled. Checking only os.kill(pid, 0) meant a
# relay OOM-killed at pid 37 locked the feature out forever the moment anything
# else was handed pid 37.
print("\nvault_upload._acquire_lock: pid reuse is not liveness")

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    vault_upload.LOCK_DIR.mkdir(parents=True)
    lock = vault_upload._lock_path("42")
    _start_orig = vault_upload._pid_start
    vault_upload._pid_start = lambda pid: "STARTED-NOW"
    try:
        import json as _json
        # Same pid, DIFFERENT process: the recycled-pid case.
        lock.write_text(_json.dumps({"pid": os.getpid(), "started": "STARTED-LONG-AGO"}))
        check("a live pid that started at another time is a STALE lock",
              vault_upload._lock_holder("42"), None)
        check("so the lock can be taken", vault_upload._acquire_lock("42") == lock, True)

        # Same pid, same start: a genuinely live holder.
        lock.write_text(_json.dumps({"pid": 1, "started": "STARTED-NOW"}))
        check("a live pid with a matching start time IS the holder",
              (vault_upload._lock_holder("42") or {}).get("pid"), 1)
        check_raises("and a second process is refused",
                     lambda: vault_upload._acquire_lock("42"), RuntimeError)
        check("the account reads as busy", vault_upload._account_is_live("42"), True)

        # Nothing can hold a lock for a day.
        old = time.time() - vault_upload._LOCK_MAX_AGE_S - 60
        os.utime(lock, (old, old))
        check("and a lock older than any real import is stale",
              vault_upload._lock_holder("42"), None)
    finally:
        vault_upload._pid_start = _start_orig
vault_upload.SPOOL_ROOT = _spool_root_orig
vault_upload.LOCK_DIR = _spool_root_orig / "locks"


# ── the sweep must never touch a run that is still going ──────────────────
# materialize_to_vault polls for up to 600s per file, and for that whole window
# the item on disk says "carrier 9001, not deleted". The hourly sweep firing
# inside that window used to delete the carrier out from under the poll — and
# then write its own stale snapshot back over run.json.
print("\nvault_upload.sweep: a live run owns its carriers")


class _SweepClient:
    def __init__(self):
        self.deleted: list = []

    def delete_post(self, pid):
        self.deleted.append(pid)
        return {}

    def schedules_later_post(self, limit=10, offset=0):
        return {"list": []}


def _write_run(td: Path, run_id: str, *, status: str, items: list,
               account: str = "42") -> Path:
    d = td / run_id
    d.mkdir(parents=True, exist_ok=True)
    state = vault_upload._new_state(run_id, account, None)
    state.update(status=status, items=items,
                 finished_at=None if status == "running" else vault_upload._now())
    (d / "run.json").write_text(__import__("json").dumps(state))
    return d / "run.json"


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    live_id, dead_id = "42-20260101T000000-aaaaaa", "43-20260101T000001-bbbbbb"

    def _carrier(pid):
        it = vault_upload._item("v.mp4", None, "local", 10)
        it.update(carrier_post_id=pid, carrier_deleted=False, status="uploading")
        return it

    live_json = _write_run(td, live_id, status="running", items=[_carrier(1111)])
    # A different account, so this asserts "the sweep still does its job"
    # rather than "the sweep does nothing". Account 42 is deliberately left
    # ENTIRELY alone while it has an importer: an hourly sweep can wait an hour,
    # and guessing which of a busy account's carriers are orphaned is the guess
    # that deletes a live one.
    _write_run(td, dead_id, status="failed", items=[_carrier(2222)],
               account="43")
    before = live_json.read_text()

    vault_upload._live["42"] = live_id
    try:
        client = _SweepClient()
        res = vault_upload.sweep(lambda aid: client)
    finally:
        vault_upload._live.pop("42", None)
    check("the orphan of the finished run is deleted", client.deleted, [2222])
    check("the LIVE run's carrier is left alone", 1111 in client.deleted, False)
    check("and its run.json is not clobbered from a stale snapshot",
          live_json.read_text(), before)
    check("the sweep reports only what it actually did", res["carriers_deleted"], 1)

    # Cross-process: the CLI's `--sweep` runs in a process whose `_live` is
    # empty. The lockfile is the only thing that can say the dashboard's import
    # is running, and without it the sweep deleted live carriers deliberately.
    live_json.write_text(before)
    vault_upload.LOCK_DIR.mkdir(parents=True, exist_ok=True)
    vault_upload._acquire_lock("42")
    try:
        client2 = _SweepClient()
        vault_upload.sweep(lambda aid: client2)
    finally:
        vault_upload._release_lock(vault_upload._lock_path("42"))
    check("an account whose LOCK is held is never swept", client2.deleted, [])
    check("its record is untouched too", live_json.read_text(), before)
vault_upload.SPOOL_ROOT = _spool_root_orig
vault_upload.LOCK_DIR = _spool_root_orig / "locks"


# ── what the operator is warned about ────────────────────────────────────
# Two ways to get this wrong, and the first version managed both: it missed the
# intent-only orphan (the dangerous one — no id exists to name it) and it fired
# on every healthy import, for the second or two a carrier legitimately exists.
print("\nvault_upload.carriers_outstanding")

_dead = vault_upload._item("a.mp4", None, "local", 1)
_dead.update(carrier_post_id=3333, carrier_deleted=False)
_ghost = vault_upload._item("b.mp4", None, "local", 1)
_ghost.update(carrier_intent={"at": "now", "marker": of_client.VAULT_MARKER},
              carrier_deleted=False)
_gone = vault_upload._item("c.mp4", None, "local", 1)
_gone.update(carrier_post_id=4444, carrier_deleted=True)

finished = {"run_id": "42-20260101T000000-ffffff", "account_id": "42",
            "status": "failed", "finished_at": vault_upload._now(),
            "items": [_dead, _ghost, _gone]}
check("a finished run's undeletable carrier is counted",
      vault_upload.carriers_outstanding("42", [finished])[0], 1)
check("so is an intent with no id — the one no id can name",
      vault_upload.carriers_outstanding("42", [finished])[1], 1)
check("a carrier that was deleted is not",
      vault_upload.carriers_outstanding("42", [{**finished, "items": [_gone]}]), (0, 0))

in_flight = {"run_id": "42-20260101T000001-aaaaaa", "account_id": "42",
             "status": "running", "finished_at": None, "items": [_dead, _ghost]}
vault_upload._live["42"] = in_flight["run_id"]
try:
    check("a RUNNING run's carrier is not an escape — it is a normal import",
          vault_upload.carriers_outstanding("42", [in_flight]), (0, 0))
    # The suppression is per RUN, not per account, and `finished_at` is what
    # says so — it is written exactly once, in start()'s finally, so it is the
    # one "this run is over" any process can trust. Inheriting the account's
    # busy flag meant a week-old escaped carrier was reported as clean for as
    # long as ANY import was going — and a wedged run kept `_live` set for the
    # life of the relay, which here is weeks.
    check("but a FINISHED run's carrier stays on screen while a different "
          "run imports", vault_upload.carriers_outstanding("42", [finished]),
          (1, 1))
finally:
    vault_upload._live.pop("42", None)

# A run that died without saying so is not "in flight" — its carrier is exactly
# the escape this warning exists for.
check("an interrupted run's carrier IS an escape",
      vault_upload.carriers_outstanding("42", [vault_upload._reconcile(in_flight)]),
      (1, 1))

# R10: an intent a completed scan cleared is resolved — and it says that in its
# own field. It used to say it in `carrier_deleted`, asserting a deletion that
# never happened on a field the CLI and the dashboard read as "a post we named
# is gone".
_scanned = dict(_ghost, carrier_scan_clear=True)
check("an intent a completed scan cleared is not counted",
      vault_upload.carriers_outstanding("42", [{**finished, "items": [_scanned]}]),
      (0, 0))


# ── liveness is ONE question with ONE answer ─────────────────────────────
# It had three implementations: a named predicate, a character-for-character
# copy inside the warnings, and a narrower `_live`-only rule in the reconciler.
# One HTTP response could call a run "interrupted" — rendered as "the relay
# restarted mid-run" — while suppressing its carrier warnings BECAUSE the
# account was busy. Two answers to one question, in one dict.
print("\nvault_upload._run_is_live: one predicate, every caller")

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    vault_upload.LOCK_DIR.mkdir(parents=True)
    cli_run = "42-20260101T000000-cccccc"
    _write_run(td, cli_run, status="running", items=[])
    state = vault_upload.read_state(cli_run) or {}
    check("no claim anywhere -> interrupted", state.get("status"), "interrupted")

    # A CLI import in ANOTHER process: `_live` here is empty and the lockfile is
    # the only witness. Reporting that run as "the relay restarted mid-run" was
    # the visible half of the split predicate.
    lock = vault_upload._lock_path("42")
    lock.write_text(json.dumps({"pid": os.getpid(),
                                "started": vault_upload._pid_start(os.getpid()),
                                "instance": "some-other-process",
                                "run_id": cli_run}))
    check("a run another process holds the lock for is LIVE, not interrupted",
          (vault_upload.read_state(cli_run) or {}).get("status"), "running")
    # And still per-run: the lock names one run, not the account.
    other = "42-20260101T000009-dddddd"
    _write_run(td, other, status="running", items=[])
    check("a DIFFERENT run of the same account is not live off that lock",
          (vault_upload.read_state(other) or {}).get("status"), "interrupted")
    lock.unlink()

    # The in-process claim has the ceiling the lockfile always had. A wedged run
    # used to keep `_live` set for the life of the relay — weeks — and while it
    # was set the sweep skipped every run dir of that account and the operator
    # was told the carriers were clean.
    vault_upload._live["42"] = cli_run
    try:
        check("a live claim with a fresh heartbeat is live",
              vault_upload._account_is_live("42"), True)
        old = time.time() - vault_upload._LIVE_MAX_STALL_S - 60
        os.utime(vault_upload._state_path(cli_run), (old, old))
        check("a claim whose run stopped writing hours ago is not",
              vault_upload._account_is_live("42"), False)
    finally:
        vault_upload._live.pop("42", None)
vault_upload.SPOOL_ROOT = _spool_root_orig
vault_upload.LOCK_DIR = _spool_root_orig / "locks"


# ── the marker scan re-asks; pass 1's answers go stale ───────────────────
# Pass 2 pages OnlyFans — up to fifty sequential round trips — and deletes any
# marker-bearing post it cannot find in the set of ids it knows. Both that set
# and "is this account importing?" were snapshots taken before the paging
# started, so a carrier created DURING the scan was, by construction, unknown.
print("\nvault_upload.sweep: pass 2 re-asks before every delete")


class _MidScan:
    """Answers the listing, and starts an import while it does."""

    def __init__(self, td, on_list):
        self.td, self.on_list = td, on_list
        self.deleted: list = []
        self.listed = 0

    def schedules_later_post(self, limit=100, offset=0):
        if offset:
            return {"list": []}
        self.listed += 1
        self.on_list()          # ... an import starts, right here
        return {"list": [{"id": 5555, "rawText": of_client.VAULT_MARKER}]}

    def delete_post(self, pid):
        self.deleted.append(pid)
        return {}


def _ghost_run(td, run_id, account="42"):
    """A finished run holding an intent and NO id — the record that puts an
    account into the marker scan in the first place."""
    it = vault_upload._item("v.mp4", None, "local", 10)
    it.update(carrier_intent={"at": vault_upload._now(),
                              "marker": of_client.VAULT_MARKER},
              status="failed")
    return _write_run(td, run_id, status="failed", items=[it], account=account)

# (a) the new carrier is RECORDED mid-scan: re-reading the run dirs is what
#     makes it known, and a known id is never touched.
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    ghost = _ghost_run(td, "42-20260101T000000-eeeeee")
    new_run = "42-20260102T000000-111111"

    def _start_recording():
        it = vault_upload._item("w.mp4", None, "local", 10)
        it.update(carrier_post_id=5555, carrier_deleted=False, status="uploading")
        _write_run(td, new_run, status="failed", items=[it])

    client = _MidScan(td, _start_recording)
    res = vault_upload.sweep(lambda aid: client)
    check("a carrier recorded AFTER pass 1 is not an unknown carrier",
          client.deleted, [])
    check("and the listing did happen — this is not a vacuous pass",
          client.listed, 1)

# (b) the account goes LIVE mid-scan: the scan is abandoned, and an abandoned
#     scan retires nothing.
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    ghost = _ghost_run(td, "42-20260101T000000-eeeeee")
    live_run = "42-20260102T000000-222222"

    def _go_live():
        _write_run(td, live_run, status="running", items=[])
        vault_upload._live["42"] = live_run

    client = _MidScan(td, _go_live)
    try:
        vault_upload.sweep(lambda aid: client)
    finally:
        vault_upload._live.pop("42", None)
    check("a carrier of a run that went live mid-scan is left alone",
          client.deleted, [])
    on_disk = json.loads(ghost.read_text())
    check("and an abandoned scan retires no intent",
          bool((on_disk["items"][0]).get("carrier_scan_clear")), False)
vault_upload.SPOOL_ROOT = _spool_root_orig
vault_upload.LOCK_DIR = _spool_root_orig / "locks"


# ── a carrier OnlyFans says is not there cannot publish ──────────────────
# `materialize_to_vault` reports `carrier_deleted` through its RETURN value, so
# anything raising between the id and the return — one non-2xx from a 600s poll
# — propagated past a delete that SUCCEEDED. The item kept "carrier live, never
# deleted" forever, every retry 404'd, and the red banner could never clear.
print("\nof_client.post_is_gone: a 404 on the delete is the delete working")


class _Resp:
    def __init__(self, code):
        self.status_code = code


check("404 means gone",
      of_client.post_is_gone(of_client.OFAPIError("404 for x", response=_Resp(404))), True)
check("410 too",
      of_client.post_is_gone(of_client.OFAPIError("410 for x", response=_Resp(410))), True)
check("401 does NOT — a stale session hides a live post",
      of_client.post_is_gone(of_client.OFAPIError("401 for x", response=_Resp(401))), False)
check("and a response-less error is read off the message",
      of_client.post_is_gone(of_client.OFAPIError("404 for x")), True)


class _Gone:
    def __init__(self):
        self.tried: list = []

    def delete_post(self, pid):
        self.tried.append(pid)
        raise of_client.OFAPIError("404 for /posts", response=_Resp(404))


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    stuck = vault_upload._item("a.mp4", None, "local", 1)
    stuck.update(carrier_post_id=9001, carrier_deleted=False)
    st = {"run_id": "42-20260101T000000-abc123", "items": [stuck]}
    gone = _Gone()
    vault_upload._cleanup_carriers(st, gone)
    check("a 404 on the retry resolves the carrier, it does not alarm forever",
          stuck["carrier_deleted"], True)
    check("and it was actually attempted", gone.tried, [9001])
vault_upload.SPOOL_ROOT = _spool_root_orig

# The hook half of the same fix: the record is written from of_client's own
# `finally`, so it is right even when the call is on its way out with an error.
class _PollDies(_Recorder):
    def get_post(self, post_id):
        raise of_client.OFAPIError("500 for /posts", response=_Resp(500))


dying = _PollDies()
recorded: list = []
try:
    of_client.OFClient.materialize_to_vault(
        dying, [{"processId": "p"}], timeout_s=1, poll_interval_s=0,
        on_carrier=lambda pid: None,
        on_carrier_deleted=lambda pid: recorded.append(pid))
except of_client.OFAPIError:
    pass
check("the delete still happened", dying.deleted, [9001])
check("and it was RECORDED, though the body raised past the return",
      recorded, [9001])


# ── releasing a lock must not release somebody else's ────────────────────
# `start()` pops its `_live` claim and releases the lock as two statements. A
# second `begin()` landing in between takes a fresh lock — and the first run's
# release then deleted the NEW run's file, silently turning cross-process
# exclusion off for the run that was actually going.
print("\nvault_upload._release_lock: only ever our own")

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    old_run, new_run = "42-20260101T000000-aaa111", "42-20260101T000100-bbb222"
    p = vault_upload._acquire_lock("42", old_run)
    p.unlink()
    vault_upload._acquire_lock("42", new_run)          # the newer run's lock
    vault_upload._release_lock(p, old_run)             # the older run finishing
    check("the newer run's lockfile survives the older run's release",
          p.exists(), True)
    check("and it still names the newer run",
          vault_upload._read_lock(p).get("run_id"), new_run)
    vault_upload._release_lock(p, new_run)
    check("its own release does remove it", p.exists(), False)

    # A lock written by a process we cannot see is UNKNOWN, not stale. Reading
    # "the start times differ" as death across a pid namespace turned G3's
    # lockout into silent lock-stealing: two importers on one account.
    p.write_text(json.dumps({"pid": os.getpid(), "started": "STARTED-ELSEWHERE",
                             "instance": "another-container", "run_id": "x"}))
    check("a foreign instance with a mismatched start is still a holder",
          (vault_upload._lock_holder("42") or {}).get("instance"), "another-container")
    check_raises("so we refuse rather than steal the lock",
                 lambda: vault_upload._acquire_lock("42", new_run), RuntimeError)
vault_upload.SPOOL_ROOT = _spool_root_orig
vault_upload.LOCK_DIR = _spool_root_orig / "locks"


# ── the write gate bounds the WAIT; the write itself outlives it ──────────────
# `run_coroutine_threadsafe` hands back a future whose timeout does not touch
# the coroutine, so a timed-out carrier POST is still queued and still fires
# when its pacing slot arrives — after the run ended and after a marker scan
# has correctly found nothing. Retiring that intent is how a post nobody is
# tracking reaches the creator's feed thirty days later.
print("\nvault_upload: an intent whose write may still fire is never retired")

_pending = {"carrier_intent": "MARKER", "carrier_post_id": None,
            "carrier_scan_clear": True, "carrier_write_pending": True}
check("a completed scan does NOT resolve it",
      vault_upload._intent_unresolved(_pending), True)
check("and it keeps the run record alive for the next sweep",
      vault_upload._intent_unresolved({**_pending, "carrier_scan_clear": True}), True)

# The counterpart: the ordinary successful file. An intent is written before
# EVERY carrier POST and is never cleared once an id is learned, so spelling
# this without the id check put every account that had ever imported into the
# hourly scan — a full paged walk of the creator's schedule, for nothing.
_done = {"carrier_intent": "MARKER", "carrier_post_id": 99,
         "carrier_deleted": True, "carrier_scan_clear": None}
check("a successfully imported file leaves nothing outstanding",
      vault_upload._intent_unresolved(_done), False)
check("an id-less intent with no scan yet IS outstanding",
      vault_upload._intent_unresolved({"carrier_intent": "MARKER"}), True)
check("and a completed scan resolves that one",
      vault_upload._intent_unresolved(
          {"carrier_intent": "MARKER", "carrier_scan_clear": True}), False)

# One definition, four askers. This is the rule that has now been spelled by
# hand in four places and disagreed in two of them.
_src = (Path(__file__).resolve().parents[1] / "vault_upload.py").read_text()
check("no hand-rolled copy of the rule survives",
      _src.count('not i.get("carrier_scan_clear")')
      + _src.count('not it.get("carrier_scan_clear")'), 0)

# begin() is the only gate. The cheap in-process pre-check could not see the
# cross-process lock, so a multi-gigabyte drag-in was staged to disk in full
# before the lock refused it — and once a wedged run aged past the stall
# ceiling it answered 409 to the very re-run the dashboard was advising.
check("is_running is gone", hasattr(vault_upload, "is_running"), False)


# ── which ids "landed", and WHEN the caller is told ───────────────────────
# Both consumers of a finished import — the relay batch route and the CLI —
# write the ids into the local mirror, and both used to re-derive the filter
# inline. The interesting half was documented in one copy and absent from the
# other: a `skipped` item can carry a perfectly real vault id, because a skip is
# a dedupe onto media that is HIDDEN on OnlyFans. Mirroring one of those puts a
# tile in the grid for bytes the creator deliberately removed.
print("\nvault_upload.landed_ids")

check("only `done` counts",
      vault_upload.landed_ids({"items": [
          {"status": "done", "vault_id": 1},
          {"status": "failed", "vault_id": 2},
          {"status": "pending", "vault_id": 3},
      ]}), [1])
check("a skipped item's id is NOT mirrored — it is a dedupe onto HIDDEN media",
      vault_upload.landed_ids({"items": [
          {"status": "done", "vault_id": 10},
          {"status": "skipped", "vault_id": 11, "deduped": True, "hidden": True},
      ]}), [10])
check("a done item with no id is skipped, not crashed on",
      vault_upload.landed_ids({"items": [{"status": "done", "vault_id": None},
                                         {"status": "done"}]}), [])
check("a half-written run record read back off disk does not KeyError",
      vault_upload.landed_ids({"items": [{}, {"status": "done", "vault_id": 5}]}), [5])
check("no items, no ids", vault_upload.landed_ids({}), [])


# The ORDERING is the fix. The dashboard polls the run's status and fires its
# query invalidations on the `running → not running` edge, exactly once; a
# mirror write that lands AFTER that edge is a write nothing refetches, so a
# large import rendered as the pre-import grid and stayed that way. `start` must
# therefore call the hook while the run still reports `running` on disk.
print("\nvault_upload.start: the mirror hook runs BEFORE the run reports finished")

_spool_root_orig2 = vault_upload.SPOOL_ROOT
_lock_dir_orig2 = vault_upload.LOCK_DIR
_collect_orig = vault_upload._collect
_save_orig = vault_upload._save
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"

    landed_item = {"name": "a.jpg", "source": "local", "size": 4, "path": None,
                   "status": "done", "error": None, "vault_id": 4242,
                   "deduped": False, "spooled": False}
    vault_upload._collect = lambda state, *a, **kw: [dict(landed_item)]

    # Every save, in order, as the run's own watchers would read it off disk.
    seen: list[tuple] = []

    def _recording_save(state):
        seen.append((state.get("status"), state.get("phase")))
        _save_orig(state)

    vault_upload._save = _recording_save

    hook_saw: list[tuple] = []
    watching: list[str] = []          # the run id the hook should read back

    def _hook(ids, details):
        # What the status route would answer to a poll landing right here.
        hook_saw.append((list(ids),
                         (vault_upload.read_state(watching[-1]) or {}).get("status")))

    rid = vault_upload.begin("42")
    watching.append(rid)
    done_run = vault_upload.start("42", client=object(), on_landed=_hook,
                                  local_paths=["a.jpg"], run_id=rid)

    check("the hook is called with the landed ids",
          [h[0] for h in hook_saw], [[4242]])
    check("and the run still reports `running` while it works — otherwise the "
          "grid has already refetched the pre-import mirror",
          [h[1] for h in hook_saw], ["running"])
    check("the wait is named rather than looking like a stall",
          ("running", "mirroring") in seen, True)
    check("`mirroring` is written BEFORE the run is published as finished",
          seen.index(("running", "mirroring")) < seen.index(("done", "finished")),
          True)
    check("and the run does finish", done_run["status"], "done")

    # A run that FAILED still mirrors what it managed to land: a batch can die
    # on its last file with a dozen already in the creator's vault.
    seen.clear()
    hook_saw.clear()

    def _boom(state, *a, **kw):
        state["items"] = [dict(landed_item)]
        raise RuntimeError("the drive fetch died")

    vault_upload._collect = _boom
    rid = vault_upload.begin("42")
    watching.append(rid)
    logging.getLogger("of-relay.vault_upload").setLevel(logging.CRITICAL)
    failed_run = vault_upload.start("42", client=object(), on_landed=_hook,
                                    local_paths=["a.jpg"], run_id=rid)
    logging.getLogger("of-relay.vault_upload").setLevel(logging.NOTSET)
    check("a failed run is still a failed run", failed_run["status"], "failed")
    check("but the files it DID land reach the mirror",
          [h[0] for h in hook_saw], [[4242]])

    # And a hook that raises must never turn a successful import into a failure:
    # the media is on OnlyFans either way, and a missing mirror row is one
    # re-collect away.
    hook_saw.clear()
    vault_upload._collect = lambda state, *a, **kw: [dict(landed_item)]
    rid = vault_upload.begin("42")
    logging.getLogger("of-relay.vault_upload").setLevel(logging.CRITICAL)
    survived = vault_upload.start(
        "42", client=object(), local_paths=["a.jpg"], run_id=rid,
        on_landed=lambda ids, details: (_ for _ in ()).throw(RuntimeError("mirror down")))
    logging.getLogger("of-relay.vault_upload").setLevel(logging.NOTSET)
    check("a mirror failure does not fail the import", survived["status"], "done")

    # And `Exception` is not the bar. The relay's hook blocks on a
    # `concurrent.futures.Future`, and a loop shutting down mid-wait raises
    # `CancelledError` — which since 3.8 IS `asyncio.CancelledError`, a
    # BaseException. It walked straight past `except Exception` and out of
    # `start`'s own `finally`, so the run was left `running/mirroring` with no
    # `finished_at`, the account still claimed in `_live`, the lockfile still on
    # disk — `begin()` refuses on `_live` unconditionally, so that account could
    # not be imported into again for the life of the process — and, worst,
    # `_cleanup_carriers` never ran for a batch whose uploads had all SUCCEEDED.
    # That is the pass that stops a carrier post publishing to the creator's
    # whole feed 30 days out.
    hook_saw.clear()
    swept: list[str] = []
    _cleanup_orig = vault_upload._cleanup_carriers
    vault_upload._cleanup_carriers = \
        lambda state, client, gate=None: swept.append(state["run_id"])
    rid = vault_upload.begin("42")
    lock_file = vault_upload._lock_path("42")
    check("the lock is held while the run is going", lock_file.exists(), True)
    logging.getLogger("of-relay.vault_upload").setLevel(logging.CRITICAL)
    cancelled = vault_upload.start(
        "42", client=object(), local_paths=["a.jpg"], run_id=rid,
        on_landed=lambda ids, details: (_ for _ in ()).throw(asyncio.CancelledError()))
    logging.getLogger("of-relay.vault_upload").setLevel(logging.NOTSET)
    vault_upload._cleanup_carriers = _cleanup_orig

    check("a CANCELLED mirror hook still leaves a finished run",
          cancelled["status"], "done")
    check("…published as finished, not left mid-phase",
          (cancelled["phase"], bool(cancelled["finished_at"])), ("finished", True))
    check("…and that is what is on DISK, not just what start() returned",
          [(vault_upload.read_state(rid) or {}).get(k)
           for k in ("status", "phase")], ["done", "finished"])
    check("carrier cleanup runs — the pass that stops a carrier publishing",
          swept, [rid])
    check("the account is released, or it can never import again this process",
          vault_upload._live.get("42"), None)
    check("and the cross-process lock is released with it",
          lock_file.exists(), False)
    check("so the next import can actually claim the account",
          isinstance(vault_upload.begin("42"), str), True)
    vault_upload.abandon(vault_upload._live["42"], "test cleanup")

vault_upload._collect = _collect_orig
vault_upload._save = _save_orig
vault_upload.SPOOL_ROOT = _spool_root_orig2
vault_upload.LOCK_DIR = _lock_dir_orig2


# ── many files, one carrier ───────────────────────────────────────────────
# OnlyFans paces post CREATION (~1 per 10 s), not media per post, so a batch
# puts up to `carrier_batch` claims on one carrier. These run the real
# `upload_claim`, `materialize_to_vault` and `vault_carrier.attribute` against
# a fake OnlyFans, so the attribution of ids back to files is the production
# code, not a stand-in.
print("\nvault_upload: claims share a carrier")

# Misses are re-read until the post's ids are all placed; a fake index that
# never answers would hold every such test for ten minutes. The lag test below
# turns it back on, with sleep stubbed.
_hash_wait_orig = vault_carrier.HASH_WAIT_S
vault_carrier.HASH_WAIT_S = 0


class _FakeOF:
    """Just enough OnlyFans for the real upload_claim/materialize_to_vault.

    File names steer it: `dup*` is already in the vault, `bad*` is refused by
    convert, anything else gets a fresh claim. `order` reorders a carrier's
    media in `get_post`; `hash_misses` are names the hash lookup cannot find;
    `delete_fails` makes every DELETE a 500; `busy` are names OnlyFans lists
    with isReady=false (still transcoding); `lag` are names the hash index
    misses on their first lookup (MEASURED: it trails the post by seconds);
    `clock` is advanced half a second per upload, for the pacing test."""
    upload_claim = of_client.OFClient.upload_claim
    materialize_to_vault = of_client.OFClient.materialize_to_vault
    _VAULT_MARKER = of_client.VAULT_MARKER

    def __init__(self, *, order=None, hash_misses=(), delete_fails=False,
                 create_raises=None, spool=None, run_id=None, drop=(), late=(),
                 busy=(), clock=None, lag=()):
        self.order = order or (lambda media: media)
        # `drop`: claims OnlyFans accepts but never lists (MEASURED: a .webp).
        # `late`: claims listed only from the second poll on.
        self.drop, self.late, self.busy = set(drop), set(late), set(busy)
        self.clock = clock
        self.lag, self.lookups = set(lag), {}
        self.polls: dict[int, int] = {}
        self.hash_misses = set(hash_misses)
        self.delete_fails = delete_fails
        self.create_raises = create_raises
        self.spool, self.run_id = spool, run_id
        self.posts: dict[int, list] = {}
        self.created: list[list[str]] = []      # names on each carrier, in order
        self.intents_on_disk: list[dict] = []   # name -> intent, read at POST time
        self.deleted: list[int] = []
        self.vid = {}                           # name -> the vault id OF minted
        self._pid = 9000

    def upload_media(self, path, **kw):
        if self.clock is not None:
            self.clock[0] += 0.5
        name = Path(path).name
        key = f"etag-{name}"
        if name.startswith("dup"):
            return {"ready": True, "deduped": True, "vault_id": 100 + len(name),
                    "hidden": False, "dedupe_key": key, "size": 8}
        if name.startswith("bad"):
            return {"ready": False, "rejected": True, "upload_key": None,
                    "note": "convert register failed: 504"}
        return {"ready": True, "deduped": False, "dedupe_key": key, "size": 8,
                "send_with": [{"processId": name, "host": "h", "name": name}]}

    def create_post(self, text, *, media_files, **kw):
        if self.create_raises:
            raise self.create_raises
        names = [m["processId"] for m in media_files]
        if self.spool and self.run_id:
            disk = json.loads((self.spool / self.run_id / "run.json").read_text())
            self.intents_on_disk.append(
                {i["name"]: i.get("carrier_intent") for i in disk["items"]
                 if i["name"] in names})
        self._pid += 1
        for n in names:
            self.vid.setdefault(n, 5000 + len(self.vid))
        self.created.append(names)
        self.posts[self._pid] = names
        return {"id": self._pid}

    def get_post(self, pid):
        self.polls[pid] = self.polls.get(pid, 0) + 1
        media = [{"id": self.vid[n], "isReady": n not in self.busy}
                 for n in self.posts[pid]
                 if n not in self.drop
                 and (n not in self.late or self.polls[pid] > 1)]
        return {"media": self.order(media)}

    def delete_post(self, pid):
        self.deleted.append(pid)
        if self.delete_fails:
            raise of_client.OFAPIError("500 for /posts", response=_Resp(500))
        return {}

    def vault_media_lookup_hash(self, key, size):
        name = key.removeprefix("etag-")
        self.lookups[name] = self.lookups.get(name, 0) + 1
        if name in self.lag and self.lookups[name] == 1:
            return None
        if name in self.hash_misses or name in self.drop or name not in self.vid:
            return None
        return {"id": self.vid[name], "isReady": name not in self.busy}


def _batch_run(td: Path, names: list[str], fake: _FakeOF, **limits) -> dict:
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    paths = []
    for n in names:
        p = td / "src" / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(n.encode().ljust(8, b"."))
        paths.append(str(p))
    rid = vault_upload.begin("42")
    fake.spool, fake.run_id = td, rid
    logging.getLogger("of-relay.vault_upload").setLevel(logging.CRITICAL)
    logging.getLogger("of-client").setLevel(logging.CRITICAL)
    try:
        return vault_upload.start("42", client=fake, local_paths=paths, run_id=rid,
                                  limits=vault_upload.Limits(pace_s=0, **limits))
    finally:
        logging.getLogger("of-relay.vault_upload").setLevel(logging.NOTSET)
        logging.getLogger("of-client").setLevel(logging.NOTSET)


def _by_name(st: dict) -> dict:
    return {i["name"]: i for i in st["items"]}


_fresh = [f"f{n:02d}.jpg" for n in range(13)]
_mixed = (_fresh[:5] + ["dup0.jpg"] + _fresh[5:6] + ["bad0.jpg"] + _fresh[6:10]
          + ["dup01.jpg"] + _fresh[10:])

with tempfile.TemporaryDirectory() as td:
    fake = _FakeOF()
    st = _batch_run(Path(td), _mixed, fake)
    items = _by_name(st)
    check("13 new files + 2 dedupe hits + 1 refused claim -> carriers of 10 and 3",
          [len(c) for c in fake.created], [10, 3])
    check("each carrier carries the claims in file order",
          fake.created, [_fresh[:10], _fresh[10:]])
    check("every new file is done", {items[n]["status"] for n in _fresh}, {"done"})
    check("…with the vault id OnlyFans minted for ITS bytes",
          all(items[n]["vault_id"] == fake.vid[n] for n in _fresh), True)
    check("…and the ids are distinct",
          len({items[n]["vault_id"] for n in _fresh}), 13)
    check("a dedupe hit rides no carrier",
          (items["dup0.jpg"]["status"], items["dup0.jpg"]["carrier_post_id"],
           items["dup0.jpg"]["carrier_intent"]), ("done", None, None))
    check("a refused claim fails on its own and rides no carrier",
          (items["bad0.jpg"]["status"], items["bad0.jpg"]["carrier_intent"]),
          ("failed", None))
    check("the intent was ON DISK for every file on a carrier before its POST",
          [all(v and v.get("marker") == of_client.VAULT_MARKER for v in snap.values())
           and len(snap) == len(names)
           for snap, names in zip(fake.intents_on_disk, fake.created)], [True, True])
    check("every file on a carrier shares its id",
          {items[n]["carrier_post_id"] for n in _fresh[:10]}, {9001})
    check("each carrier deleted once, from its own finally", fake.deleted, [9001, 9002])
    check("…and recorded deleted on every file it carried",
          all(items[n]["carrier_deleted"] is True for n in _fresh), True)
    check("nothing outstanding", vault_upload.carriers_outstanding("42", [st]), (0, 0))
    check("the mirror hook's ids are the per-file ids",
          sorted(vault_upload.landed_ids(st)),
          sorted([fake.vid[n] for n in _fresh] + [items["dup0.jpg"]["vault_id"],
                                                  items["dup01.jpg"]["vault_id"]]))
    check("the known-carrier set still names both",
          vault_upload._known_carriers("42") >= {"9001", "9002"}, True)

# Position on the post is never the authority — only each file's own hash is.
# OnlyFans listing the media in another order than `mediaFiles` must not hand
# any file its neighbour's id.
with tempfile.TemporaryDirectory() as td:
    fake = _FakeOF(order=lambda media: list(reversed(media)))
    st = _batch_run(Path(td), _fresh[:4], fake)
    items = _by_name(st)
    check("a reversed media list is attributed by hash, correctly",
          [items[n]["vault_id"] for n in _fresh[:4]],
          [fake.vid[n] for n in _fresh[:4]])

# The swap the order fallback allowed: [img, vid1, vid2] listed as
# [img, vid2, vid1] and NO hash answering (index lag, a 429). Position would
# hand vid1 and vid2 each other's ids, both "done".
with tempfile.TemporaryDirectory() as td:
    trio = ["f00.jpg", "v1.mp4", "v2.mp4"]
    fake = _FakeOF(order=lambda media: [media[0], media[2], media[1]],
                   hash_misses=set(trio))
    st = _batch_run(Path(td), trio, fake)
    items = _by_name(st)
    check("reordered media + every hash missing -> every file fails, none swapped",
          [(items[n]["status"], items[n]["vault_id"]) for n in trio],
          [("failed", None)] * 3)
    check("…and each says why",
          all("could not be told apart" in items[n]["error"] for n in trio), True)
    check("…and the carrier still went", fake.deleted, [9001])

# Same swap, but only the image's hash answers: still nothing by position.
with tempfile.TemporaryDirectory() as td:
    fake = _FakeOF(order=lambda media: [media[0], media[2], media[1]],
                   hash_misses={"v1.mp4", "v2.mp4"})
    st = _batch_run(Path(td), ["f00.jpg", "v1.mp4", "v2.mp4"], fake)
    items = _by_name(st)
    check("two misses among three -> the hashed file lands, the two fail",
          [(items[n]["status"], items[n]["vault_id"])
           for n in ("f00.jpg", "v1.mp4", "v2.mp4")],
          [("done", fake.vid["f00.jpg"]), ("failed", None), ("failed", None)])

# ONE miss is closed by elimination, which needs no order: the post lists n
# distinct ids, the hash placed n-1 of them, the last id is the last claim's.
with tempfile.TemporaryDirectory() as td:
    fake = _FakeOF(order=lambda media: list(reversed(media)),
                   hash_misses={"f02.jpg"})
    st = _batch_run(Path(td), _fresh[:4], fake)
    items = _by_name(st)
    check("a single hash miss on a reordered carrier is filled by elimination",
          [(items[n]["status"], items[n]["vault_id"]) for n in _fresh[:4]],
          [("done", fake.vid[n]) for n in _fresh[:4]])

# The index trails the post: a miss is re-read, not failed — the live run that
# found this lost 9 of 13 files to a single pass.
with tempfile.TemporaryDirectory() as td:
    vault_carrier.HASH_WAIT_S = 600
    _sleep_orig = time.sleep
    naps: list = []
    time.sleep = lambda n: naps.append(n)
    try:
        fake = _FakeOF(order=lambda media: list(reversed(media)),
                       lag={"f00.jpg", "f01.jpg", "f03.jpg"})
        st = _batch_run(Path(td), _fresh[:4], fake)
    finally:
        time.sleep = _sleep_orig
        vault_carrier.HASH_WAIT_S = 0
    items = _by_name(st)
    check("hash misses from index lag are re-read, and every file lands right",
          [(items[n]["status"], items[n]["vault_id"]) for n in _fresh[:4]],
          [("done", fake.vid[n]) for n in _fresh[:4]])
    check("…one re-read pass, of the misses only",
          (len(naps), [fake.lookups[n] for n in _fresh[:4]]), (1, [2, 2, 1, 2]))

# …but not when a claim is missing from the post: then the leftover id is not
# the leftover claim's to take.
_grace_orig = of_client._CARRIER_MISSING_GRACE_S
of_client._CARRIER_MISSING_GRACE_S = 0
try:
    with tempfile.TemporaryDirectory() as td:
        fake = _FakeOF(drop={"f03.jpg"}, hash_misses={"f02.jpg"})
        st = _batch_run(Path(td), _fresh[:4], fake)
        items = _by_name(st)
        check("no elimination when the post lists fewer media than claims",
              [(items[n]["status"], items[n]["vault_id"]) for n in _fresh[:4]],
              [("done", fake.vid["f00.jpg"]), ("done", fake.vid["f01.jpg"]),
               ("failed", None), ("failed", None)])
finally:
    of_client._CARRIER_MISSING_GRACE_S = _grace_orig

# A video still transcoding is listed with its permanent id: the carrier does
# not wait for it, and only THAT file is flagged.
with tempfile.TemporaryDirectory() as td:
    fake = _FakeOF(busy={"v1.mp4"})
    st = _batch_run(Path(td), ["f00.jpg", "v1.mp4", "f01.jpg"], fake)
    items = _by_name(st)
    check("a transcoding video does not hold its carrier: one poll",
          fake.polls.get(9001), 1)
    check("…every file lands with its own id",
          [(items[n]["status"], items[n]["vault_id"])
           for n in ("f00.jpg", "v1.mp4", "f01.jpg")],
          [("done", fake.vid[n]) for n in ("f00.jpg", "v1.mp4", "f01.jpg")])
    check("…and only the video is still transcoding",
          [items[n]["still_transcoding"] for n in ("f00.jpg", "v1.mp4", "f01.jpg")],
          [False, True, False])

# A claim OnlyFans drops must not hold its carrier for the full timeout, and a
# claim that is merely SLOW must not be cut off by its quicker neighbours.
_grace_orig = of_client._CARRIER_MISSING_GRACE_S
try:
    of_client._CARRIER_MISSING_GRACE_S = 0
    with tempfile.TemporaryDirectory() as td:
        fake = _FakeOF(drop={"f01.jpg"})
        t = time.time()
        st = _batch_run(Path(td), _fresh[:3], fake)
        items = _by_name(st)
        check("a dropped claim does not wait out the 600 s poll", time.time() - t < 30, True)
        check("…it fails alone, and its neighbours keep their own ids",
              [(items[n]["status"], items[n]["vault_id"]) for n in _fresh[:3]],
              [("done", fake.vid["f00.jpg"]), ("failed", None),
               ("done", fake.vid["f02.jpg"])])
    of_client._CARRIER_MISSING_GRACE_S = 10
    with tempfile.TemporaryDirectory() as td:
        fake = _FakeOF(late={"f01.jpg"})
        st = _batch_run(Path(td), _fresh[:3], fake)
        check("a claim listed a poll late is waited for, not lost",
              [i["status"] for i in st["items"]], ["done"] * 3)
        check("…and was polled for", fake.polls.get(9001), 2)
finally:
    of_client._CARRIER_MISSING_GRACE_S = _grace_orig

# One carrier that cannot be deleted is ONE scheduled post on the feed.
with tempfile.TemporaryDirectory() as td:
    fake = _FakeOF(delete_fails=True)
    st = _batch_run(Path(td), _fresh[:3], fake)
    items = _by_name(st)
    check("a carrier delete failure flags every file it carried",
          [items[n]["carrier_deleted"] for n in _fresh[:3]], [False] * 3)
    check("…the end-of-run cleanup retried it ONCE, not once per file",
          fake.deleted, [9001, 9001])
    check("…and the alarm counts one post, not three",
          vault_upload.carriers_outstanding("42", [st]), (1, 0))

# carrier_batch=1 is the old one-carrier-per-file behaviour.
with tempfile.TemporaryDirectory() as td:
    fake = _FakeOF()
    st = _batch_run(Path(td), _fresh[:3], fake, carrier_batch=1)
    check("carrier_batch=1 posts one carrier per file", fake.created,
          [[n] for n in _fresh[:3]])
    check("…each deleted", fake.deleted, [9001, 9002, 9003])
    check("…each file done with its own id",
          [(i["status"], i["vault_id"]) for i in st["items"]],
          [("done", fake.vid[n]) for n in _fresh[:3]])
    check("carrier_batch below 1 is read as 1",
          vault_upload.Limits(carrier_batch=0).checked().carrier_batch, 1)

# The gate gave up waiting on the carrier create: the post may still be made,
# so every file on it keeps the intent open — and it is one possible post.
from concurrent.futures import TimeoutError as _FT  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    fake = _FakeOF(create_raises=_FT())
    st = _batch_run(Path(td), _fresh[:3], fake)
    check("a timed-out carrier write leaves every file on it write-pending",
          [(i["status"], i["carrier_write_pending"]) for i in st["items"]],
          [("failed", True)] * 3)
    check("…and is counted as ONE post that may exist",
          vault_upload.carriers_outstanding("42", [st]), (0, 1))

# A gate CANCELLED out of the carrier create is the same lost race: the relay's
# `_hop` surfaces a loop-side cancel as concurrent.futures' CancelledError.
from concurrent.futures import CancelledError as _FC  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    st = _batch_run(Path(td), _fresh[:3], _FakeOF(create_raises=_FC()))
    check("a cancelled carrier write leaves every file on it write-pending",
          [(i["status"], i["carrier_write_pending"]) for i in st["items"]],
          [("failed", True)] * 3)
    check("…one possible post", vault_upload.carriers_outstanding("42", [st]), (0, 1))

# asyncio's own CancelledError is a BaseException: it must not walk past the
# batch and leave its files `uploading` forever.
with tempfile.TemporaryDirectory() as td:
    fake = _FakeOF(create_raises=asyncio.CancelledError())
    try:
        _batch_run(Path(td), _fresh[:3], fake)
        check("asyncio.CancelledError propagates out of the run", "returned", "raised")
    except asyncio.CancelledError:
        check("asyncio.CancelledError propagates out of the run", "raised", "raised")
    rid = fake.run_id
    disk = vault_upload.read_state(rid) or {}
    check("…after failing every file on the carrier, write-pending",
          [(i["status"], i.get("carrier_write_pending")) for i in disk.get("items", [])],
          [("failed", True)] * 3)

# One file blowing up the loop (a save on a full disk) must not strand the
# claims already staged: they are carried, then the run stops.
with tempfile.TemporaryDirectory() as td:
    _upload_one_orig = vault_upload._upload_one

    def _boom(state, item, *a, **kw):
        if item["name"] == "f03.jpg":
            raise OSError("No space left on device")
        return _upload_one_orig(state, item, *a, **kw)
    vault_upload._upload_one = _boom
    try:
        fake = _FakeOF()
        st = _batch_run(Path(td), _fresh[:5], fake)
    finally:
        vault_upload._upload_one = _upload_one_orig
    items = _by_name(st)
    check("an exception mid-batch still carries the claims staged before it",
          fake.created, [_fresh[:3]])
    check("…which land with their own ids",
          [(items[n]["status"], items[n]["vault_id"]) for n in _fresh[:3]],
          [("done", fake.vid[n]) for n in _fresh[:3]])
    check("…and the run says it failed, the rest not uploaded",
          (st["status"], items["f04.jpg"]["status"]), ("failed", "failed"))

# media_prep crashing on one file is that file's failure, not the batch's.
with tempfile.TemporaryDirectory() as td:
    _prepare_orig = vault_upload.media_prep.prepare

    def _prep(path, *a, **kw):
        if Path(path).name == "f01.jpg":
            raise RuntimeError("ffprobe exploded")
        return _prepare_orig(path, *a, **kw)
    vault_upload.media_prep.prepare = _prep
    try:
        fake = _FakeOF()
        st = _batch_run(Path(td), _fresh[:3], fake)
    finally:
        vault_upload.media_prep.prepare = _prepare_orig
    items = _by_name(st)
    check("a prepare crash fails that file alone",
          [items[n]["status"] for n in _fresh[:3]], ["done", "failed", "done"])
    check("…the others still share a carrier, and the run finishes",
          (fake.created, st["status"]), ([["f00.jpg", "f02.jpg"]], "done"))

# Housekeeping after a file lands (the Drive memo, the spool unlink) failing on
# one file must not leave the files after it on the same carrier unrecorded.
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    rid = "42-20260101T000000-1a2b3c"
    (td / rid).mkdir(parents=True)
    state = vault_upload._new_state(rid, "42", None)
    batch = []
    fake = _FakeOF()
    for n in _fresh[:3]:
        it = vault_upload._item(n, None, "drive", 8)
        it.update(status="uploading", drive_md5=f"md5-{n}")
        batch.append(vault_upload._Staged(it, of_client.UploadClaim(
            media={"processId": n}, dedupe_key=f"etag-{n}", size=8), None))
    state["items"] = [s.item for s in batch]
    _memo_orig = vault_upload._memo_remember
    vault_upload._memo_remember = lambda *a: (_ for _ in ()).throw(
        OSError("No space left on device"))
    logging.getLogger("of-relay.vault_upload").setLevel(logging.CRITICAL)
    try:
        vault_upload._carry(state, batch, fake, None)
        raised = None
    except Exception as e:  # noqa: BLE001
        raised = e
    finally:
        vault_upload._memo_remember = _memo_orig
        logging.getLogger("of-relay.vault_upload").setLevel(logging.NOTSET)
    check("a failing memo write does not escape the carrier", raised, None)
    check("…and every file on it is recorded done with its own id",
          [(s.item["status"], s.item["vault_id"]) for s in batch],
          [("done", fake.vid[n]) for n in _fresh[:3]])
vault_upload.SPOOL_ROOT = _spool_root_orig

# Shared ids, read back off disk by the cleanup and the sweep.
_shared = []
for n in range(10):
    it = vault_upload._item(f"s{n}.jpg", None, "local", 1)
    it.update(carrier_post_id=7777, carrier_deleted=False, carrier_key="k7777",
              status="done", vault_id=n)
    _shared.append(it)
_shared_run = {"run_id": "42-20260101T000000-5ba7ed", "account_id": "42",
               "status": "done", "finished_at": vault_upload._now(),
               "items": [dict(i) for i in _shared]}
check("ten files sharing one undeleted carrier are ONE outstanding carrier",
      vault_upload.carriers_outstanding("42", [_shared_run]), (1, 0))
_del = _SweepClient()
vault_upload._cleanup_carriers(_shared_run, _del)
check("_cleanup_carriers deletes a shared carrier once", _del.deleted, [7777])
check("…and marks every file on it deleted",
      {i["carrier_deleted"] for i in _shared_run["items"]}, {True})

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    rj = _write_run(td, "42-20260101T000000-5ba7ee", status="done",
                    items=[dict(i) for i in _shared])
    _sw = _SweepClient()
    res = vault_upload.sweep(lambda aid: _sw)
    check("the sweep deletes a shared carrier once", _sw.deleted, [7777])
    check("…counts it once", res["carriers_deleted"], 1)
    check("…and records it on every file",
          {i["carrier_deleted"] for i in json.loads(rj.read_text())["items"]}, {True})

    # No session for the account: one failure per carrier, said as what it is.
    rj.write_text(json.dumps({**json.loads(rj.read_text()),
                              "items": [dict(i) for i in _shared]}))
    res = vault_upload.sweep(lambda aid: (_ for _ in ()).throw(RuntimeError("503")))
    check("no client: the shared carrier is one failure, nothing marked deleted",
          (res["carriers_failed"],
           {i["carrier_deleted"] for i in json.loads(rj.read_text())["items"]}),
          (1, {False}))

# Appended files that have queued up while the run was busy share a carrier.
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    vault_upload.SPOOL_ROOT = td
    vault_upload.LOCK_DIR = td / "locks"
    rid = vault_upload.begin("42", keep_open=True)
    for n in _fresh[:3]:
        p = td / n
        p.write_bytes(b"z" * 8)
        vault_upload.append(rid, str(p))
    vault_upload.close(rid)
    fake = _FakeOF(spool=td, run_id=rid)
    st = vault_upload.start("42", client=fake, run_id=rid,
                            limits=vault_upload.Limits(pace_s=0))
    check("three queued appended files ride one carrier", fake.created, [_fresh[:3]])
    check("…and all land", [i["status"] for i in st["items"]], ["done"] * 3)

# Pacing is between CARRIERS, counted from the end of the last one — and it is
# `limits.pace_s` and nothing else. It used to be "did the caller pass a
# gate?", so a test double, a metrics wrapper — any gate but the relay's own —
# silently turned pacing off; this run passes a gate on purpose.
class _StubTime:
    """`vault_upload.time` with a clock that only moves when told to."""
    def __init__(self, clock, slept):
        self._clock, self._slept = clock, slept

    def monotonic(self):
        return self._clock[0]

    def sleep(self, n):
        self._slept.append(n)

    def __getattr__(self, name):
        return getattr(time, name)


with tempfile.TemporaryDirectory() as td:
    slept: list[float] = []
    clock = [1000.0]
    _time_orig = vault_upload.time
    vault_upload.time = _StubTime(clock, slept)
    try:
        fake = _FakeOF(clock=clock)
        vault_upload.SPOOL_ROOT = Path(td)
        vault_upload.LOCK_DIR = Path(td) / "locks"
        paths = []
        for n in _fresh[:12]:
            p = Path(td) / n
            p.write_bytes(n.encode().ljust(8, b"."))
            paths.append(str(p))
        vault_upload.start("42", client=fake, local_paths=paths,
                           gate=_recording_gate,
                           limits=vault_upload.Limits(pace_s=3))
    finally:
        vault_upload.time = _time_orig
    check("12 files at 10 per carrier pace once, before the second carrier",
          (len(fake.created), len(slept)), (2, 1))
    check("…for what is left of the gap: 3 s less the 1 s two uploads took",
          slept, [2.0])
vault_upload.SPOOL_ROOT = _spool_root_orig
vault_upload.LOCK_DIR = _spool_root_orig / "locks"
vault_carrier.HASH_WAIT_S = _hash_wait_orig


print()
if failures:
    print(f"❌ {len(failures)} FAILED")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ all vault upload tests passed")
