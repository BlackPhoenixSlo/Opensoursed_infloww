from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import rollout_core as core
import rollout_decide as rd
from rollout_core import EXIT_DONE, EXIT_PAUSED, EXIT_REFUSED, VAULT, Ctx, Refused, Resp, say

SCRIPTS = "/admin/saved-replies"
FILL = f"{SCRIPTS}/fill"
ITEMS_PAGE = 1000
RANK = {"reconcile": 0, "read_back": 1, "apply": 2}


def call_retry(ctx: Ctx, method: str, path: str, query: dict | None = None, body: Any = None) -> Resp:
    r = Resp(0, None)
    for n in range(rd.RETRY_BUDGET):
        if n:
            time.sleep(core.POLL_S)
        r = ctx.relay.call(method, path, query, body)
        if r.ok or rd.retry_class(r.status) != "retry":
            return r
    return r


def scripts_rows(ctx: Ctx, cid: str) -> list[dict] | None:
    r = call_retry(ctx, "GET", SCRIPTS, {"account_id": cid})
    if not r.ok:
        return None
    return [x for x in (rd.row_of(v) for v in r.json.get("list") or [] if isinstance(v, dict)) if x is not None]


def live_ids(ctx: Ctx, cid: str) -> set[int] | None:
    out: set[int] = set()
    off = 0
    while True:
        r = call_retry(ctx, "GET", f"{VAULT}/items",
                       {"account_id": cid, "limit": ITEMS_PAGE, "offset": off, "sort": "oldest"})
        if not r.ok:
            return None
        page = r.json.get("list") or []
        out.update(rd.ids(page))
        if not r.json.get("hasMore") or not page:
            return out
        off += len(page)


def seq_rows(rows: list[dict], seq: str) -> list[dict]:
    return [r for r in rows if r.get("script_id") == seq]


class Fill:

    def __init__(self, ctx: Ctx) -> None:
        self.ctx, self.relay, self.j = ctx, ctx.relay, ctx.journal
        self.want_seq = set(ctx.args.sequence or [])
        self.backup = ctx.args.backup
        self._live: dict[str, set[int] | None] = {}

    def wanted(self, seq: str) -> bool:
        return not self.want_seq or seq in self.want_seq

    def live(self, cid: str) -> set[int] | None:
        if cid not in self._live:
            self._live[cid] = live_ids(self.ctx, cid)
        return self._live[cid]

    def pause(self) -> str | None:
        return rd.pause_reason({"livez": self.relay.livez(), "errors_in_a_row": self.relay.errors_in_a_row})

    def halt(self, new_creator: bool) -> str | None:
        why = self.pause() if new_creator else None
        return why or ("errors" if self.relay.errors_in_a_row >= rd.ERRORS_IN_A_ROW else None)

    def paused(self, reason: str, creator: str | None = None, **fields: Any) -> int:
        self.j.write("pause", creator, reason=reason, **fields)
        say(f"paused: {reason}" + (f" ({creator} {fields.get('sequence')})" if creator else ""))
        return EXIT_PAUSED

    def plan(self, cid: str, seq: str, rows: list[dict], live: set[int], source: str = "plan"
             ) -> tuple[dict | None, list[str]]:
        r = call_retry(self.ctx, "POST", f"{FILL}/plan", {"account_id": cid}, {"sequence": seq})
        if not r.ok:
            gate = [f"unreadable_{r.status}"]
            self.j.write("plan", cid, sequence=seq, status=None, gate=gate, flags=[], error=r.error() or None,
                         source=source)
            say(f"plan {cid} {seq}: unreadable (HTTP {r.status} {r.error()})")
            return None, gate
        plan = r.json
        return plan, self.journal_plan(cid, seq, plan, rows, live, source)

    def journal_plan(self, cid: str, seq: str, plan: dict, rows: list[dict], live: set[int], source: str
                     ) -> list[str]:
        gate = rd.apply_gate(plan, live)
        flags = rd.plan_flags(plan)
        self.j.write("plan", cid, sequence=seq, status=plan.get("status"), gate=gate, flags=flags,
                     fingerprint=plan.get("fingerprint"), plan=plan, before=seq_rows(rows, seq), source=source,
                     writes=len(rd.write_set(plan, seq_rows(rows, seq))))
        say(f"plan {cid} {seq}: {plan.get('status')} gate {', '.join(gate) or 'pass'}"
            f"{' flags ' + ', '.join(flags) if flags else ''}")
        return gate

    def journal_undo(self, cid: str, seq: str, op: str, undo: list[dict], **fields: Any) -> None:
        try:
            self.j.write("apply", cid, sequence=seq, op=op, undo=undo, **fields)
        except Exception:
            print("UNDO LIST " + json.dumps({"creator": cid, "sequence": seq, "op": op, "undo": undo},
                                            sort_keys=True), file=sys.stderr, flush=True)
            raise

    def refuse(self, cid: str, seq: str, plan: dict, before: list[dict]) -> str | None:
        if not plan.get("fingerprint"):
            say(f"apply {cid} {seq}: the plan has no fingerprint; not sent")
            return "no_fingerprint"
        skip = backup_skip(self.backup, cid, plan, before)
        if skip:
            say(f"apply {cid} {seq}: the backup does not hold the rows to write ({skip}); not sent")
        return skip

    def apply_one(self, cid: str, seq: str, plan: dict, before: list[dict]) -> str:
        if rd.is_reserved(seq):
            return "status:reserved"
        for attempt in (1, 2):
            refused = self.refuse(cid, seq, plan, before)
            if refused:
                return refused
            op = uuid.uuid4().hex
            ws = rd.write_set(plan, before)
            self.j.write("apply_intent", cid, sequence=seq, op=op, fingerprint=plan.get("fingerprint"), plan=plan,
                         before=before, write_set=[int(o["id"]) for o in ws])
            r = self.relay.call("POST", f"{FILL}/apply", {"account_id": cid},
                                {"sequence": seq, "fingerprint": plan["fingerprint"]})
            if r.ok:
                undo = list(r.json.get("undo") or [])
                status = r.json.get("status")
                self.journal_undo(cid, seq, op, undo, status=status,
                                  applied=[o.get("id") for o in r.json.get("applied") or [] if isinstance(o, dict)])
                if status != "ok":
                    say(f"apply {cid} {seq}: {status}, nothing written")
                    return str(status)
                say(f"apply {cid} {seq}: {len(undo)} Option(s) written")
                return self.read_back(cid, seq, op, plan, before, undo)
            if r.status == 409 and r.error() == "stale":
                detail = r.json.get("detail") if isinstance(r.json, dict) else None
                fresh = (detail or {}).get("plan") if isinstance(detail, dict) else None
                fresh = fresh if isinstance(fresh, dict) else {}
                self.j.write("stale", cid, sequence=seq, op=op, final=attempt == 2, status=fresh.get("status"))
                if attempt == 2:
                    say(f"apply {cid} {seq}: stale twice, skipped")
                    return "stale"
                rows, live = scripts_rows(self.ctx, cid), self.live(cid)
                if rows is None or live is None or not fresh:
                    say(f"apply {cid} {seq}: stale, and the re-plan inputs are unreadable; skipped")
                    return "stale"
                gate = self.journal_plan(cid, seq, fresh, rows, live, "stale")
                if gate:
                    return gate[0]
                plan, before = fresh, seq_rows(rows, seq)
                continue
            if rd.retry_class(r.status) == "retry":
                say(f"apply {cid} {seq}: HTTP {r.status}, reading back")
                return self.reconcile(cid, seq, op, plan, before, in_run=True)
            self.j.write("apply", cid, sequence=seq, op=op, status=f"http_{r.status}", error=r.error() or None,
                         undo=[])
            say(f"apply {cid} {seq}: refused HTTP {r.status} {r.error()}")
            return f"http_{r.status}"
        return "stale"

    def read_back(self, cid: str, seq: str, op: str, plan: dict, before: list[dict], undo: list[dict],
                  rows: list[dict] | None = None) -> str:
        rows = rows if rows is not None else scripts_rows(self.ctx, cid)
        if rows is None:
            say(f"readback {cid} {seq}: Scripts list unreadable; unverified, the next apply run reads it back")
            return "unverified"
        reasons = rd.readback(plan, before, undo, rows)
        self.j.write("readback", cid, sequence=seq, op=op, ok=not reasons, reasons=reasons)
        if reasons:
            say(f"READ-BACK MISMATCH {cid} {seq}: {', '.join(reasons)}")
            return "readback_mismatch"
        return "filled"

    def reconcile(self, cid: str, seq: str, op: str, plan: dict, before: list[dict], in_run: bool) -> str:
        rows = scripts_rows(self.ctx, cid)
        if rows is None:
            say(f"reconcile {cid} {seq}: Scripts list unreadable; left in flight for the next run")
            return "in_flight"
        undo, uncertain = rd.reconstruct_undo(plan, before, rows)
        if uncertain:
            self.j.write("apply", cid, sequence=seq, op=op, status="uncertain", uncertain=True, undo=[])
            say(f"UNCERTAIN {cid} {seq}: rows differ from the plan; never undone automatically")
            return "uncertain"
        if undo is None:
            if in_run:
                say(f"apply {cid} {seq}: not landed; the next run re-plans it")
                return "in_flight"
            self.j.write("apply", cid, sequence=seq, op=op, status="not_landed", undo=[])
            live = self.live(cid)
            if live is None:
                say(f"apply {cid} {seq}: not landed; vault unreadable, re-plan next run")
                return "not_landed"
            fresh, gate = self.plan(cid, seq, rows, live, "reconcile")
            if fresh is None or gate:
                return gate[0] if gate else "not_landed"
            return self.apply_one(cid, seq, fresh, seq_rows(rows, seq))
        self.journal_undo(cid, seq, op, undo, status="ok", reconstructed=True, applied=[e["id"] for e in undo])
        say(f"apply {cid} {seq}: landed before the crash; Undo list rebuilt ({len(undo)} Option(s))")
        return self.read_back(cid, seq, op, plan, before, undo, rows)


def mode_plan(ctx: Ctx) -> int:
    f = Fill(ctx)
    for a in ctx.scoped:
        cid = str(a.get("id"))
        why = f.pause()
        if why:
            return f.paused(why)
        rows, live = scripts_rows(ctx, cid), None
        if rows is not None:
            live = f.live(cid)
        if rows is None or live is None:
            say(f"plan {cid}: {'Scripts list' if rows is None else 'vault'} unreadable (HTTP "
                f"{ctx.relay.last_status})")
            if ctx.relay.errors_in_a_row >= rd.ERRORS_IN_A_ROW:
                return f.paused("errors")
            continue
        seqs = sorted({str(r["script_id"]) for r in rows if r.get("script_id")})
        for seq in [s for s in seqs if f.wanted(s)]:
            f.plan(cid, seq, rows, live)
            if ctx.relay.errors_in_a_row >= rd.ERRORS_IN_A_ROW:
                return f.paused("errors")
    return EXIT_DONE


def check_backup(path: str | None, ts: float) -> tuple[bool, str | None, dict]:
    if not path:
        return False, "no --backup", {}
    p = Path(path).expanduser().resolve()
    info: dict[str, Any] = {"path": str(p)}
    if not p.is_file():
        return False, "missing", info
    st = p.stat()
    info["size"] = st.st_size
    if ts - st.st_mtime > rd.BACKUP_MAX_AGE_S:
        return False, "older_than_6h", info
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    info["sha256"] = h.hexdigest()
    try:
        con = _open_ro(p)
    except sqlite3.Error as e:
        return False, f"unopenable:{type(e).__name__}", info
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()
        if not ok or ok[0] != "ok":
            return False, "integrity_check", info
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not set(rd.BACKUP_TABLES) <= tables:
            return False, "tables_missing", info
    except sqlite3.DatabaseError as e:
        return False, f"unreadable:{type(e).__name__}", info
    finally:
        con.close()
    return True, None, info


def backup_rows(path: str | None, expected: list[dict]) -> str | None:
    if not expected:
        return None
    if not path:
        return "no --backup"
    try:
        con = _open_ro(Path(path))
    except sqlite3.Error as e:
        return f"unopenable:{type(e).__name__}"
    try:
        return _rows_mismatch(con, expected)
    except sqlite3.DatabaseError as e:
        return f"unreadable:{type(e).__name__}"
    finally:
        con.close()


def backup_skip(path: str | None, cid: str, plan: dict, before: list[dict]) -> str | None:
    why = backup_rows(path, _expected_rows(cid, plan, before))
    return f"backup:{why.split(':')[0]}" if why else None


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.expanduser().resolve().as_uri()}?mode=ro", uri=True)


def _rows_mismatch(con: sqlite3.Connection, expected: list[dict]) -> str | None:
    want = sorted({int(x["row"]["id"]) for x in expected})
    got: dict[int, dict] = {}
    for at in range(0, len(want), 500):
        part = want[at:at + 500]
        for rid, acct, media, previews, price in con.execute(
                "SELECT id, account_id, media_json, previews_json, price_cents FROM saved_replies "
                f"WHERE id IN ({','.join('?' * len(part))})", part):
            got[int(rid)] = {"account_id": acct, "media": rd.ids(_json_list(media)),
                             "previews": rd.ids(_json_list(previews)), "price_cents": int(price or 0)}
    return rd.backup_mismatch(expected, got)


def _json_list(raw: Any) -> list:
    try:
        v = json.loads(raw) if raw else []
    except ValueError:
        return []
    return v if isinstance(v, list) else []


def _expected_rows(cid: str, plan: dict, before: list[dict]) -> list[dict]:
    by = {int(r["id"]): r for r in before}
    return [{"creator": cid, "row": by.get(int(o["id"]), {"id": int(o["id"])})}
            for o in rd.write_set(plan, before)]


def mode_apply(ctx: Ctx) -> int:
    f = Fill(ctx)
    st = rd.resume(ctx.journal.read(), now=core.now())
    order = [str(a.get("id")) for a in ctx.scoped]
    scope, eligible = set(order), {str(a.get("id")) for a in ctx.all_ok}
    work: dict[str, list[tuple[str, dict]]] = {}
    for (c, s), e in sorted(st["fills"].items()):
        if not f.wanted(s):
            continue
        act = rd.next_action(e)
        if c not in scope:
            if act == "reconcile" and c not in eligible:
                for op in filter(rd.orphan, e["ops"]):
                    say(f"orphan {c} {s} op {op['op']}: an apply_intent whose Creator is not Eligible now; "
                        "not reconciled")
            continue
        if act == "none":
            say(f"apply {c} {s}: not sent ({rd.fill_outcome(e)})")
            continue
        work.setdefault(c, []).append((act, e))
    if not ctx.live:
        for c in order:
            for act, e in sorted(work.get(c, []), key=lambda x: (RANK[x[0]], x[1]["sequence"])):
                what = {"reconcile": "would reconcile a lost apply response", "read_back": "would read back",
                        "apply": f"would write {e['plan'].get('writes')} Option(s)"}[act]
                skip = (backup_skip(ctx.args.backup, c, e["plan"]["plan"], e["plan"]["before"])
                        if act == "apply" and ctx.args.backup else None)
                if skip:
                    what = f"would skip ({skip})"
                say(f"apply {c} {e['sequence']}: {what} [dry run]")
        if ctx.args.backup:
            ok, why, _info = check_backup(ctx.args.backup, core.now())
            say(f"backup: {'ok' if ok else 'refused: ' + str(why)}")
            if not ok:
                return EXIT_REFUSED
        return EXIT_DONE
    ok, why, info = check_backup(ctx.args.backup, core.now())
    ctx.journal.write("backup", None, ok=ok, reason=why, **info)
    if not ok:
        raise Refused(f"backup: {why} (live apply needs a --backup file under 6 h old that passes integrity_check "
                      "and has the saved_replies and vault_items tables)")
    say(f"backup ok: {info.get('path')} {info.get('size')} bytes sha256 {info.get('sha256')}")
    ends: dict[str, int] = {}
    for cid in order:
        items = sorted(work.get(cid, []), key=lambda x: (RANK[x[0]], x[1]["sequence"]))
        if not items:
            continue
        for i, (act, e) in enumerate(items):
            why = f.halt(new_creator=i == 0)
            if why:
                return f.paused(why)
            seq, got = e["sequence"], []
            if act == "reconcile":
                for op in filter(rd.orphan, e["ops"]):
                    it = op["intent"]
                    got.append(f.reconcile(cid, seq, op["op"], it.get("plan") or {}, it.get("before") or [], False))
            elif act == "read_back":
                for op in filter(rd.unread, e["ops"]):
                    it = op["intent"]
                    got.append(f.read_back(cid, seq, op["op"], it.get("plan") or {}, it.get("before") or [],
                                           op["apply"].get("undo") or []))
            else:
                got.append(f.apply_one(cid, seq, e["plan"]["plan"], e["plan"]["before"]))
            for end in got:
                ends[end] = ends.get(end, 0) + 1
            if "readback_mismatch" in got:
                return f.paused("readback_mismatch", cid, sequence=seq)
            if "unverified" in got:
                return f.paused("unverified", cid, sequence=seq)
    say("apply: " + (", ".join(f"{k} {v}" for k, v in sorted(ends.items())) or "nothing to apply"))
    if ends.get("in_flight"):
        return f.paused("in_flight", count=ends["in_flight"])
    return EXIT_DONE


def mode_undo(ctx: Ctx) -> int:
    f = Fill(ctx)
    st = rd.resume(ctx.journal.read(), now=core.now())
    want_c = set(ctx.args.creator or [])
    ops = [op for op in reversed(st["applies"]) if rd.filled(op) and op["undo"] is None
           and (not want_c or op["creator"] in want_c) and f.wanted(op["sequence"])]
    if not ops:
        say("undo: nothing to undo")
        return EXIT_DONE
    last, unsettled = None, 0
    for op in ops:
        cid, seq, entries = op["creator"], op["sequence"], op["apply"]["undo"]
        if not ctx.live:
            say(f"undo {cid} {seq}: would undo {len(entries)} Option(s) [dry run]")
            continue
        why = f.halt(new_creator=cid != last)
        if why:
            return f.paused(why)
        last = cid
        r = ctx.relay.call("POST", f"{FILL}/undo", {"account_id": cid}, {"sequence": seq, "undo": entries})
        if r.ok:
            undone, kept = list(r.json.get("undone") or []), list(r.json.get("kept") or [])
            ctx.journal.write("undo", cid, sequence=seq, op=op["op"], undone=undone, kept=kept, left=kept)
            say(f"undo {cid} {seq}: {len(undone)} undone, {len(kept)} left")
            for k in kept:
                say(f"  left {cid} {seq} row {k.get('id')}: {k.get('reason')}")
        elif r.status == 404 and r.error() == "sequence_not_found":
            ctx.journal.write("undo", cid, sequence=seq, op=op["op"], undone=[], kept=[], left=[],
                              status="http_404", error=r.error() or None)
            say(f"undo {cid} {seq}: Sequence not found, nothing undone")
        elif rd.retry_class(r.status) == "retry":
            rows = scripts_rows(ctx, cid)
            by = {int(x["id"]): x for x in rows or []}
            if rows is not None and all(not (by.get(int(e["id"])) or {}).get("media") for e in entries):
                ctx.journal.write("undo", cid, sequence=seq, op=op["op"], undone=[int(e["id"]) for e in entries],
                                  kept=[], left=[], reconciled=True)
                say(f"undo {cid} {seq}: HTTP {r.status}, read back: undone")
            else:
                unsettled += 1
                say(f"undo {cid} {seq}: HTTP {r.status}; the next undo run sends it again")
        else:
            unsettled += 1
            say(f"undo {cid} {seq}: refused HTTP {r.status} {r.error()}; the next undo run sends it again")
    if unsettled:
        return f.paused("undo_unsettled", count=unsettled)
    return EXIT_DONE



def write_sample(ctx: Ctx, entries: list[dict], n: int, seed: int) -> Path:
    by = {(e["creator"], e["sequence"]): e for e in entries if rd.fill_outcome(e) == "filled"}
    picks = rd.sample(by, n, seed)
    parts = ["<!doctype html><meta charset=utf-8><title>Script fill contact sheet</title>",
             "<style>body{font:14px sans-serif}img{width:120px;height:120px;object-fit:cover;margin:2px}"
             "section{margin:1em 0;border-top:1px solid #ccc}</style>",
             f"<h1>Script fill contact sheet</h1><p>{len(picks)} of {len(by)} filled Sequences, seed {seed}, "
             f"{html.escape(core.iso())}</p>"]
    for key in picks:
        e = by[key]
        op = next(op for op in reversed(e["ops"]) if rd.filled(op) and op["undo"] is None)
        plan = (op["intent"] or {}).get("plan") or {}
        written = {int(u["id"]): u for u in op["apply"].get("undo") or []}
        parts.append(f"<section><h2>{html.escape(key[0])} · {html.escape(key[1])}</h2>")
        for o in plan.get("options") or []:
            media = rd.ids(o.get("media"))
            if not media:
                continue
            price = int((written.get(int(o["id"])) or o).get("price_cents") or 0)
            tag = "written" if int(o["id"]) in written else "kept"
            parts.append(f"<p>Step {o.get('step')}.{o.get('option', 1)} {html.escape(str(o.get('role')))} "
                         f"${price / 100:.2f} ({tag}, previews {rd.ids(o.get('previews'))})<br>")
            for m in media:
                r = ctx.relay.get_bytes(f"{VAULT}/thumb", {"account_id": key[0], "media_id": m})
                if r.status == 200 and r.body:
                    ctype = (r.headers.get("Content-Type") if r.headers is not None else None) or "image/jpeg"
                    parts.append(f"<img alt='{m}' src='data:{html.escape(ctype)};base64,"
                                 f"{base64.b64encode(r.body).decode()}'>")
                else:
                    parts.append(f"<span>[{m}: thumb HTTP {r.status}]</span> ")
            parts.append("</p>")
        parts.append("</section>")
    path = ctx.journal.path.parent / "sample.html"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(parts))
    os.chmod(path, 0o600)
    return path
