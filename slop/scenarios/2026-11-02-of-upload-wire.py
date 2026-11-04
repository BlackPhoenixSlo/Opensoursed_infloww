"""Media upload on OnlyFans' wire (service/of_upload.py through the REAL `OFClient`): hash dedupe, signed S3
(single PUT, or multipart past 5 MiB: parts concurrently, then signed/finish), the convert claim, and the vault
id minted once something references the claim (a fan send, an import's carrier post).

World: `agency_inbox` (small 3 Creators, medium 10), each Creator with a captured session (seed/of_sessions), so
the relay builds its real OFClient against lib/of_wire.py (`OF_WIRE`). Files are made harness-side, deterministic
from `--seed` (a JPEG's first and last markers around random bytes, each file distinct): `--files=`
(FLOW_SIZES `of_upload_files`) Composer files spread over the Creators, `--big_files=` of them 2-3 parts (> 5 MiB),
the rest 20-200 KB; per Creator `--import_files=` fresh import files (Creator 0's first one multipart) and
`--import_dupes=` of its landed single-part Composer files sent again through the import (single-part only: the
multipart dedupe is REUPLOAD_MULTI's, in D, so the md5 fault's red stays off IMPORT).

Flow, `--users` at once:
  A  the Composer upload, `POST /api/of/v2/upload` (owner session, X-Account-Id, multipart `file`);
  B  right after, that claim sent to a fan of the Creator: `POST /api/of/v2/chats/{fan}/messages`,
     `media_files=[send_with]` (OF mints the vault media off the send);
  C  per Creator (all at once; one run per Creator, the route's own rule) a vault import: `POST
     .../vault/upload/batch` (first file, keep_open) + one `.../batch/append` per further file (`last` on the
     final one), its fresh files and its dupes; `GET .../upload/status?run_id=` until the run finished;
  D  every Composer file and every fresh import file uploaded again through the Composer (the same bytes).

Checks (names in lib/upload_faults.py), the fake's records split by phase (A-C vs D):
  UPLOAD_SHAPE   per new file (A, C fresh) exactly 1 signed/create asking ceil(size / 5 MiB) parts, that many ok
                 S3 PUTs (one per part), per Creator signed/finish calls == its multipart uploads.
  ONE_CLAIM      per new file exactly 1 convert claim.
  S3_BYTES       the fake S3 object under that key: the file's size and sha256.
  DEDUPE_KEY     the product hashed under the harness's own S3 ETag of the file (md5, or md5 of the part md5s +
                 `-N`): a `vault/media/hash` read with that `h` + size; the Composer upload answered it as
                 `dedupe_key` (an import's is not surfaced).
  CLAIM_ETAG     that ETag == the fake S3 object's ETag == the claim's `file[ETag]` (no fault proves it).
  CLAIM_TARGET   the claim names OF's key (Creator spliced in) with its uploadToken, `file[Location]` = the
                 putUrl without its query (part 1's), `file[Bucket]` its first host label, `file[name]` the file.
  REUPLOAD_ONE / REUPLOAD_MULTI   D: answered `deduped` with the vault id the fake minted for those bytes, and
                 not one signed/create, PUT or claim for that file in D (single-part / multipart files apart).
  SEND           B: 200, OF got exactly one message naming that processId, to that fan, its `mediaFiles` entry ==
                 the upload's `send_with`, a processId the fake's convert issued for that file.
  IMPORT         C: run `done`, every item `done` with a vault id: a fresh file the id minted for its bytes, a
                 dupe its earlier (B's) id, `deduped`; one id per file; no carrier left (every post OF got is
                 deleted), status carriers_undeletable / carriers_unrecorded 0.
  OFFHOST        no curl_cffi request off loopback (server-offhost.jsonl empty), and convert claims reached the
                 fake (lib/upload_relay.py's rewrite is live).
  AUDIT_ROWS     SQL: per Creator one `actions` row per 2xx upload (A + D) and per 2xx send (per fan), and one
                 outbound `messages` row (the send's attribution) per message OF accepted.
Budgets: p95 of A and B (route latency at --users), both vs the last green run; stock no 5xx / Traceback.

The loop finding (#171), closed: `POST /api/of/v2/upload` is `async def` and ran the blocking
`_proxy(... upload_media ...)` on the event loop, so uploads went one at a time and stalled every other request; a
coroutine holding a SQLite write transaction could not commit and other writers hit busy_timeout ("database is
locked", audit and attribution rows lost). Pre-fix, medium --users=200 (run
20261103T152551Z-2026-11-02-of-upload-wire-73b3): upload p95 86,817.5 ms, send p95 48,422.8 ms, 80 of 1250 actions
and 36 of 400 outbound messages lost, 232 'database is locked' log lines. The route now runs the spool and the
upload in one `asyncio.to_thread` worker; measured at medium --users=200 (runs
20261103T184145Z-2026-11-02-of-upload-wire-28e8, 20261103T184210Z-2026-11-02-of-upload-wire-99d2): upload p95
1,814.6 / 1,783.0 ms, send p95 1,516.7 / 1,570.0 ms, 1250 / 1250 actions, 0 messages lost, 0 'database is locked'.

Bypasses (declared): lib/of_wire.py is OnlyFans, S3 and convert (its docstring: 50 ms a call, a guess; the convert
answer's `host` / `extra` are guesses; the vault media is minted at reference, as the product's live notes say OF
does); lib/upload_relay.py rewrites the hard-coded convert host to the fake in curl_cffi. `/users/me` carries no
`upload.geoUploadArgs`, so the claim's preset fields are the product's own fallback. The owner tabs are httpx
pools, not browsers; their upload / send / import calls wait up to 300 s (a browser's fetch has no timeout).

Break-it-once: upload-dedupe-uses-md5 (the scenario's FAULT: `s3_etag_and_md5` returns the plain md5 as the
dedupe key) turns REUPLOAD_MULTI and DEDUPE_KEY red; `--fault=upload-convert-claimed-twice` (`convert_register` POSTs
twice) turns ONE_CLAIM red; `--scale=medium --users=200 --fault=upload-on-loop` (the Composer's `upload_media`
handed back to the event loop, the #171 shape) turns both budgets and AUDIT_ROWS red (run
20261103T184340Z-2026-11-02-of-upload-wire-break-3c7b: upload p95 101,805.3 ms, send p95 49,684.0 ms, 79 actions
and 32 messages lost, 222 'database is locked'; the lock Tracebacks are its noise). At small / 20 it has nothing to catch.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote, urlsplit

from slop.lib.upload_faults import (AUDIT_ROWS, BUDGET, CLAIM_ETAG, CLAIM_TARGET, DEDUPE_KEY, IMPORT, OFFHOST,
                                    ONE_CLAIM, REUPLOAD_MULTI, REUPLOAD_ONE, S3_BYTES, SEND, SEND_ROUTE, UPLOAD,
                                    UPLOAD_SHAPE)
from slop.seed import of_sessions

PROFILE = "agency_inbox"
UI = False
OF_WIRE = True
FAULT = "upload-dedupe-uses-md5"
PART = 5 * 1024 * 1024            # S3's minimum part, what OF's web client (and of_upload) splits at
SMALL = (20_000, 200_000)         # bytes of a small image
BIG = (PART + 1, 2 * PART + PART // 2)   # 2-3 parts
CALL_TIMEOUT_S = 300
IMPORT_TIMEOUT_S = 900
BATCH, APPEND, STATUS = ("/api/of/v2/vault/upload/batch", "/api/of/v2/vault/upload/batch/append",
                         "/api/of/v2/vault/upload/status")
P95_MS = {UPLOAD: 15_000, SEND_ROUTE: 5_000}   # BUDGET (lib/upload_faults.py) names the checks
P95_VS_LAST = (2.0, 2000)


def s3_etag(data: bytes) -> str:
    """S3's ETag for these bytes uploaded at PART: md5, or md5 of the parts' md5 digests + `-N`."""
    if len(data) <= PART:
        return hashlib.md5(data).hexdigest()
    parts = [hashlib.md5(data[i:i + PART]).digest() for i in range(0, len(data), PART)]
    return f"{hashlib.md5(b''.join(parts)).hexdigest()}-{len(parts)}"


def _make(d: Path, name: str, size: int, rng) -> dict:
    data = b"\xff\xd8\xff\xe0" + rng.randbytes(size - 6) + b"\xff\xd9"
    (d / name).write_bytes(data)
    return {"name": name, "path": str(d / name), "size": size, "sha256": hashlib.sha256(data).hexdigest(),
            "etag": s3_etag(data), "md5": hashlib.md5(data).hexdigest(), "parts": max(1, -(-size // PART))}


async def _pool(items, fn, n: int) -> None:
    it = iter(list(items))

    async def worker():
        for x in it:
            await fn(x)

    await asyncio.gather(*(worker() for _ in range(max(1, n))))


def _name_of(key: str) -> str:
    return key.rsplit("/", 1)[-1]


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    of_sessions.seed(w, w.data["creators"])
    aids = [c["id"] for c in w.data["creators"]]
    n_files, n_big, n_imp, n_dup = (ctx.param(k, w.size[f"of_upload_{k}"])
                                    for k in ("files", "big_files", "import_files", "import_dupes"))
    assert n_big <= n_files and n_dup >= 0, (n_files, n_big, n_dup)
    rng = w.rng("scenario:of-upload-wire")
    d = ctx.stack.tmp / "upload-files"
    d.mkdir(exist_ok=True)

    # ── the files ──────────────────────────────────────────────────────────
    big = set(rng.sample(range(n_files), n_big))
    compose = []
    for i in range(n_files):
        aid = aids[i % len(aids)]
        fans = w.data["fans"][aid]
        f = _make(d, f"slop-{ctx.seed}-c{i:04d}.jpg", rng.randint(*(BIG if i in big else SMALL)), rng)
        compose.append({**f, "aid": aid, "fan": fans[(i // len(aids)) % len(fans)]["id"]})
    fresh = {aid: [{**_make(d, f"slop-{ctx.seed}-i{k}-{j}.jpg",
                            rng.randint(*(BIG if k == 0 and j == 0 else SMALL)), rng), "aid": aid}
                   for j in range(n_imp)] for k, aid in enumerate(aids)}
    ctx.metric("files", {"compose": n_files, "multipart": sum(f["parts"] > 1 for f in compose),
                         "import_fresh": n_imp * len(aids), "import_dupes_per_creator": n_dup,
                         "bytes": sum(f["size"] for f in compose) + sum(f["size"] for v in fresh.values() for f in v)})

    http = ctx.owner.share(limits=ctx.users + len(aids) + 8)
    fake = ctx.of_wire

    # ── A + B: Composer upload, then the send ─────────────────────────────
    ups: dict[str, dict] = {}    # file name -> {status, body}
    sends: dict[str, dict] = {}

    async def compose_one(f: dict) -> None:
        h = {"X-Account-Id": f["aid"]}
        r = await http.post("/api/of/v2/upload", headers=h, timeout=CALL_TIMEOUT_S,
                            files={"file": (f["name"], Path(f["path"]).read_bytes(), "image/jpeg")})
        body = r.json() if r.status_code == 200 else {}
        ups[f["name"]] = {"status": r.status_code, "body": body, "text": "" if body else r.text[:300]}
        sw = (body.get("send_with") or [None])[0]
        if not isinstance(sw, dict):
            return
        s = await http.post(f"/api/of/v2/chats/{f['fan']}/messages", headers=h, timeout=CALL_TIMEOUT_S,
                            json={"text": f"slop upload {f['name']}", "media_files": [sw]})
        sends[f["name"]] = {"status": s.status_code, "send_with": sw,
                            "body": s.json() if s.status_code == 200 else s.text[:300]}

    ctx.rec.stage = "compose"
    t0 = time.time()
    await _pool(compose, compose_one, ctx.users)
    compose_s = time.time() - t0

    # ── C: one vault import per Creator, fresh files + already-sent ones ──
    landed = {f["name"] for f in compose if ups.get(f["name"], {}).get("status") == 200
              and sends.get(f["name"], {}).get("status") == 200}
    dupes = {aid: [f for f in compose if f["aid"] == aid and f["name"] in landed and f["parts"] == 1][:n_dup]
             for aid in aids}
    runs: dict[str, dict] = {}

    async def import_one(aid: str) -> None:
        h = {"X-Account-Id": aid}
        files = fresh[aid] + dupes[aid]
        rec = runs[aid] = {"files": [f["name"] for f in files], "posts": []}
        first, rest = files[0], files[1:]
        r = await http.post(BATCH, headers=h, timeout=CALL_TIMEOUT_S, data={"keep_open": "true"},
                            files=[("files", (first["name"], Path(first["path"]).read_bytes(), "image/jpeg"))])
        rec["batch"] = r.status_code
        run_id = (r.json() if r.status_code == 200 else {}).get("run_id")
        rec["run_id"] = run_id
        if not run_id:
            rec["error"] = r.text[:300]
            return
        for k, f in enumerate(rest):
            a = await http.post(APPEND, headers=h, timeout=CALL_TIMEOUT_S,
                                data={"run_id": run_id, "last": "true" if k == len(rest) - 1 else "false"},
                                files=[("files", (f["name"], Path(f["path"]).read_bytes(), "image/jpeg"))])
            rec["posts"].append(a.status_code)
        if not rest:
            a = await http.post(APPEND, headers=h, timeout=CALL_TIMEOUT_S, data={"run_id": run_id, "last": "true"})
            rec["posts"].append(a.status_code)
        deadline = time.time() + IMPORT_TIMEOUT_S
        st: dict = {}
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            q = await http.get(f"{STATUS}?run_id={run_id}", headers=h)
            st = q.json() if q.status_code == 200 else {}
            if st and not st.get("running") and st.get("status") in ("done", "failed", "interrupted"):
                break
        rec["status"] = st

    ctx.rec.stage = "import"
    t1 = time.time()
    await asyncio.gather(*(import_one(a) for a in aids))
    import_s = time.time() - t1

    # ── D: the same bytes again, through the Composer ─────────────────────
    again_files = [f for f in compose if f["name"] in landed] + \
        [f for aid in aids for f in fresh[aid]]
    again: dict[str, dict] = {}

    async def again_one(f: dict) -> None:
        r = await http.post("/api/of/v2/upload", headers={"X-Account-Id": f["aid"]}, timeout=CALL_TIMEOUT_S,
                            files={"file": (f["name"], Path(f["path"]).read_bytes(), "image/jpeg")})
        again[f["name"]] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:300]}

    ctx.rec.stage = "reupload"
    t3 = time.time()
    await _pool(again_files, again_one, ctx.users)
    reupload_s = time.time() - t3
    ctx.rec.stage = None
    await http.aclose()

    # ── the fake's records, by file and phase ─────────────────────────────
    up = fake.upload.snapshot()
    uploads, puts, claims, carriers, lookups, minted, s3 = (
        up[k] for k in ("uploads", "s3_puts", "claims", "carriers", "lookups", "minted", "s3"))
    with fake.lock:
        posts = {a: list(v) for a, v in fake.posts.items()}
        of_sends = {a: list(v) for a, v in fake.sends.items()}
        calls = list(fake.calls)
        unmodelled = dict(fake.unmodelled)
        unsigned = fake.unsigned

    def by_name(rows: dict, name_of) -> tuple[dict, dict]:
        """Per file name, the rows of phases A-C and of D."""
        ac: dict = defaultdict(list)
        dd: dict = defaultdict(list)
        for a, v in rows.items():
            for r in v:
                (ac if r["t"] < t3 else dd)[name_of(r)].append({**r, "account": a})
        return ac, dd

    up_ac, up_d = by_name(uploads, lambda r: _name_of(r["key"]))
    put_ac, put_d = by_name(puts, lambda r: _name_of(r["key"]))
    cl_ac, cl_d = by_name(claims, lambda r: r["name"])
    minted_by = {(a, m["etag"], m["size"]): m["id"] for a, v in minted.items() for m in v}
    compose_names = {f["name"] for f in compose}
    new_files = compose + [f for v in fresh.values() for f in v]
    (ctx.out / "upload-files.json").write_text(json.dumps(
        {"compose": compose, "fresh": fresh, "dupes": {a: [f["name"] for f in v] for a, v in dupes.items()}},
        indent=1))
    (ctx.out / "of-upload-fake.json").write_text(json.dumps(
        {**up, "unmodelled": unmodelled, "unsigned": unsigned}, indent=1, default=str))

    # UPLOAD_SHAPE / ONE_CLAIM / S3_BYTES / DEDUPE_KEY / CLAIM_ETAG / CLAIM_TARGET, per new file
    bad: dict[str, list] = defaultdict(list)
    finishes = Counter(c["account"] for c in calls
                       if c["route"] == "POST /api2/v2/upload/signed/finish" and c["t"] < t3)
    multi_ups = Counter()
    for f in new_files:
        n, a = f["name"], f["aid"]
        u = up_ac.get(n, [])
        if len(u) != 1 or u[0]["parts"] != f["parts"] or u[0]["account"] != a:
            bad["shape"].append((n, len(u), [x["parts"] for x in u], f["parts"]))
            continue
        u = u[0]
        multi_ups[a] += u["parts"] > 1
        ok_puts = sorted((p["part"] or 0) for p in put_ac.get(n, []) if p["ok"] and p["key"] == u["key"])
        if ok_puts != ([0] if f["parts"] == 1 else list(range(1, f["parts"] + 1))) or (f["parts"] > 1) != u["finished"]:
            bad["shape"].append((n, "puts", ok_puts, u["finished"]))
        c = cl_ac.get(n, [])
        if len(c) != 1:
            bad["claims"].append((n, len(c)))
        obj = s3.get(u["key"]) or {}
        if obj.get("sha256") != f["sha256"] or obj.get("size") != f["size"]:
            bad["bytes"].append((n, obj.get("size"), f["size"]))
        hashed = any(lk["h"] == f["etag"] and lk["size"] == f["size"] and lk["t"] < t3 for lk in lookups.get(a, ()))
        # an import's dedupe key is not surfaced
        dk = (ups.get(n, {}).get("body") or {}).get("dedupe_key") if n in compose_names else f["etag"]
        if not hashed or dk != f["etag"]:
            bad["dedupe"].append({"file": n, "want": f["etag"], "hashed": hashed, "dedupe_key": dk})
        if obj.get("etag") != f["etag"] or any(x["etag"] != f["etag"] for x in c):
            bad["claim_etag"].append({"file": n, "want": f["etag"], "s3": obj.get("etag"),
                                      "claims": [x["etag"] for x in c]})
        loc = f"{fake.origin}/s3/{quote(u['key'])}"
        for x in c:
            if not (x["key"] == u["key"] and x["token_ok"] and x["location"] == loc and x["account"] == a
                    and x["bucket"] == urlsplit(loc).netloc.split(".")[0] and x["name"] == n
                    and x["secure"] == "false" and str(x["user"]) == a):
                bad["target"].append({k: x.get(k) for k in ("name", "key", "token_ok", "location", "bucket",
                                                             "secure", "user")} | {"want_key": u["key"], "want_loc": loc})
    for a in aids:
        if finishes.get(a, 0) != multi_ups.get(a, 0):
            bad["shape"].append((a, "finishes", finishes.get(a, 0), multi_ups.get(a, 0)))
    news = len(new_files)
    ctx.check(UPLOAD_SHAPE, news > 0 and not bad["shape"], files=news, bad=len(bad["shape"]), sample=bad["shape"][:5],
              multipart=sum(multi_ups.values()))
    ctx.check(ONE_CLAIM, news > 0 and not bad["claims"], files=news, bad=len(bad["claims"]), sample=bad["claims"][:5])
    ctx.check(S3_BYTES, news > 0 and not bad["bytes"], files=news, bad=len(bad["bytes"]), sample=bad["bytes"][:5])
    ctx.check(DEDUPE_KEY, news > 0 and not bad["dedupe"], files=news, bad=len(bad["dedupe"]),
              sample=bad["dedupe"][:5])
    ctx.check(CLAIM_ETAG, news > 0 and not bad["claim_etag"], files=news, bad=len(bad["claim_etag"]),
              sample=bad["claim_etag"][:5])
    ctx.check(CLAIM_TARGET, news > 0 and not bad["target"], claims=sum(len(v) for v in cl_ac.values()),
              bad=len(bad["target"]), sample=bad["target"][:3])

    # REUPLOAD_ONE / REUPLOAD_MULTI (D)
    re_bad: dict[bool, list] = {False: [], True: []}
    re_n = Counter()
    for f in again_files:
        n, multi = f["name"], f["parts"] > 1
        re_n[multi] += 1
        g = again.get(n, {})
        body = g.get("body") if isinstance(g.get("body"), dict) else {}
        want = minted_by.get((f["aid"], f["etag"], f["size"]))
        if not (g.get("status") == 200 and body.get("deduped") is True and want is not None
                and body.get("vault_id") == want and not up_d.get(n) and not put_d.get(n) and not cl_d.get(n)):
            re_bad[multi].append({"file": n, "status": g.get("status"), "deduped": body.get("deduped"),
                                  "vault_id": body.get("vault_id"), "want": want, "uploads": len(up_d.get(n, [])),
                                  "puts": len(put_d.get(n, [])), "claims": len(cl_d.get(n, []))})
    for multi, name in ((False, REUPLOAD_ONE), (True, REUPLOAD_MULTI)):
        if not re_n[multi]:
            ctx.skip(name, "no such file re-uploaded")
            continue
        ctx.check(name, not re_bad[multi], files=re_n[multi], bad=len(re_bad[multi]), sample=re_bad[multi][:5])

    # SEND (B)
    pid_name = {c["processId"]: c["name"] for v in claims.values() for c in v if c.get("processId")}
    s_bad = []
    for f in compose:
        n = f["name"]
        s = sends.get(n)
        if s is None:
            s_bad.append({"file": n, "upload": ups.get(n, {}).get("status"), "why": "no send_with"})
            continue
        pid = s["send_with"].get("processId")
        got = [x for x in of_sends.get(f["aid"], ())
               if any(isinstance(m, dict) and m.get("processId") == pid for m in (x["body"].get("mediaFiles") or ()))]
        sent_mf = got[0]["body"]["mediaFiles"] if got else None
        if not (s["status"] == 200 and len(got) == 1 and got[0]["fan_id"] == f["fan"]
                and sent_mf == [s["send_with"]] and pid_name.get(pid) == n):
            s_bad.append({"file": n, "status": s["status"], "of_msgs": len(got), "mediaFiles": sent_mf,
                          "send_with": s["send_with"], "claim_of": pid_name.get(pid)})
    ctx.check(SEND, bool(sends) and not s_bad, sends=len(sends), bad=len(s_bad), sample=s_bad[:5])

    # IMPORT (C)
    i_bad = []
    for aid in aids:
        rec = runs.get(aid, {})
        st = rec.get("status") or {}
        items = {i.get("name"): i for i in st.get("items") or []}
        want = {f["name"]: minted_by.get((aid, f["etag"], f["size"])) for f in fresh[aid]}
        want |= {f["name"]: minted_by.get((aid, f["etag"], f["size"])) for f in dupes[aid]}
        ids = [i.get("vault_id") for i in items.values()]
        problems = []
        if st.get("status") != "done" or rec.get("batch") != 200 or any(p != 200 for p in rec.get("posts", [])):
            problems.append(("run", rec.get("batch"), rec.get("posts"), st.get("status"), st.get("error")))
        if sorted(items) != sorted(want):
            problems.append(("items", sorted(items), sorted(want)))
        for n, vid in want.items():
            i = items.get(n) or {}
            if i.get("status") != "done" or vid is None or i.get("vault_id") != vid:
                problems.append(("item", n, i.get("status"), i.get("vault_id"), vid, i.get("error")))
        for f in dupes[aid]:
            if not (items.get(f["name"]) or {}).get("deduped"):
                problems.append(("dupe not deduped", f["name"]))
        if len(set(ids)) != len(ids):
            problems.append(("ids", ids))
        if st.get("carriers_undeletable") or st.get("carriers_unrecorded"):
            problems.append(("carrier roll-up", st.get("carriers_undeletable"), st.get("carriers_unrecorded")))
        if problems:
            i_bad.append({"creator": aid, "problems": problems[:6]})
    left = {a: [p["id"] for p in v if p["id"] not in {c["id"] for c in carriers.get(a, ())}]
            for a, v in posts.items()}
    left = {a: v for a, v in left.items() if v}
    n_carriers = sum(1 for v in posts.values() for p in v if p.get("mediaFiles"))  # the only posts here: carriers
    ctx.check(IMPORT, bool(runs) and not i_bad and not left and n_carriers > 0, runs=len(runs), bad=i_bad[:5],
              carriers=n_carriers, posts_left_on_of=left)
    (ctx.out / "import-runs.json").write_text(json.dumps(runs, indent=1, default=str))

    # OFFHOST
    off = [line for t in ctx.stack.offhost_dirs if (p := Path(t) / "server-offhost.jsonl").exists()
           for line in p.read_text().splitlines() if line.strip()]
    n_claims = sum(len(v) for v in claims.values())
    ctx.check(OFFHOST, not off and n_claims > 0, offhost=off[:5], convert_claims=n_claims)

    # AUDIT_ROWS: what the audit / attribution writers committed (SQL), against the 2xx answers and OF's sends
    # actions.action is "METHOD path" (service/audit_log.py), so the upload's is UPLOAD
    want_act = Counter((f["aid"], UPLOAD) for f in compose if ups.get(f["name"], {}).get("status") == 200)
    want_act += Counter((f["aid"], UPLOAD) for f in again_files if again.get(f["name"], {}).get("status") == 200)
    want_act += Counter((f["aid"], f"POST /api/of/v2/chats/{f['fan']}/messages") for f in compose
                        if sends.get(f["name"], {}).get("status") == 200)
    want_msg = {(a, int(x["fan_id"]), int(x["id"])) for a, v in of_sends.items() for x in v}
    con = w.sql()
    try:
        got_act = Counter({(str(a), act): n for a, act, n in con.execute(
            "SELECT account_id, action, COUNT(*) FROM actions WHERE action = ? "
            "OR action LIKE 'POST /api/of/v2/chats/%/messages' GROUP BY 1, 2", (UPLOAD,))})
        got_msg = {(str(a), int(f), int(m)) for a, f, m in con.execute(
            "SELECT account_id, fan_id, message_id FROM messages WHERE direction = 'out'")}
    finally:
        con.close()
    act_off = {f"{a} {act}": (got_act.get((a, act), 0), n) for (a, act), n in (want_act | got_act).items()
               if got_act.get((a, act), 0) != want_act.get((a, act), 0)}
    lost_msg = sorted(want_msg - got_msg)
    ctx.check(AUDIT_ROWS, bool(want_act) and bool(want_msg) and not act_off and not lost_msg,
        actions_want=sum(want_act.values()), actions_got=sum(got_act.values()), actions_off=len(act_off),
        sample_off=dict(list(act_off.items())[:5]), messages_want=len(want_msg), messages_lost=len(lost_msg),
        sample_lost=lost_msg[:5])

    # budgets
    routes = ctx.rec.summary("compose")
    for route, budget in P95_MS.items():
        if route not in routes:
            ctx.skip(BUDGET[route], "no samples")
        else:
            ctx.check(BUDGET[route], routes[route]["p95_ms"] < budget, budget=True, p95=routes[route]["p95_ms"],
                n=routes[route]["n"], budget_ms=budget)
    re_routes = ctx.rec.summary("reupload")
    ctx.metric("load", {"creators": len(aids), "users": ctx.users, "compose_s": round(compose_s, 2),
                        "import_s": round(import_s, 2), "reupload_s": round(reupload_s, 2),
                        "compose_routes": routes, "reupload_routes": re_routes,
                        "import_routes": ctx.rec.summary("import"), "unmodelled": unmodelled,
                        "unsigned": unsigned})
    ctx.metric("p95_vs_last_green", {r: routes[r]["p95_ms"] for r in P95_MS if r in routes})
