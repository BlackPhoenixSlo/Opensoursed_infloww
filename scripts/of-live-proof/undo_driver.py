"""The driver's undo half (ticket 131, split out of prove.py): the undo-key registration (`register_keys`), a proof's
Undo log rows undone through the Relay and closed (`settle_rows`), and fake mode's per-row FakeOF check
(`row_problem`). A proof's undo is one of:

  - its undo Writes (`_send_all`), each row's by its arm index, sent by undo Write then row (ticket 30: each post's
    DELETE, then the one hide), an undo several rows share sent once;
  - a fallback chain (ticket 100, Proof.undo_ids, `_chain`): the undo Writes tried in order until one is answered 2xx
    on the wire, a later one's other ids registered first through `/__proof/read-id`;
  - a confirmed sequence (ticket 96, Proof.undo_steps, `_steps`), sent once for all of a proof's rows, each call
    followed by a fresh read it must confirm before the next.

`call(method, route, body=None, account=None, form=None) -> (status, text)` is the Relay client (`form`: a multipart
body, `multipart`'s), `wire()` the folded wire log and `read(tag)` the proof's OnlyFans read, as prove.py's run_proof
builds them.
"""
from __future__ import annotations

import hashlib
import json
import struct
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

from proof_core import NOT_REVERSIBLE_REFUSED, _api, _template, fill, read_keys_for
from undo_log import needs_row_id, reads_equal, row_undo_hits, row_undos, verify_undo

# ticket 67: what the Relay's profile-image route takes (service/server.py PROFILE_IMAGE_TYPES, PROFILE_IMAGE_MAX), by
# the picture's first bytes; a kept picture it would refuse stops the proof before its trigger (`keep`).
UPLOAD_MAX = 5 * 1024 * 1024
_SNIFF = ((b"\xff\xd8\xff", "image/jpeg", ".jpg"), (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
          (b"GIF8", "image/gif", ".gif"))


def picture_type(data: bytes) -> tuple | None:
    """(content type, extension) of a JPEG, PNG, GIF or WebP picture by its first bytes, else None."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return next(((t, e) for magic, t, e in _SNIFF if data.startswith(magic)), None)


def picture_size(data: bytes) -> tuple | None:
    """(width, height) decoded from a PNG's IHDR, a JPEG's SOF or a GIF's screen descriptor, else None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"GIF8") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i + 9 <= len(data) and data[i] == 0xFF:
            marker, size = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + size
    return None


def describe(data: bytes) -> dict:
    """A picture's sha256, byte length, content type (by its first bytes) and decoded width/height."""
    kind, size = picture_type(data), picture_size(data)
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "type": kind[0] if kind else None,
            "width": size[0] if size else None, "height": size[1] if size else None}


def _download(call, url, creator) -> tuple:
    """(status, bytes) of a picture fetched through the Relay's /img as the Creator."""
    status, data = call("GET", "/img?u=" + quote(str(url), safe=""), account=creator)
    return status, data or b""


def multipart(fields: dict) -> tuple:
    """(content type, body) of a multipart form: each value a string or a (file name, bytes, content type) file."""
    boundary = uuid.uuid4().hex
    out = b""
    for name, v in fields.items():
        if isinstance(v, tuple):
            fname, data, ctype = v
            out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fname}"\r\n'
                    f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
        else:
            out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{v}\r\n'.encode()
    return f"multipart/form-data; boundary={boundary}", out + f"--{boundary}--\r\n".encode()


def keep(proof, before, call, creator, folder) -> dict:
    """Ticket 67: each picture an undo puts back (`Write.relay_upload`), downloaded through the Relay's /img right after
    the before read and written into `folder` (the evidence folder, never git): {undo index: (file name, bytes, content
    type)}. Raises, so the proof stops before its trigger, when the before read names none, or the download fails or is
    not a picture the upload route takes: a write whose undo could not put it back is never sent."""
    kept = {}
    for i, w in enumerate(proof.undo):
        if not w.relay_upload:
            continue
        url = w.relay_upload.picture(before)
        if not url:
            raise RuntimeError(f"{proof.id}: the before read names no picture for undo {i} to put back")
        status, data = _download(call, url, creator)
        kind = picture_type(data) if status == 200 else None
        if kind is None or len(data) > UPLOAD_MAX:
            raise RuntimeError(f"{proof.id}: the picture undo {i} puts back did not download as a JPEG, PNG, GIF or "
                               f"WebP of 5 MB or less (/img answered {status}, {len(data)} bytes)")
        name = f"undo-{i}-before{kind[1]}"
        (folder / name).write_bytes(data)
        kept[i] = (name, data, kind[0])
    return kept


# ticket 67 follow-up: live OF re-encodes a re-uploaded cover, gives it a new URL and applies it late (measured
# 2026-11-21: the header URL changed again after the after-undo read; the restored cover's mean absolute pixel difference
# from the kept original was 1.45 / 3.83 / 4.47 on 0-255 across OF's three sizes, against 61-64 for the proof's grey
# test picture). So the undo re-reads, up to RESTORE_WAIT seconds, every RESTORE_STEP, until the after-undo read names a
# cover URL that is neither the before nor the after-write one and that picture decodes to the kept picture's size with
# a mean absolute RGB difference under RESTORE_MAX_DIFF. ASSUMPTION, `inferred`: 12 sits well above the measured
# re-encode noise (<= 5) and far below another picture (~60); overturned by a live restore of the right picture above
# it, or a wrong one below it. ASSUMPTION, `inferred`: a new URL that is not the kept picture (the late test write) is
# no verdict yet: the restore may still land after it; only the deadline fails the row (OF's order is not measured).
RESTORE_WAIT, RESTORE_STEP, RESTORE_MAX_DIFF = 60.0, 3.0, 12.0


def picture_match(kept: bytes, got: bytes, reuploaded: bool = False) -> dict:
    """Ticket 67: `got` against the `kept` picture: {ok, why, kept, restored (`describe`'s, sha256 kept for the
    report), mean_abs_diff (0-255, None when not decoded)}. Byte-identical passes (`reverify`), except a `reuploaded`
    picture: OF re-encodes every upload, so the kept bytes themselves are not the re-upload. Else both must decode
    (Pillow) to the same width and height with a mean absolute RGB difference under RESTORE_MAX_DIFF."""
    out = {"kept": describe(kept), "restored": describe(got), "mean_abs_diff": None, "max_diff": RESTORE_MAX_DIFF}
    if kept == got:
        return {**out, "ok": not reuploaded, "mean_abs_diff": 0.0,
                "why": "byte-identical to the kept picture: not OF's re-encoded re-upload" if reuploaded else None}
    import io
    from PIL import Image, ImageChops, ImageStat
    try:
        a, b = (Image.open(io.BytesIO(x)).convert("RGB") for x in (kept, got))
    except Exception as e:  # noqa: BLE001  (an undecodable picture is not the kept one)
        return {**out, "ok": False, "why": f"does not decode ({type(e).__name__})"}
    if a.size != b.size:
        return {**out, "ok": False, "why": f"size {b.size[0]}x{b.size[1]}, kept {a.size[0]}x{a.size[1]}"}
    diff = round(sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3, 2)
    ok = diff < RESTORE_MAX_DIFF
    return {**out, "ok": ok, "mean_abs_diff": diff,
            "why": None if ok else f"mean abs pixel diff {diff} >= {RESTORE_MAX_DIFF}"}


def _served(proof, i, read_value) -> str | None:
    """The picture URL `read_value` (an OnlyFans read) names for `proof`'s picture undo `i`, else None."""
    return proof.undo[i].relay_upload.picture(read_value) if read_value else None


def restored(proof, row, kept, fetched, folder) -> tuple:
    """Ticket 67: each kept picture against the last new cover the after-undo reads named (`fetched` {undo index:
    (status, bytes)}, `undo`'s; none: no read named one), written into `folder` as `undo-{i}-after<ext>`: ({undo index:
    `picture_match`'s, or {kept, restored: None}}, evidence names, problems). The undo holds only when `picture_match`
    passes for a re-upload (the same picture, re-encoded by OF)."""
    out, names, problems = {}, [], []
    for i, (_, data, _) in sorted((kept or {}).items()):
        status, got = fetched.get(i, (None, b""))
        if status != 200 or not got:
            out[str(i)] = {"kept": describe(data), "restored": None}
            problems.append(f"row {row['row']}: the picture undo {i} put back did not read back " + (
                "(no after-undo read named a cover other than none, the before or the after-write one)"
                if status is None else f"(the new cover answered {status})"))
            continue
        rec = out[str(i)] = picture_match(data, got, reuploaded=True)
        kind = picture_type(got)
        name = f"undo-{i}-after{kind[1] if kind else '.bin'}"
        if folder is not None:
            (folder / name).write_bytes(got)
        names.append(name)
        if not rec["ok"]:
            k, r = rec["kept"], rec["restored"]
            problems.append(f"row {row['row']}: the picture undo {i} put back is not the kept one: {rec['why']} "
                            f"(sha256 {k['sha256'][:12]} {k['bytes']} B -> {r['sha256'][:12]} {r['bytes']} B)")
    return out, names, problems


def _picture_undo(proof) -> int | None:
    """The index of `proof`'s undo that puts a picture back (`Write.relay_upload`), else None."""
    return next((i for i, w in enumerate(proof.undo) if w.relay_upload), None)


def kept_files(proof, folder) -> list:
    """The pictures an earlier run kept in its evidence `folder` for `proof`'s picture undo (`keep`'s names)."""
    i = _picture_undo(proof)
    return sorted((Path(folder) / proof.id).glob(f"undo-{i}-before.*")) if i is not None else []


def reverify(proof, folder, read, call, creator, out=None) -> dict:
    """Ticket 67 follow-up, read only: the picture OnlyFans serves now (`read()`, the proof's OnlyFans read, then
    /img) against the one an earlier run kept in `folder` (`kept_files`; the caller refuses a folder without
    one), by `picture_match`'s rule. Sends no write: one read and one GET. The served picture goes into `out` (this
    run's evidence folder) as `<proof id>/reverify-served<ext>`. {ok, why, kept_file, status, ...picture_match's}."""
    i, file = _picture_undo(proof), kept_files(proof, folder)[0]   # prove.py refuses a folder without one
    kept, name = file.read_bytes(), f"{proof.id}/{file.name}"
    url = _served(proof, i, read())
    status, got = _download(call, url, creator) if url else (None, b"")
    if status is None:
        return {"ok": False, "why": "the OnlyFans read shows no cover", "kept_file": name}
    if status != 200 or not got:
        return {"ok": False, "why": f"the served cover answered {status}", "kept_file": name, "status": status}
    if out is not None:
        kind = picture_type(got)
        (Path(out) / proof.id).mkdir(parents=True, exist_ok=True)
        (Path(out) / proof.id / f"reverify-served{kind[1] if kind else '.bin'}").write_bytes(got)
    return {**picture_match(kept, got), "kept_file": name, "status": status}


def is_key_source(proof, row) -> bool:
    """Whether this row is one its proof's undo keys are read off (ticket 131): the proof reads keys, and the row has
    its own OnlyFans id that its undo deletes by (the Record proof's post row, settled first by `undo_order`)."""
    return bool(proof.undo_keys) and row.get("of_id") is not None and needs_row_id(proof, row)


def _read_id(call, row, key, of_id, source, creator):
    return call("POST", "/__proof/read-id", {"row": row["row"], "key": key, "of_id": str(of_id), "source": str(source)},
                account=creator)


def register_keys(proof, row, before, after_write, call, problems, keys=None, creator=None) -> dict:
    """Ticket 30/131: the undo's other ids (the vault media id the created post carries), out of the read taken before
    any undo (`after_write()`), the ones read off this row's own item (`read_keys_for`); each registered with the Relay
    as read off the row's OnlyFans id, which the Relay checks it created and reads itself, so the guard binds the
    undo's pinned body to it alone. Added to `keys` (returned): one already held (ticket 97's second post carries the
    same media id) is not registered again; a refused one, or one differing from the id held, is dropped (the undo
    that needs it is not sent: its rows close FAILED)."""
    keys = {} if keys is None else keys
    try:
        got = read_keys_for(proof.undo_keys(before, after_write()), row["of_id"])
    except Exception as e:  # noqa: BLE001  (no keys: the undo that needs them is not sent, its rows FAILED)
        problems.append(f"reading {proof.id}'s undo ids failed: {type(e).__name__}: {e}")
        return keys
    for k, v in got.items():
        if k in keys:
            if keys[k] != v:
                problems.append(f"row {row['row']}: undo id {k}={v} differs from the {k}={keys[k]} already held")
            continue
        status, _ = _read_id(call, row, k, v, row["of_id"], creator)
        if status == 200:
            keys[k] = v
        else:
            problems.append(f"row {row['row']}: the Relay refused read id {k}={v}: {status}")
    return keys


def trigger_reversal(w, row, path, lines):
    """Ticket 34: the reversal the trigger itself already sent for this row (vault.more.delete: the UI's Delete is the
    create's declared undo, class 8), else None: the first completed `reversal` wire line of `w`'s method on the row's
    filled OnlyFans `path`, after the row's write. Only for an undo whose path takes `{id}`, which the Live guard binds
    to an id this proof created, so the line is this proof's; sending it again would be refused over count."""
    if "id" not in _template(w.path).groupindex or row.get("wire_seq") is None:
        return None
    return next((e for e in sorted(lines, key=lambda e: e["seq"])
                 if e.get("verdict") == "reversal" and e["seq"] > row["wire_seq"] and e.get("status") is not None
                 and e["method"] == w.method.upper() and _api(e["path"]) == _api(path)), None)


def _ok(status) -> bool:
    return isinstance(status, int) and 200 <= status < 300


def _shows_id(v, of_id: str) -> bool:
    """Whether a read holds `of_id` anywhere as a whole value (a row's id field or column). A `_` key is the read's
    own bookkeeping (phase2 read_marked_messages' `_page` bounds), never an item: skipped (W30 S3)."""
    if isinstance(v, Mapping):
        return any(_shows_id(x, of_id) for k, x in v.items() if not str(k).startswith("_"))
    if isinstance(v, (list, tuple)):
        return any(_shows_id(x, of_id) for x in v)
    return not isinstance(v, bool) and v is not None and str(v) == of_id


def still_shown(read, of_id) -> bool:
    """Follow-up #6: whether a fresh read (tagged `before-undo-retry`) still shows the row's own item by its OnlyFans
    id. False when there is no read, no id, or the read failed: the driver then sends nothing of its own.
    ASSUMPTION: the proof's read names its items by id (p2.bubble-unsend-ppv's marked (id, text, price) rows; W30 W2:
    a PPV pushed past the read's page is not shown here, and its row closes FAILED on ppv_gone/ppv_same); overturned by
    a trigger-reversing proof whose read carries no id, whose failed in-page reversal then closes FAILED unretried."""
    if read is None or of_id is None:
        return False
    try:
        return _shows_id(read("before-undo-retry"), str(of_id))
    except Exception:  # noqa: BLE001  (unknown: nothing sent, the failed reversal stays the record)
        return False


def _send_one(w, route, body, call, wire, creator, values, start=None) -> dict:
    """One undo Write's Relay call (the Relay's method, `relay_method`, else the Write's); the last wire line of the
    Write's own OnlyFans method after it gives the path, status and seq verify_undo checks (ticket 131; None: none).
    `start`: (wire seq, time) the undo began at, when something went out before this call (ticket 67's upload)."""
    seq0, t0 = start or (max((e["seq"] for e in wire()), default=0), time.time())
    relay_status, _ = call((w.relay_method or w.method).upper(), route, body, account=creator)
    line = ([e for e in wire() if e["seq"] > seq0 and e["method"] == w.method.upper()] or [None])[-1]
    return {"method": w.method.upper(), "path": line["path"] if line else fill(w.path, values),
            "status": line["status"] if line else None, "seq": line["seq"] if line else None, "relay": route,
            "relay_status": relay_status, "sent": t0, "done": time.time(), "at": t0}


def _upload_item(status, reply):
    """Ticket 67: the upload route's item when it answered one (200, a JSON object with a non-empty processId), else
    None: any other reply is a refused upload, so no write carrying it (`{header: null}` or `""` clears the picture)."""
    if status != 200:
        return None
    try:
        item = json.loads(reply)
    except (TypeError, ValueError):
        return None
    return item if isinstance(item, dict) and isinstance(item.get("processId"), str) and item["processId"] else None


def _put_back(w, i, values, call, creator, kept, at) -> tuple[dict | None, dict]:
    """Ticket 67, a Write with `relay_upload`: (its record when nothing more is sent, else None; the values its body
    fills). It is always sent (one after-write read cannot prove the write never lands); it first posts its kept
    picture (`kept`, `keep`'s) to the upload route, whose item fills `{upload}`; a refused upload (`_upload_item`)
    sends nothing more (its record has no seq). Each record's `at` is when the undo went out
    (`row_problem` tells the undo's hits from the write's by it)."""
    up = w.relay_upload
    if not up:
        return None, values
    path = fill(w.path, values)
    status, reply = call("POST", up.route, account=creator, form=multipart({**up.fields, "file": (kept or {})[i]}))
    item = _upload_item(status, reply)
    if item is None:
        return {"method": w.method.upper(), "path": path, "status": None, "seq": None, "relay": up.route,
                "relay_status": status, "at": at, "refused": "the upload route answered no upload item"}, values
    return None, {**values, "upload": item}


def _send_all(proof, rows, call, wire, values, sent, creator, before, kept=None, read=None) -> list:
    """Each row's undo Writes (`row_undos`), by undo Write then row: [(reversals, the first Write not sent or None)]
    per row. A Write whose placeholders are not all known is not sent, nor any of that row after it. A request another
    row already sent (`sent`: ticket 30's hide, for the upload row and a second post) is not sent again; the row takes
    its record; nor one the trigger already sent 2xx (`trigger_reversal`, ticket 34). Follow-up #6 / round 2 #21: where
    the Write's `max` leaves the guard room for a second one (the PPV's 2), the trigger's reversal is the undo only
    while a fresh read no longer shows the row's item (`still_shown`): still shown (a non-2xx, or a 2xx such as OF's
    `{"success": false}`), the driver sends its own; gone, or the read failed, the trigger's line stays the record
    (non-2xx: the row closes FAILED for the owner; a second DELETE of an item already gone would only answer 404).
    A picture put back (ticket 67) goes through `_put_back` first. Each record names the wire seq its call caused
    (None: none), the line verify_undo checks (ticket 131)."""
    out = [([], None) for _ in rows]
    for i, w in enumerate(proof.undo):
        for n, r in enumerate(rows):
            revs, unsent = out[n]
            if unsent is not None or i not in {k for k, _ in row_undos(proof, r)}:
                continue
            v = values(r)
            route = fill(w.relay, v) if w.relay else None
            if route is None or "{" in route or "{" in fill(w.path, v):
                out[n] = (revs, w)
                continue
            method = (w.relay_method or w.method).upper()
            made = None if (method, route) in sent else trigger_reversal(w, r, fill(w.path, v), wire())
            if made is not None and w.max > 1 and still_shown(read, r.get("of_id")):
                made = None   # follow-up #6 / round 2 #21: the item is still there (in-page reply failed, or 2xx with
                #               `success: false`): send our own
            if made is not None:   # the trigger's own reversal is the record; nothing is sent again (ticket 34)
                sent[method, route] = {"method": made["method"], "path": made["path"], "status": made["status"],
                                       "seq": made["seq"], "relay": None, "relay_status": None, "by": "trigger"}
            if (method, route) not in sent:
                start = (max((e["seq"] for e in wire()), default=0), time.time())
                done, filled = _put_back(w, i, v, call, creator, kept, start[1])
                if done is not None:
                    sent[method, route] = done
                else:
                    body = (w.relay_body(before) if callable(w.relay_body)   # ticket 60: a setting put back
                            else fill(dict(w.relay_body), filled) if w.relay_body else None)
                    sent[method, route] = _send_one(w, route, body, call, wire, creator, v, start)
            revs.append(sent[method, route])
    return out


def _chain(proof, row, call, wire, creator, after, values) -> tuple[list, str, dict]:
    """Ticket 100: the undo Writes as a fallback chain (Proof.undo_ids), each tried in order until one is answered 2xx
    on the wire; before a later one its other ids (`undo_ids(after-write read, OnlyFans id, Proof fan)`) are
    registered through `/__proof/read-id`, read off the row's id. (attempts, reason, ids registered): reason is ""
    when one took or none was sent (verify_undo then closes the row FAILED), else why none took."""
    of_id, attempts, got = row.get("of_id"), [], {}
    for i, w in enumerate(proof.undo):
        if of_id is None or not w.relay:
            break
        if i:
            more = proof.undo_ids(after, of_id, values.get("proof_fan")) or {}
            missing = [k for k, v in more.items() if v is None] or ([] if more else ["ids"])
            refused = f"no {', '.join(missing)} in the after-write read" if missing else None
            for k, v in more.items() if refused is None else ():
                if str(v) in (values.get(k), got.get(k)):
                    continue
                status, text = _read_id(call, row, k, v, of_id, creator)
                if status != 200:   # the Relay's own read did not show it: this Write is never sent
                    refused = f"POST /__proof/read-id of {k}={v} answered {status}: {text[:200]!r}"
                    break
                got[k] = str(v)
            if refused is not None:
                attempts.append({"method": w.method.upper(), "relay": w.relay, "skipped": refused})
                continue
            values = {**values, **{k: str(v) for k, v in more.items()}}
        route = fill(w.relay, values)
        body = fill(dict(w.relay_body), values) if w.relay_body and not callable(w.relay_body) else None
        attempts.append(_send_one(w, route, body, call, wire, creator, values))
        if _ok(attempts[-1]["status"]):
            return attempts, "", got
    tried = [a for a in attempts if "skipped" not in a]
    reason = "" if not tried else "; ".join(f"{a['method']} {a.get('path', a['relay'])} "
                                            + (a["skipped"] if "skipped" in a else f"answered {a['status']}")
                                            for a in attempts)
    return attempts, reason, got


def _steps(proof, call, wire, read, creator, before, keys) -> tuple[list, list]:
    """Ticket 96: the confirmed sequence (Proof.undo_steps), once for all of a proof's rows. Each step (undo Write
    `k`, body, confirm) is sent, its route and body filled with `{account}`, then confirmed by a fresh read tagged
    `after-undo-step-{n}` (taken only when the Relay answered 2xx); an unconfirmed step stops it. (steps sent,
    problems)."""
    out, problems = [], []
    for n, (k, body, confirm) in enumerate(proof.undo_steps(before), 1):
        w, values = proof.undo[k], {**keys, "account": creator}
        route = fill(w.relay, values)
        body = fill(dict(body), values) if body is not None else None
        step = {**_send_one(w, route, body, call, wire, creator, values), "body": body}
        fresh, failed = None, ""
        if _ok(step["relay_status"]):
            try:
                fresh = read(f"after-undo-step-{n}")
            except Exception as e:  # noqa: BLE001  (unconfirmed: the sequence stops)
                failed = f"its fresh read failed: {type(e).__name__}: {e}"
        step["confirmed"] = fresh is not None and bool(confirm(fresh))
        out.append(step)
        if not step["confirmed"]:   # the next step is never sent on an unconfirmed one
            what = route + (f" {json.dumps(body)}" if body is not None else "")
            problems.append(f"undo step {n} ({what}) " + (failed or f"answered {step['relay_status']}" if fresh is None
                                                         else "not confirmed by the fresh read"))
            break
    return out, problems


def settle_rows(proof, rows, call, wire, read, *, creator, before, after, effect, keys, sent, res, fan=None,
                kept=None, folder=None, clock=time.monotonic, sleep=time.sleep) -> list:
    """Steps 11-12 for these Undo log rows of one proof, in the order given (`undo_order`): their undo (`_send_all`,
    `_chain` or `_steps`), one after-undo read, then each row's closing snapshot, whose state verify_undo decides;
    problems and the closed rows go into `res`; the closed rows are returned in order. A row with an unsent undo (no
    OnlyFans id: its write not found; no undo key registered) closes FAILED; a chain refused to its end
    NOT_REVERSIBLE_REFUSED with its reason (ticket 100: a row whose OnlyFans id an earlier row's chain took back
    reuses it, so the publish row sends no second unsend). Ticket 67: a kept picture must read back as the same picture
    (`restored`, written into `folder`), else the row closes FAILED: once the re-upload went out, the after-undo read
    is retaken (`clock`/`sleep`, up to RESTORE_WAIT) until it names a cover URL other than the before and after-write
    ones that is the kept picture; each new URL is fetched once, and the last one decides at the deadline."""
    rows = list(rows)
    if not rows:   # an undo sequence is never sent for no row
        return []

    def values(r):
        of_id = r.get("of_id")
        return {**keys, "account": creator, **({"id": of_id} if of_id is not None else {})}

    plans = []   # per row: (reversals, extra closed fields, problems before verify_undo, reason)
    if proof.undo_steps is not None:
        if "sequence" not in res:
            res["sequence"], res["sequence_problems"] = _steps(proof, call, wire, read, creator, before, keys)
        plans = [(list(res["sequence"]), {}, [f"row {r['row']}: {p}" for p in res["sequence_problems"]], "")
                 for r in rows]
    elif proof.undo_ids is not None:
        fan_v, chained = int(fan) if str(fan or "").isdigit() else fan, []
        for r in rows:
            oid = r.get("of_id")
            earlier = next((c for c in [*res.get("closed", []), *chained]
                            if oid is not None and c.get("of_id") == oid and c.get("attempts") is not None), None)
            if earlier is None:
                attempts, reason, got = _chain(proof, r, call, wire, creator, after,
                                               {**values(r), "fan": fan_v, "proof_fan": fan})
                chained.append({"row": r["row"], "of_id": oid, "attempts": attempts, "reason": reason,
                                "reversals": [a for a in attempts if "skipped" not in a][-1:],
                                **({"keys": got} if got else {})})
                plans.append((chained[-1]["reversals"], {k: chained[-1][k] for k in ("attempts", "keys")
                                                          if k in chained[-1]}, [], reason))
                continue
            extra = {k: earlier[k] for k in ("attempts", "keys") if k in earlier}
            plans.append((list(earlier.get("reversals") or []), {**extra, "reused_from": earlier["row"]}, [],
                          earlier.get("reason", "")))
    else:
        for r, (revs, unsent) in zip(rows, _send_all(proof, rows, call, wire, values, sent, creator, before,
                                                     kept, read)):
            miss = ([f"row {r['row']}: undo {unsent.method.upper()} {unsent.path} not sent: its ids are unknown"]
                    if unsent is not None and revs else [])   # none sent: verify_undo already names it
            plans.append((revs, {}, miss, ""))
    kept = kept or {}
    # ticket 67: the cover URLs the restore must leave (every upload gets a new one, measured); no wait when the
    # re-upload never went out (refused, or an undo not sent: the row fails on that)
    olds = {i: {_served(proof, i, r) for r in (before, after)} for i in kept}
    wait = bool(kept) and all(not miss and revs and not any(rv.get("refused") for rv in revs)
                              for revs, _, miss, _ in plans)
    fetched, urls, back_ok, deadline, polls, err = {}, {}, {}, clock() + RESTORE_WAIT, 0, None
    while True:
        polls += 1
        try:
            after_undo, err = read("after-undo"), None
        except Exception as e:  # noqa: BLE001
            after_undo, err = None, e
        for i in kept:
            url = _served(proof, i, after_undo)
            if url and url not in olds[i] and url != urls.get(i):   # a new cover: fetched once
                urls[i], fetched[i] = url, _download(call, url, creator)
                back_ok[i] = (fetched[i][0] == 200 and bool(fetched[i][1])
                              and picture_match(kept[i][1], fetched[i][1], reuploaded=True)["ok"])
        if not wait or all(back_ok.get(i) for i in kept) or clock() >= deadline:
            break
        sleep(RESTORE_STEP)
    if err is not None:
        res["problems"].append(f"after-undo read failed: {err}")
    same, out = proof.same or reads_equal, []   # ticket 67: a picture put back by a new upload reads back its own way
    for r, (revs, extra, early, reason) in zip(rows, plans):
        extra = dict(extra)
        ks = {**keys, **extra.pop("keys", {})}
        closed = {**r, "of_id": r.get("of_id"), "effect": effect, "reversals": revs, **extra,
                  "reads": {"before": before, "after_write": after, "after_undo": after_undo}}
        if ks:
            closed["keys"] = ks
        problems = verify_undo(wire(), [closed], same) + early
        pictures, back, wrong = restored(proof, r, kept, fetched, folder)
        for i in kept:
            pictures[str(i)].update(polls=polls)
        if pictures:
            closed["reads"]["pictures"] = pictures
        problems += wrong
        if reason:   # ticket 100: no unsend took it back
            closed["reason"] = reason
            res["problems"].append(f"row {r['row']}: {NOT_REVERSIBLE_REFUSED}: {reason}")
        else:
            res["problems"] += problems
        closed["reads"]["equal"] = (before is not None and after_undo is not None and bool(same(before, after_undo))
                                    and not wrong)
        closed.update(state=NOT_REVERSIBLE_REFUSED if reason else "FAILED" if problems else "undone",
                      closed=datetime.now(timezone.utc).isoformat(),
                      evidence=[*res["screens"], *([res["seen"]] if res.get("seen") else []),
                                *(f"{proof.id}/{k[0]}" for k in (kept or {}).values()),
                                *(f"{proof.id}/{n}" for n in back),
                                f"of-read-{proof.id}-before.json", f"of-read-{proof.id}-after-undo.json"])
        res.setdefault("closed", []).append(closed)
        out.append(closed)
    return out




def arm_hit(writes, h) -> bool:
    """Whether a FakeOF hit is one of these Writes (method and path template)."""
    return any(h["method"] == w.method.upper() and _template(_api(w.path)).match(_api(h["path"])) for w in writes)


def _window(c) -> tuple[float, float]:
    return datetime.fromisoformat(c["opened"]).timestamp(), datetime.fromisoformat(c["closed"]).timestamp()


def _sequence_problem(proof, c, closed_rows, plain) -> str | None:
    """Ticket 96: the row's write once in its window outside the steps' own (they share its path), each step's hit
    once inside its own call, 2xx."""
    opened, closed = _window(c)
    steps = [(s["sent"], s["done"]) for s in c.get("reversals") or []]
    got = sorted((h for h in plain if h["method"] == c["write"]["method"] and h["path"] == c["write"]["path"]
                  and opened <= h["t"] <= closed and not any(a <= h["t"] <= b for a, b in steps)), key=lambda h: h["t"])
    same = sum(1 for x in closed_rows if x["write"] == c["write"] and x["opened"] >= c["opened"])
    out = []
    if len(got) != same or got[0]["status"] != c.get("write_status", got[0]["status"]):
        out.append(f"row {c['row']} ({proof.id}): FakeOF did not show {c['write']['method']} {c['write']['path']} "
                   f"once ({[(h['method'], h['path'], h['status']) for h in got]})")
    for k, s in enumerate(c.get("reversals") or [], 1):
        hit = [h for h in plain if h["method"] == s["method"] and h["path"] == s["path"]
               and s["sent"] <= h["t"] <= s["done"]]
        if len(hit) != 1 or not _ok(hit[0]["status"]):
            out.append(f"row {c['row']} ({proof.id}): FakeOF did not show undo step {k} {s['method']} {s['path']} "
                       f"once, 2xx ({[(h['path'], h['status']) for h in hit]})")
    return "; ".join(out) or None


def _write_hits(proof, c, plain) -> list:
    """The row's write hits in its window. A write that reached FakeOF before its row opened is missed, so the row
    fails (opened first)."""
    opened, closed = _window(c)
    return [h for h in plain if h["path"] == c["write"]["path"] and arm_hit(proof.arm, h)
            and opened <= h["t"] <= closed]


def _write_then_undos(proof, c, closed_rows, writes, undos, want, late=()) -> str | None:
    """The row's write once per row on its path opened since this one (no retry reached it; ticket 97: B's two
    posts), then exactly `want` undo hits, all 2xx, before the row closed. Ticket 97: a write OnlyFans refused (4xx,
    no id), or committed then answered 5xx (found after), is shown with the status the row recorded. Only rows opened
    inside this row's window count (ticket 99: a proof settled in phases). Ticket 67: no `late` write-shaped hit
    after the undo went out."""
    opened, closed = _window(c)
    same = sum(1 for x in closed_rows if x["write"]["path"] == c["write"]["path"]
               and opened <= datetime.fromisoformat(x["opened"]).timestamp() <= closed)
    write_ok = writes and (_ok(writes[0]["status"]) or writes[0]["status"] == c.get("write_status"))
    ok = (not late and len(writes) == same and want and len(undos) == want and write_ok
          and (not undos or (writes[0]["t"] < min(h["t"] for h in undos) and max(h["t"] for h in undos) <= closed))
          and all(_ok(h["status"]) for h in undos))
    return None if ok else (f"row {c['row']} ({proof.id}): FakeOF did not show {c['write']['method']} "
                            f"{c['write']['path']} then its undo of {c.get('of_id')} ({len(writes)} write hits after "
                            f"the row opened, {len(undos)} undo hits, {len(late)} write hits after its undo went out)")


def _chain_problem(proof, c, closed_rows, plain) -> str | None:
    """Ticket 100: each attempt the chain sent shows exactly once in the row's window (a refused try may come
    first); the last one is the undo."""
    opened, closed = _window(c)
    tried = [a for a in c["attempts"] if "skipped" not in a]
    each = [[h for h in plain if h["method"] == a["method"] and h["path"] == a["path"]
             and opened <= h["t"] <= closed] for a in tried]
    undos = [each[-1][0]] if tried and all(len(x) == 1 for x in each) else []
    return _write_then_undos(proof, c, closed_rows, _write_hits(proof, c, plain), undos, 1)


def row_problem(proof, c, closed_rows, plain) -> str | None:
    """Fake mode's per-row check (Testing Decisions seam 1): FakeOF showed the closed row `c`'s write inside its window,
    then each of its own undo Writes (`row_undo_hits`, ticket 131: in the window, the hide on the row's media id), all
    2xx; None when it did, else the problem. `closed_rows`: the proof's closed rows (a retry would add write hits).
    A sequence (ticket 96) is checked step by step (`_sequence_problem`); a fallback chain (ticket 100) by each
    attempt it sent (`_chain_problem`). Else one rule tells an undo that sends the write's own request again (ticket
    60's setting put back, ticket 67's cover upload and PATCH) from the write: the write-shaped hits (any arm) before
    the row's undo went out (its records' earliest `at`; none: the row's close) are writes, those after are its undo's
    (an undo the trigger itself sent, ticket 34, is no write-shaped hit, so it counts at any time); a write-shaped hit
    after that the row's undo Writes, or the proof's undo Writes reversing no row (`reverses=()`, ticket 67's upload
    sent again), do not account for is a problem (a late or duplicate write)."""
    if proof.undo_steps is not None:
        return _sequence_problem(proof, c, closed_rows, plain)
    if c.get("attempts") is not None:
        return _chain_problem(proof, c, closed_rows, plain)
    cut = min((rv["at"] for rv in c.get("reversals") or [] if rv.get("at") is not None), default=float("inf"))
    shaped = _write_hits(proof, c, plain)
    writes = [h for h in shaped if h["t"] < cut]
    # the row's own undo Writes (by its arm index); an upload row's hide may be the post row's (sent once)
    mine = [w for _, w in row_undos(proof, c)]
    undos = ([] if c.get("of_id") is None and needs_row_id(proof, c) else
             [h for h in row_undo_hits(proof, c, plain) if h["t"] >= cut or not arm_hit(proof.arm, h)])
    side = [w for w in proof.undo if w.reverses == ()]
    late = [h for h in shaped if h["t"] >= cut and all(h is not u for u in undos) and not arm_hit(side, h)]
    return _write_then_undos(proof, c, closed_rows, writes, undos, len(mine), late)
