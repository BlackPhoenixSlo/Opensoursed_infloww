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

UPLOAD_MAX = 5 * 1024 * 1024
_SNIFF = ((b"\xff\xd8\xff", "image/jpeg", ".jpg"), (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
          (b"GIF8", "image/gif", ".gif"))


def picture_type(data: bytes) -> tuple | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return next(((t, e) for magic, t, e in _SNIFF if data.startswith(magic)), None)


def picture_size(data: bytes) -> tuple | None:
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
    kind, size = picture_type(data), picture_size(data)
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "type": kind[0] if kind else None,
            "width": size[0] if size else None, "height": size[1] if size else None}


def _download(call, url, creator) -> tuple:
    status, data = call("GET", "/img?u=" + quote(str(url), safe=""), account=creator)
    return status, data or b""


def multipart(fields: dict) -> tuple:
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


RESTORE_WAIT, RESTORE_STEP, RESTORE_MAX_DIFF = 60.0, 3.0, 12.0


def picture_match(kept: bytes, got: bytes, reuploaded: bool = False) -> dict:
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
    return proof.undo[i].relay_upload.picture(read_value) if read_value else None


def restored(proof, row, kept, fetched, folder) -> tuple:
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
    return next((i for i, w in enumerate(proof.undo) if w.relay_upload), None)


def kept_files(proof, folder) -> list:
    i = _picture_undo(proof)
    return sorted((Path(folder) / proof.id).glob(f"undo-{i}-before.*")) if i is not None else []


def reverify(proof, folder, read, call, creator, out=None) -> dict:
    i, file = _picture_undo(proof), kept_files(proof, folder)[0]
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
    return bool(proof.undo_keys) and row.get("of_id") is not None and needs_row_id(proof, row)


def _read_id(call, row, key, of_id, source, creator):
    return call("POST", "/__proof/read-id", {"row": row["row"], "key": key, "of_id": str(of_id), "source": str(source)},
                account=creator)


def register_keys(proof, row, before, after_write, call, problems, keys=None, creator=None) -> dict:
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
    if "id" not in _template(w.path).groupindex or row.get("wire_seq") is None:
        return None
    return next((e for e in sorted(lines, key=lambda e: e["seq"])
                 if e.get("verdict") == "reversal" and e["seq"] > row["wire_seq"] and e.get("status") is not None
                 and e["method"] == w.method.upper() and _api(e["path"]) == _api(path)), None)


def _ok(status) -> bool:
    return isinstance(status, int) and 200 <= status < 300


def _shows_id(v, of_id: str) -> bool:
    if isinstance(v, Mapping):
        return any(_shows_id(x, of_id) for k, x in v.items() if not str(k).startswith("_"))
    if isinstance(v, (list, tuple)):
        return any(_shows_id(x, of_id) for x in v)
    return not isinstance(v, bool) and v is not None and str(v) == of_id


def still_shown(read, of_id) -> bool:
    if read is None or of_id is None:
        return False
    try:
        return _shows_id(read("before-undo-retry"), str(of_id))
    except Exception:  # noqa: BLE001  (unknown: nothing sent, the failed reversal stays the record)
        return False


def _send_one(w, route, body, call, wire, creator, values, start=None) -> dict:
    seq0, t0 = start or (max((e["seq"] for e in wire()), default=0), time.time())
    relay_status, _ = call((w.relay_method or w.method).upper(), route, body, account=creator)
    line = ([e for e in wire() if e["seq"] > seq0 and e["method"] == w.method.upper()] or [None])[-1]
    return {"method": w.method.upper(), "path": line["path"] if line else fill(w.path, values),
            "status": line["status"] if line else None, "seq": line["seq"] if line else None, "relay": route,
            "relay_status": relay_status, "sent": t0, "done": time.time(), "at": t0}


def _upload_item(status, reply):
    if status != 200:
        return None
    try:
        item = json.loads(reply)
    except (TypeError, ValueError):
        return None
    return item if isinstance(item, dict) and isinstance(item.get("processId"), str) and item["processId"] else None


def _put_back(w, i, values, call, creator, kept, at) -> tuple[dict | None, dict]:
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
                made = None
            if made is not None:
                sent[method, route] = {"method": made["method"], "path": made["path"], "status": made["status"],
                                       "seq": made["seq"], "relay": None, "relay_status": None, "by": "trigger"}
            if (method, route) not in sent:
                start = (max((e["seq"] for e in wire()), default=0), time.time())
                done, filled = _put_back(w, i, v, call, creator, kept, start[1])
                if done is not None:
                    sent[method, route] = done
                else:
                    body = (w.relay_body(before) if callable(w.relay_body)
                            else fill(dict(w.relay_body), filled) if w.relay_body else None)
                    sent[method, route] = _send_one(w, route, body, call, wire, creator, v, start)
            revs.append(sent[method, route])
    return out


def _chain(proof, row, call, wire, creator, after, values) -> tuple[list, str, dict]:
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
                if status != 200:
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
        if not step["confirmed"]:
            what = route + (f" {json.dumps(body)}" if body is not None else "")
            problems.append(f"undo step {n} ({what}) " + (failed or f"answered {step['relay_status']}" if fresh is None
                                                         else "not confirmed by the fresh read"))
            break
    return out, problems


def settle_rows(proof, rows, call, wire, read, *, creator, before, after, effect, keys, sent, res, fan=None,
                kept=None, folder=None, clock=time.monotonic, sleep=time.sleep) -> list:
    rows = list(rows)
    if not rows:
        return []

    def values(r):
        of_id = r.get("of_id")
        return {**keys, "account": creator, **({"id": of_id} if of_id is not None else {})}

    plans = []
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
                    if unsent is not None and revs else [])
            plans.append((revs, {}, miss, ""))
    kept = kept or {}
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
            if url and url not in olds[i] and url != urls.get(i):
                urls[i], fetched[i] = url, _download(call, url, creator)
                back_ok[i] = (fetched[i][0] == 200 and bool(fetched[i][1])
                              and picture_match(kept[i][1], fetched[i][1], reuploaded=True)["ok"])
        if not wait or all(back_ok.get(i) for i in kept) or clock() >= deadline:
            break
        sleep(RESTORE_STEP)
    if err is not None:
        res["problems"].append(f"after-undo read failed: {err}")
    same, out = proof.same or reads_equal, []
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
        if reason:
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
    return any(h["method"] == w.method.upper() and _template(_api(w.path)).match(_api(h["path"])) for w in writes)


def _window(c) -> tuple[float, float]:
    return datetime.fromisoformat(c["opened"]).timestamp(), datetime.fromisoformat(c["closed"]).timestamp()


def _sequence_problem(proof, c, closed_rows, plain) -> str | None:
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
    opened, closed = _window(c)
    return [h for h in plain if h["path"] == c["write"]["path"] and arm_hit(proof.arm, h)
            and opened <= h["t"] <= closed]


def _write_then_undos(proof, c, closed_rows, writes, undos, want, late=()) -> str | None:
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
    opened, closed = _window(c)
    tried = [a for a in c["attempts"] if "skipped" not in a]
    each = [[h for h in plain if h["method"] == a["method"] and h["path"] == a["path"]
             and opened <= h["t"] <= closed] for a in tried]
    undos = [each[-1][0]] if tried and all(len(x) == 1 for x in each) else []
    return _write_then_undos(proof, c, closed_rows, _write_hits(proof, c, plain), undos, 1)


def row_problem(proof, c, closed_rows, plain) -> str | None:
    if proof.undo_steps is not None:
        return _sequence_problem(proof, c, closed_rows, plain)
    if c.get("attempts") is not None:
        return _chain_problem(proof, c, closed_rows, plain)
    cut = min((rv["at"] for rv in c.get("reversals") or [] if rv.get("at") is not None), default=float("inf"))
    shaped = _write_hits(proof, c, plain)
    writes = [h for h in shaped if h["t"] < cut]
    mine = [w for _, w in row_undos(proof, c)]
    undos = ([] if c.get("of_id") is None and needs_row_id(proof, c) else
             [h for h in row_undo_hits(proof, c, plain) if h["t"] >= cut or not arm_hit(proof.arm, h)])
    side = [w for w in proof.undo if w.reverses == ()]
    late = [h for h in shaped if h["t"] >= cut and all(h is not u for u in undos) and not arm_hit(side, h)]
    return _write_then_undos(proof, c, closed_rows, writes, undos, len(mine), late)
