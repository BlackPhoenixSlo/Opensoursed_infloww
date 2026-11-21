"""undo_log: the Undo log (ticket 03) and the driver's checks over it, split out of proof_core (file size): its JSONL
helpers (`append_jsonl`, `read_undo_log`, the only I/O, shared by its two writers, the Relay and the driver), the
per-row and whole-log checks against the wire log (`verify_undo`, `check_undo_log`, `pending_rows`), the undo Writes
a row takes and their order (`row_undos`, `undo_order`, `needs_row_id`), fake mode's per-row hits (`row_undo_hits`)
and the log as Markdown (`undo_markdown`). Pure but for the two file helpers; stdlib only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping

from proof_core import NOT_REVERSIBLE, READS, Proof, _api, _bind, _names, _req, _template, declared_kinds


def undo_rows(lines) -> list:
    """The Undo log's rows from its JSONL lines: each line is a whole-row snapshot, the last one per row wins.
    ASSUMPTION: the Relay opens a row (`pending`) and the driver closes it, each appending a snapshot, so a crash
    leaves the last true state on disk (rung 4: append-only); overturned if one writer must own the file."""
    rows = {}
    for line in lines:
        rows[line["row"]] = line
    return [rows[k] for k in sorted(rows)]


def append_jsonl(path, rec: dict) -> None:
    """One whole-row snapshot (or wire line), flushed and fsynced before returning: `undo_rows`' crash safety."""
    import json
    import os
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_undo_log(path) -> list:
    """The Undo log file's rows, folded (`undo_rows`); a missing file has none."""
    import json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return []
    return undo_rows(json.loads(x) for x in p.read_text().splitlines() if x.strip())


def reads_equal(a, b) -> bool:
    """Two OnlyFans-side reads compared as JSON values (a tuple equals its list; key order is ignored)."""
    import json
    if a is None or b is None:
        return False
    norm = lambda v: json.dumps(v, sort_keys=True, default=str)  # noqa: E731
    return norm(a) == norm(b)


def verify_undo(wire, undo_entries, same=reads_equal) -> list:
    """Problems with each Undo log row about to be closed; a row with none closes `undone`, else `FAILED`.

    A row carries `effect` (the proof's declared effect on its before/after-write reads), `reversal` {method, path,
    seq} (or `reversals`, ticket 30) as sent, and `reads` {before, after_undo}. The reversal's status is taken from the
    wire log, never from the row: the line `seq` names (the one its own undo caused, ticket 131; None: it caused none)
    must be a completed `reversal` line of that method and path, and 2xx. The whole-log cases (missing rows, `pending`
    rows left by a crash) are `check_undo_log`'s. `same(before, after_undo)`: the proof's own comparison (ticket 67,
    `Proof.same`), else the two reads equal."""
    out = []
    for r in undo_entries:
        n, w, rd = r.get("row"), r.get("write") or {}, r.get("reads") or {}
        write = f"{w.get('method', '')} {w.get('path', '')}".strip()
        if r.get("effect") is False:
            out.append(f"row {n}: no-op write: the declared effect did not hold after {write}")
        revs = _reversals(r)
        for rv in revs or [{}]:
            lines = [e for e in wire if e.get("verdict") == "reversal" and rv and rv.get("seq") is not None
                     and e.get("seq") == rv["seq"]
                     and e.get("method") == str(rv.get("method", "")).upper() and e.get("path") == rv.get("path")]
            if not lines:
                out.append(f"row {n}: no reversal of {write} on the wire"
                           + (f" ({rv['method']} {rv['path']})" if len(revs) > 1 else ""))
            elif not (isinstance(lines[-1].get("status"), int) and 200 <= lines[-1]["status"] < 300):
                out.append(f"row {n}: reversal {_req(lines[-1])} answered {lines[-1].get('status')}")
        if rd.get("before") is None or rd.get("after_undo") is None or not same(rd["before"], rd["after_undo"]):
            out.append(f"row {n}: the after-undo read differs from the before read")
    return out


def row_undos(proof: Proof, row) -> list:
    """The declared undo Writes that reverse this Undo log row, as (index, Write) in declared order (ticket 30): those
    whose `reverses` names the row's arm index (stamped by the Relay when it opens the row) and every one whose
    `reverses` is None. A row with no arm stamp gets only the latter; a refused row (`_refused`) none naming `{id}`."""
    arm = row.get("arm")
    return [(i, w) for i, w in enumerate(proof.undo) if (w.reverses is None or (arm is not None and arm in w.reverses))
            and not (_refused(row) and _names_id(w))]


def _refused(row) -> bool:
    """A write OnlyFans refused (ticket 97: B's second post answered 400): a 4xx and no OnlyFans id, so nothing to
    delete. A 5xx (a Relay 502 included) is not: OnlyFans may have committed before answering, so its row keeps the
    `{id}` undo and goes to the lost-reply finder (story 53)."""
    s = row.get("write_status")
    return isinstance(s, int) and 400 <= s < 500 and row.get("of_id") is None


def _names_id(w) -> bool:
    """Whether undo Write `w` needs a row's own OnlyFans id: `{id}` in its path, its Relay route or its pinned Relay
    body (ticket 60: a body function names none)."""
    return ("id" in _template(w.path).groupindex or bool(w.relay) and "id" in _template(w.relay).groupindex
            or "id" in _names(w.relay_body if isinstance(w.relay_body, Mapping) else {}))


def undo_order(proof: Proof, rows) -> list:
    """The rows in the order the driver settles them: by the first undo Write each takes, then open order, so an
    undo several rows share is sent by the row that declares it with the undos before it (ticket 30: the post's
    DELETE, then the hide; the upload rows after, the hide not sent again). A row with no undo goes last."""
    def rank(r):
        return min((i for i, _ in row_undos(proof, r)), default=len(proof.undo))
    return sorted(rows, key=lambda r: (rank(r), r.get("row", 0)))


def needs_row_id(proof: Proof, row) -> bool:
    """Whether this row's undo needs its own OnlyFans id (`_names_id`), so a row that has none
    goes to the proof's lost-reply finder (story 53). An upload row, reversed by the hide keyed on `undo_keys`, does
    not."""
    return any(_names_id(w) for _, w in row_undos(proof, row))


def row_undo_hits(proof: Proof, row, hits) -> list:
    """Fake mode's check (ticket 131): FakeOF hits of this closed row's own undo Writes (`row_undos`), inside its window
    (opened <= t <= closed), a path `{id}` equal to the row's OnlyFans id when it has one, and each `{name}` of a pinned
    body, or of its path when a declared kind, equal to the id the row recorded in `keys[name]` (a hide of another
    media id, or an earlier proof's identical hide, is not this row's)."""
    opened = datetime.fromisoformat(row["opened"]).timestamp()
    closed = datetime.fromisoformat(row["closed"]).timestamp()
    oid, keys, kinds = row.get("of_id"), row.get("keys") or {}, declared_kinds(proof)

    def one(w, h):
        m = h["method"] == w.method.upper() and _template(_api(w.path)).match(_api(h["path"]))
        if not m or (oid is not None and m.groupdict().get("id", oid) != oid):
            return False
        if any(str(keys.get(k)) != v for k, v in m.groupdict().items() if k in kinds):   # ticket 100's {message}
            return False
        got = {} if w.body_must is None else _bind(dict(w.body_must), h.get("body"), True)
        return got is not None and all(k in keys and str(keys[k]) == v for k, v in got.items())

    return [h for h in hits if opened <= h["t"] <= closed and any(one(w, h) for _, w in row_undos(proof, row))]


def _reversals(r) -> list:
    """A row's reversals as sent, in order: `reversals` (ticket 30, one or more), else the single `reversal`."""
    if r.get("reversals") is not None:
        return list(r["reversals"])
    return [r["reversal"]] if r.get("reversal") else []


def _row_write(r) -> str:
    w = r.get("write") or {}
    return f"{w.get('method', '')} {w.get('path', '')}".strip()


def _row_id(r) -> str:
    oid = r.get("of_id")
    lost = str(r.get("write_status") or "")
    return f"OnlyFans id {oid}" if oid else "OnlyFans id unknown" + (f", {lost}" if lost.startswith("reply lost") else "")


def _left(r):
    """What the after-undo read still shows beyond the before read, when both are lists: the change left behind."""
    import json
    rd = r.get("reads") or {}
    before, after = rd.get("before"), rd.get("after_undo")
    if not isinstance(before, (list, tuple)) or not isinstance(after, (list, tuple)):
        return None
    norm = lambda v: json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)  # noqa: E731
    had = {norm(x) for x in before}
    return [norm(x) for x in after if norm(x) not in had]


def pending_rows(rows) -> list:
    """Every `pending` row (a write recorded before it was forwarded and never closed: a crash, a lost reply) named
    with the change it may have left (story 52). An earlier run's pending row refuses every new run until the owner
    clears it by hand: appending `{"row": N, "state": "cleared by hand", ...}` to that undo-log.jsonl (last wins)."""
    return [f"row {r.get('row')} ({r.get('proof')}) pending: {_row_write(r)} ({_row_id(r)}) may be left on the "
            "account; check it, then clear the row by hand" for r in rows if r.get("state") == "pending"]


def check_undo_log(wire, rows) -> list:
    """The whole Undo log against the whole wire log, at the end of a run: [] only when complete.

    `wire`: folded wire lines (last per seq); `rows`: folded Undo log rows (`undo_rows`). Missing: an allowed write
    with no row (`wire_seq`). Failed: a FAILED row, named with what the after-undo read still shows. Pending: a row
    never closed. Any other state but `undone` and `not reversible, owner go` is not confirmed undone."""
    out = []
    for r in rows:
        state, n, proof = r.get("state"), r.get("row"), r.get("proof")
        if state in ("undone", NOT_REVERSIBLE):
            continue
        if state == "pending":
            out += pending_rows([r])
        elif state == "FAILED":   # "left on the account" only for what the after-undo read still shows
            left, refused = _left(r), (f"; {r['found_refused']}" if r.get("found_refused") else "")
            out.append(f"row {n} ({proof}) FAILED, owner action: "
                       + (f"{_row_write(r)} ({_row_id(r)}) left on the account: {', '.join(left)}" if left else
                          f"confirm {_row_write(r)} ({_row_id(r)}) is gone; the after-undo read shows "
                          + ("nothing left" if left == [] else "no list to compare")) + refused)
        else:
            out.append(f"row {n} ({proof}) {state}: {_row_write(r)} ({_row_id(r)}) not confirmed undone")
    seqs = {r.get("wire_seq") for r in rows}
    for e in wire:
        if e.get("verdict") == "allow" and e.get("method") not in READS and e.get("seq") not in seqs:
            out.append(f"wire line {e.get('seq')}: {_req(e)} was allowed with no Undo log row")
    return out


def _cell(v) -> str:
    import json
    s = v if isinstance(v, str) else json.dumps(v, separators=(",", ":"), default=str)
    s = s if len(s) <= 80 else s[:77] + "..."
    return s.replace("|", "\\|").replace("\n", " ")


def undo_markdown(rows) -> str:
    """The Undo log as one Markdown table, one row per entry, for the PR body unedited."""
    head = ["#", "proof", "write", "narrowed", "OnlyFans id", "reversal", "before", "after write", "after undo",
            "before = after undo", "state", "evidence"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        w, rd = r.get("write") or {}, r.get("reads") or {}
        rev = "; ".join(f"{rv['method']} {rv['path']} → {rv.get('status')}" for rv in _reversals(r) if rv.get("method"))
        eq = {True: "yes", False: "no"}.get(rd.get("equal"), "")
        cells = [r.get("row"), r.get("proof", ""), f"{w.get('method', '')} {w.get('path', '')}".strip(),
                 w.get("narrowed", ""), r.get("of_id") or "", rev, rd.get("before", ""), rd.get("after_write", ""),
                 rd.get("after_undo", ""), eq, r.get("state", ""), ", ".join(r.get("evidence") or ())]
        out.append("| " + " | ".join(_cell("" if c is None else c) for c in cells) + " |")
    return "\n".join(out) + "\n"
