from __future__ import annotations

from datetime import datetime
from typing import Mapping

from proof_core import (NOT_REVERSIBLE, NOT_REVERSIBLE_REFUSED, READS, Proof, _api, _bind, _names, _req, _template,
                        declared_kinds)


def undo_rows(lines) -> list:
    rows = {}
    for line in lines:
        rows[line["row"]] = line
    return [rows[k] for k in sorted(rows)]


def append_jsonl(path, rec: dict) -> None:
    import json
    import os
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_undo_log(path) -> list:
    import json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return []
    return undo_rows(json.loads(x) for x in p.read_text().splitlines() if x.strip())


def reads_equal(a, b) -> bool:
    import json
    if a is None or b is None:
        return False
    norm = lambda v: json.dumps(v, sort_keys=True, default=str)  # noqa: E731
    return norm(a) == norm(b)


def verify_undo(wire, undo_entries, same=reads_equal) -> list:
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
    arm = row.get("arm")
    return [(i, w) for i, w in enumerate(proof.undo) if (w.reverses is None or (arm is not None and arm in w.reverses))
            and not (_refused(row) and _names_id(w))]


def _refused(row) -> bool:
    s = row.get("write_status")
    return isinstance(s, int) and 400 <= s < 500 and row.get("of_id") is None


def _names_id(w) -> bool:
    return ("id" in _template(w.path).groupindex or bool(w.relay) and "id" in _template(w.relay).groupindex
            or "id" in _names(w.relay_body if isinstance(w.relay_body, Mapping) else {}))


def undo_order(proof: Proof, rows) -> list:
    def rank(r):
        return min((i for i, _ in row_undos(proof, r)), default=len(proof.undo))
    return sorted(rows, key=lambda r: (rank(r), r.get("row", 0)))


def needs_row_id(proof: Proof, row) -> bool:
    return any(_names_id(w) for _, w in row_undos(proof, row))


def row_undo_hits(proof: Proof, row, hits) -> list:
    opened = datetime.fromisoformat(row["opened"]).timestamp()
    closed = datetime.fromisoformat(row["closed"]).timestamp()
    oid, keys, kinds = row.get("of_id"), row.get("keys") or {}, declared_kinds(proof)

    def one(w, h):
        m = h["method"] == w.method.upper() and _template(_api(w.path)).match(_api(h["path"]))
        if not m or (oid is not None and m.groupdict().get("id", oid) != oid):
            return False
        if any(str(keys.get(k)) != v for k, v in m.groupdict().items() if k in kinds):
            return False
        got = {} if w.body_must is None else _bind(dict(w.body_must), h.get("body"), True)
        return got is not None and all(k in keys and str(keys[k]) == v for k, v in got.items())

    return [h for h in hits if opened <= h["t"] <= closed and any(one(w, h) for _, w in row_undos(proof, row))]


def _reversals(r) -> list:
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
    import json
    rd = r.get("reads") or {}
    before, after = rd.get("before"), rd.get("after_undo")
    if not isinstance(before, (list, tuple)) or not isinstance(after, (list, tuple)):
        return None
    norm = lambda v: json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)  # noqa: E731
    had = {norm(x) for x in before}
    return [norm(x) for x in after if norm(x) not in had]


def pending_rows(rows) -> list:
    return [f"row {r.get('row')} ({r.get('proof')}) pending: {_row_write(r)} ({_row_id(r)}) may be left on the "
            "account; check it, then clear the row by hand" for r in rows if r.get("state") == "pending"]


def unresolved_rows(rows) -> list:
    return pending_rows(rows) + [
        f"row {r.get('row')} ({r.get('proof')}) {r.get('state')}: {_row_write(r)} ({_row_id(r)}) may be left on the "
        "account; check it, then clear the row by hand"
        for r in rows if r.get("state") in ("FAILED", NOT_REVERSIBLE_REFUSED)]


def check_undo_log(wire, rows) -> list:
    out = []
    for r in rows:
        state, n, proof = r.get("state"), r.get("row"), r.get("proof")
        if state in ("undone", NOT_REVERSIBLE):
            continue
        if state == "pending":
            out += pending_rows([r])
        elif state == "FAILED":
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
