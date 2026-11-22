"""Rollout driver, fill side (Phase 3b): Seam 1 tables (Apply gate, read-back, Undo reconstruction, apply-side
resume, next action) and `rollout.py plan | apply | undo` against the fake relay of fake_relay.py.

Run: venv/bin/python -m pytest scripts/script-fill-rollout -q
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import pytest

import rollout_core as core
import rollout_decide as rd
from fake_relay import Cr, Fake, journal, kinds, run, srow


HEAD = [{"t": "x", "mode": "describe", "kind": "run_start", "creator": None, "ceiling_mc": 40000, "eligible": 2},
        {"t": "x", "mode": "describe", "kind": "roster", "creator": None, "eligible": ["a", "b"]}]


# ── Seam 1, 3b: Apply gate, read-back, Undo reconstruction, apply-side resume ─

CHAT, FREE, PAID = rd.CHAT, rd.FREE, rd.PAID


def opt(oid, step, role, price=0, media=(), previews=(), keep=False, flags=()):
    return {"id": oid, "step": step, "option": 1, "role": role, "keep": keep, "media": list(media),
            "previews": list(previews), "price_cents": price, "price_fixed": False, "flags": list(flags)}


LIVE = {1, 2, 3, 4, 5, 6}
# chat Steps between the paid ones: the rule climbs along paid Steps only
GOOD = [opt(1, 1, CHAT), opt(2, 2, PAID, 1000, [1, 2], [1]), opt(3, 3, CHAT), opt(4, 4, PAID, 2000, [3])]


def gplan(options, status="ok", flags=()):
    return {"status": status, "options": options, "flags": list(flags), "fingerprint": "f"}


@pytest.mark.parametrize("name,plan,want", [
    ("passes", gplan(GOOD), []),
    ("no fingerprint", {**gplan(GOOD), "fingerprint": None}, ["no_fingerprint"]),
    ("empty fingerprint", {**gplan(GOOD), "fingerprint": ""}, ["no_fingerprint"]),
    ("fingerprint key missing", {k: v for k, v in gplan(GOOD).items() if k != "fingerprint"}, ["no_fingerprint"]),
    ("refusal without fingerprint is its one reason", {**gplan(GOOD, "no_fit"), "fingerprint": None},
     ["status:no_fit"]),
    ("status", gplan(GOOD, "price_conflict"), ["status:price_conflict"]),
    ("reserved", gplan(GOOD, "reserved"), ["status:reserved"]),
    ("media gone", gplan([*GOOD[:3], opt(4, 4, PAID, 2000, [9])]), ["media_not_live"]),
    ("preview gone and not media", gplan([opt(2, 2, PAID, 1000, [1], [9])]), ["media_not_live", "preview_not_media"]),
    ("kept removed media never blocks", gplan([*GOOD, opt(5, 5, PAID, 2000, [99], keep=True,
                                                          flags=["kept_existing", "removed_media"])]), []),
    ("step order", gplan([GOOD[0], GOOD[3], GOOD[1]]), ["step_order"]),
    ("status refusal is its one reason", gplan([opt(2, 2, PAID, 0)], "no_fit"), ["status:no_fit"]),
    ("preview on a free Option", gplan([opt(1, 1, FREE, 0, [5], [5]), *GOOD[1:]]), ["preview_not_media"]),
    ("preview not among media", gplan([opt(2, 2, PAID, 1000, [1], [2])]), ["preview_not_media"]),
    ("free Option at 0", gplan([opt(1, 1, FREE, 0, [5]), *GOOD[1:]]), []),
    ("free_unfilled not blocking", gplan([*GOOD, opt(5, 5, FREE, flags=["free_unfilled"])]), []),
    ("no_video / ask_unmet not blocking", gplan([*GOOD, opt(5, 5, PAID, 2000, [5], flags=["no_video", "ask_unmet"])]),
     []),
    ("non-blocking flags", gplan([*GOOD, opt(5, 5, PAID, 0, [6], keep=True, flags=["kept_existing", "kept_unpriced"])],
                                 flags=["gap"]), []),
    ("$2.99", gplan([opt(2, 2, PAID, 299, [1])]), ["price_unsendable"]),
    ("$3", gplan([opt(2, 2, PAID, 300, [1])]), []),
    ("$200", gplan([opt(2, 2, PAID, 20000, [1])]), []),
    ("$200.01", gplan([opt(2, 2, PAID, 20001, [1])]), ["price_unsendable"]),
    ("written paid at 0", gplan([opt(2, 2, PAID, 0, [1])]), ["price_unsendable"]),
    ("escalation down", gplan([GOOD[0], opt(2, 2, PAID, 2500, [1]), GOOD[2], GOOD[3]]), ["escalation"]),
    ("tie allowed", gplan([opt(2, 2, PAID, 1000, [1]), opt(4, 4, PAID, 1000, [3])]), []),
    ("branch Steps: highest of one above lowest of next",
     gplan([opt(2, 2, PAID, 1000, [1]), opt(3, 2, PAID, 1800, [2]), opt(4, 4, PAID, 1500, [3]),
            opt(5, 4, PAID, 2500, [4])]), ["escalation"]),
    ("branch Steps held on every path",
     gplan([opt(2, 2, PAID, 1000, [1]), opt(3, 2, PAID, 1500, [2]), opt(4, 4, PAID, 1500, [3]),
            opt(5, 4, PAID, 2500, [4])]), []),
])
def test_apply_gate(name, plan, want):
    assert rd.apply_gate(plan, LIVE) == want, name


# A Fill-set price (Option 2, before price 0) and a Fixed price (Option 4, before $20), both written.
RB_PLAN = gplan([opt(1, 1, CHAT), opt(2, 2, PAID, 1000, [1, 2], [1]), opt(4, 4, PAID, 2000, [3]),
                 opt(5, 5, FREE, flags=["free_unfilled"])])
RB_BEFORE = [{"id": 1, "media": [], "previews": [], "price_cents": 0},
             {"id": 2, "media": [], "previews": [], "price_cents": 0},
             {"id": 4, "media": [], "previews": [], "price_cents": 2000},
             {"id": 5, "media": [], "previews": [], "price_cents": 0}]
RB_NOW = [{"id": 1, "media": [], "previews": [], "price_cents": 0, "removed_media_ids": []},
          {"id": 2, "media": [1, 2], "previews": [1], "price_cents": 1000, "removed_media_ids": []},
          {"id": 4, "media": [3], "previews": [], "price_cents": 2000, "removed_media_ids": []},
          {"id": 5, "media": [], "previews": [], "price_cents": 0, "removed_media_ids": []}]
RB_UNDO = [{"id": 2, "media_ids": [1, 2], "previews": [1], "price_cents": 1000, "price_set": True},
           {"id": 4, "media_ids": [3], "previews": [], "price_cents": 2000, "price_set": False}]


def _now(**by_id):
    return [{**r, **by_id.get(f"r{r['id']}", {})} for r in RB_NOW]


@pytest.mark.parametrize("name,undo,now,want", [
    ("Fill-set and Fixed prices match", RB_UNDO, RB_NOW, []),
    ("Fixed price with price_set false is ok", [RB_UNDO[1]] + [RB_UNDO[0]], RB_NOW, []),
    ("wrong price_set on the Fixed price", [RB_UNDO[0], {**RB_UNDO[1], "price_set": True}], RB_NOW, ["values"]),
    ("wrong price_set on the Fill-set price", [{**RB_UNDO[0], "price_set": False}, RB_UNDO[1]], RB_NOW, ["values"]),
    ("short Undo list", RB_UNDO[:1], RB_NOW, ["undo_short"]),
    ("media differ from the plan", RB_UNDO, _now(r2={"media": [1, 6]}), ["values"]),
    ("previews differ from the plan", RB_UNDO, _now(r2={"previews": []}), ["values"]),
    ("price differs from the plan and the entry", RB_UNDO, _now(r4={"price_cents": 2500}), ["values"]),
    ("removed media", RB_UNDO, _now(r4={"removed_media_ids": [3]}), ["removed_media"]),
])
def test_readback(name, undo, now, want):
    assert rd.readback(RB_PLAN, RB_BEFORE, undo, now) == want, name


def test_write_set_skips_kept_and_free_unfilled():
    plan = gplan([*RB_PLAN["options"], opt(6, 6, PAID, 3000, [4], keep=True)])
    before = RB_BEFORE + [{"id": 6, "media": [4], "previews": [], "price_cents": 3000}]
    assert [o["id"] for o in rd.write_set(plan, before)] == [2, 4]


def test_reconstruct_undo_landed_not_landed_uncertain():
    undo, uncertain = rd.reconstruct_undo(RB_PLAN, RB_BEFORE, RB_NOW)
    assert (undo, uncertain) == (RB_UNDO, False)          # Phase 1 UndoEntry shape, Fill-set and Fixed prices
    assert all(set(e) == {"id", "media_ids", "previews", "price_cents", "price_set"} for e in undo)
    assert rd.reconstruct_undo(RB_PLAN, RB_BEFORE, RB_BEFORE) == (None, False)     # never landed
    assert rd.reconstruct_undo(RB_PLAN, RB_BEFORE, _now(r2={"media": [1, 6]})) == (None, True)
    partly = _now(r4={"media": [], "previews": []})       # one landed, one empty: not one transaction's end
    assert rd.reconstruct_undo(RB_PLAN, RB_BEFORE, partly) == (None, True)


def test_backup_mismatch():
    exp = [{"creator": "100", "row": {"id": 2, "media": [], "previews": [], "price_cents": 0}}]
    ok = {2: {"account_id": "100", "media": [], "previews": [], "price_cents": 0}}
    assert rd.backup_mismatch(exp, ok) is None
    assert rd.backup_mismatch(exp, {}) == "row_missing:2"
    assert rd.backup_mismatch(exp, {2: {**ok[2], "account_id": "101"}}) == "row_account:2"
    assert rd.backup_mismatch(exp, {2: {**ok[2], "price_cents": 500}}) == "row_values:2"


@pytest.mark.parametrize("name,want", [("FM12", True), ("FM0", True), ("FM", False), ("FMx", False),
                                       ("FM1-intro", False), ("Shower", False), (None, False), ("FM١", False),
                                       ("fm12", False), (" FM12", False), ("FM12 ", False), ("FM 12", False),
                                       ("FM12\n", False), ("FM²", False)])
def test_is_reserved(name, want):
    assert rd.is_reserved(name) is want


def _fl(kind, creator="100", sequence="S", **kw):
    return {"t": "x", "mode": "apply", "kind": kind, "creator": creator, "sequence": sequence, **kw}


def test_resume_apply_kinds():
    plan = _fl("plan", status="ok", gate=[], plan=RB_PLAN, before=RB_BEFORE)
    j = HEAD + [plan]
    e = rd.resume(j)["fills"][("100", "S")]
    assert rd.next_action(e) == "apply" and rd.fill_outcome(e) == "not_applied"
    j += [_fl("apply_intent", op="o1", plan=RB_PLAN, before=RB_BEFORE)]
    e = rd.resume(j)["fills"][("100", "S")]
    assert [op["op"] for op in e["ops"] if rd.orphan(op)] == ["o1"]        # apply_intent without apply
    assert rd.next_action(e) == "reconcile" and rd.fill_outcome(e) == "in_flight"
    j += [_fl("apply", op="o1", status="ok", undo=RB_UNDO)]
    e = rd.resume(j)["fills"][("100", "S")]
    assert not any(map(rd.orphan, e["ops"])) and [op["op"] for op in e["ops"] if rd.unread(op)] == ["o1"]
    assert rd.next_action(e) == "read_back"                                # apply without readback
    j += [_fl("readback", op="o1", ok=True, reasons=[])]
    e = rd.resume(j)["fills"][("100", "S")]
    assert not any(map(rd.unread, e["ops"])) and rd.fill_outcome(e) == "filled" and rd.next_action(e) == "none"
    assert rd.fill_counts([e]) == {"sequences": 1, "eligible": 1, "filled": 1, "skipped": {}, "flags": {},
                                   "mismatch": 0}
    j += [_fl("undo", op="o1", undone=[2, 4], kept=[])]
    e = rd.resume(j)["fills"][("100", "S")]
    assert rd.fill_outcome(e) == "undone" and rd.next_action(e) == "none"
    j += [plan]                                                            # re-planned after the undo
    assert rd.next_action(rd.resume(j)["fills"][("100", "S")]) == "apply"
    j += [_fl("apply_intent", op="o2"), _fl("stale", op="o2", final=True)]
    st = rd.resume(j)
    assert not any(map(rd.orphan, st["fills"][("100", "S")]["ops"]))
    assert rd.fill_outcome(st["fills"][("100", "S")]) == "stale"
    assert rd.next_action(st["fills"][("100", "S")]) == "none"
    assert st["creators"] == {} and st["spent_mc"] == 0                    # 3a state untouched


P_OK = _fl("plan", status="ok", gate=[], plan=RB_PLAN, before=RB_BEFORE)
INTENT = _fl("apply_intent", op="o1", plan=RB_PLAN, before=RB_BEFORE)
FILLED = [INTENT, _fl("apply", op="o1", status="ok", undo=RB_UNDO), _fl("readback", op="o1", ok=True, reasons=[])]
OK_EMPTY = _fl("apply", op="o1", status="ok", undo=[])         # server said ok, Undo list empty
RB_BAD = _fl("readback", op="o1", ok=False, reasons=["undo_short"])
RB_CLEAN = _fl("readback", op="o1", ok=True, reasons=[])


@pytest.mark.parametrize("name,lines,want", [
    ("planned and passed", [P_OK], "apply"),
    ("gate failed", [_fl("plan", status="ok", gate=["no_fingerprint"])], "none"),
    ("unplanned", [], "none"),
    ("orphan intent", [P_OK, INTENT], "reconcile"),
    ("filled, not read back", [P_OK, *FILLED[:2]], "read_back"),
    ("filled and read back", [P_OK, *FILLED], "none"),
    ("re-planned after filled (gap / free_unfilled)", [P_OK, *FILLED, P_OK], "none"),
    ("re-planned after a read-back mismatch", [P_OK, *FILLED[:2], _fl("readback", op="o1", ok=False,
                                                                       reasons=["undo_short"]), P_OK], "none"),
    ("ok + empty undo + readback undo_short, re-planned", [P_OK, INTENT, _fl("apply", op="o1", status="ok", undo=[]),
                                                          _fl("readback", op="o1", ok=False, reasons=["undo_short"]),
                                                          P_OK], "none"),
    ("ok + empty undo, no readback line", [P_OK, INTENT, OK_EMPTY], "read_back"),
    ("ok + empty undo, no readback line, re-planned", [P_OK, INTENT, OK_EMPTY, P_OK], "read_back"),
    ("ok + empty undo + clean readback, re-planned", [P_OK, INTENT, OK_EMPTY, RB_CLEAN, P_OK], "none"),
    ("uncertain, re-planned", [P_OK, INTENT, _fl("apply", op="o1", status="uncertain", uncertain=True, undo=[]),
                               P_OK], "none"),
    ("undone, re-planned", [P_OK, *FILLED, _fl("undo", op="o1", undone=[2, 4], kept=[]), P_OK], "apply"),
    ("undone, not re-planned", [P_OK, *FILLED, _fl("undo", op="o1", undone=[2, 4], kept=[])], "none"),
    ("stale twice, re-planned", [P_OK, INTENT, _fl("stale", op="o1", final=True), P_OK], "apply"),
    ("not landed (reconciled), re-planned", [P_OK, INTENT, _fl("apply", op="o1", status="not_landed", undo=[]),
                                             P_OK], "apply"),
])
def test_next_action(name, lines, want):
    e = rd.resume(lines)["fills"].get(("100", "S")) or {"creator": "100", "sequence": "S", "plan": None,
                                                         "plan_i": -1, "ops": []}
    assert rd.next_action(e) == want, name


@pytest.mark.parametrize("name,lines,outcome,mismatch", [
    ("ok + empty undo + failed read-back", [P_OK, INTENT, OK_EMPTY, RB_BAD], "readback_mismatch", 1),
    ("ok + empty undo + failed read-back, re-planned", [P_OK, INTENT, OK_EMPTY, RB_BAD, P_OK],
     "readback_mismatch", 1),
    ("filled + failed read-back", [P_OK, *FILLED[:2], RB_BAD], "readback_mismatch", 1),
    ("filled, not read back (read-back list unreadable)", [P_OK, *FILLED[:2]], "unverified", 0),
    ("ok + empty undo + clean read-back (legit zero-write)", [P_OK, INTENT, OK_EMPTY, RB_CLEAN], "ok", 0),
    ("filled + clean read-back", [P_OK, *FILLED], "filled", 0),
])
def test_fill_outcome_and_mismatch(name, lines, outcome, mismatch):
    e = rd.resume(lines)["fills"][("100", "S")]
    assert (rd.fill_outcome(e), rd.fill_counts([e])["mismatch"]) == (outcome, mismatch), name


def test_uncertain_outcome_survives_a_re_plan():
    lines = [P_OK, INTENT, _fl("apply", op="o1", status="uncertain", uncertain=True, undo=[]), P_OK]
    assert rd.fill_outcome(rd.resume(lines)["fills"][("100", "S")]) == "uncertain"


def test_resume_reserved_plan_never_applies():
    e = rd.resume([_fl("plan", sequence="FM7", status="ok", gate=[])])["fills"][("100", "FM7")]
    assert rd.next_action(e) == "none"


def test_fill_counts_reasons_and_eligibility():
    lines = [_fl("plan", sequence="a", status="reserved", gate=["status:reserved"]),
             _fl("plan", sequence="b", status="no_paid_steps", gate=["status:no_paid_steps"]),
             _fl("plan", sequence="c", status="price_conflict", gate=["status:price_conflict"], flags=["gap"]),
             _fl("plan", sequence="d", status="ok", gate=["media_not_live"], flags=["gap", "free_unfilled"])]
    fc = rd.fill_counts(rd.resume(lines)["fills"].values())
    assert fc["eligible"] == 2 and fc["filled"] == 0
    assert fc["skipped"] == {"status:reserved": 1, "status:no_paid_steps": 1, "status:price_conflict": 1,
                             "media_not_live": 1}
    assert fc["flags"] == {"gap": 2, "free_unfilled": 1}
    assert rd.plan_flags(gplan([opt(2, 2, PAID, 1000, [1], flags=["ask_unmet", "no_video"])])) == \
        ["no_video", "ask_unmet"], "issue 16 flags reported"
    assert rd.fill_rate(3, 4) == "3/4 (75 %)" and rd.fill_rate(0, 0) == "n/a"


# ── Driver, fill side ───────────────────────────────────────────────────────

FILL_P = "/admin/saved-replies/fill"
SCRIPTS_P = "/admin/saved-replies"
A_SEQ, SHARED, CONFLICT, RES = "Shower Tease 3", "Shared Sequence", "Conflict Ladder", "FM12"


def fill_world(**kw):
    """A: complete vault, a Sequence with a Fill-set and a Fixed price and an unfilled free Option, the shared
    Sequence name, a Reserved sequence. B: a Fixed-price conflict and the shared name, from its own vault."""
    a, b = Cr("312345678", "alicefans", **kw), Cr("498765432", "bobby_b", **kw)
    a.items = {7000001, 7000002, 7000003, 7000004, 7000005}
    a.seqs = {A_SEQ: [srow(1), srow(2, PAID, fill=([7000001, 7000002], [7000001], 1500)),
                      srow(3, PAID, price=2000, fill=([7000003], [], None)), srow(4, FREE)],
              SHARED: [srow(1, FREE, fill=([7000004], [], None)), srow(2, PAID, fill=([7000005], [], 1000))],
              RES: [srow(1, PAID, fill=([7000005], [], 900))]}
    b.items = {8000001, 8000002}
    b.seqs = {CONFLICT: [srow(1, PAID, price=5000), srow(2, PAID, price=3000, fill=([8000002], [], None))],
              SHARED: [srow(1, PAID, fill=([8000001], [], 1200))]}
    b.fill_status = {CONFLICT: "price_conflict"}
    return a, b


def rows_of(fake):
    return {(c.id, n): [(r["media"], r["previews"], r["price"]) for r in rows]
            for c in fake.cr.values() for n, rows in c.seqs.items()}


def make_backup(path, fake, skip=()):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE saved_replies (id INTEGER PRIMARY KEY, account_id TEXT, script_id TEXT, "
                "media_json TEXT, previews_json TEXT, price_cents INTEGER)")
    con.execute("CREATE TABLE vault_items (account_id TEXT, media_id INTEGER)")
    for c in fake.cr.values():
        for name, rows in c.seqs.items():
            for r in rows:
                if r["id"] not in skip:
                    con.execute("INSERT INTO saved_replies VALUES (?,?,?,?,?,?)",
                                (r["id"], c.id, name, json.dumps([{"id": m} for m in r["media"]]),
                                 json.dumps(r["previews"]), r["price"]))
    con.commit()
    con.close()
    return str(path)


def fill_posts(fake, what):
    return [(aid, body["sequence"]) for p, aid, body in fake.posts if p == f"{FILL_P}/{what}"]


def planned(tmp_path):
    return {(p["creator"], p["sequence"]): p for p in kinds(tmp_path, "plan")}


@pytest.fixture
def world(serve, tmp_path):
    a, b = fill_world()
    fake = Fake([a, b])
    url = serve(fake)
    assert run(url, tmp_path, "plan") == 0
    return a, b, fake, url, make_backup(tmp_path / "backup.db", fake)


def test_plan_gates_every_sequence_and_dry_runs_post_only_fill_plan(serve, tmp_path):
    a, b = fill_world()
    fake = Fake([a, b])
    url = serve(fake)
    before = rows_of(fake)
    assert run(url, tmp_path, "plan") == 0
    p = planned(tmp_path)
    assert set(p) == {(a.id, A_SEQ), (a.id, SHARED), (a.id, RES), (b.id, CONFLICT), (b.id, SHARED)}
    assert {k: v["gate"] for k, v in p.items()} == {
        (a.id, A_SEQ): [], (a.id, SHARED): [], (a.id, RES): ["status:reserved"],
        (b.id, CONFLICT): ["status:price_conflict"], (b.id, SHARED): []}
    assert p[(a.id, A_SEQ)]["flags"] == ["free_unfilled"] and p[(a.id, A_SEQ)]["writes"] == 2
    assert [r["price_cents"] for r in p[(a.id, A_SEQ)]["before"]] == [0, 0, 2000, 0]   # current row values
    assert run(url, tmp_path, "apply") == 0 and run(url, tmp_path, "undo") == 0
    assert {x[0] for x in fake.posts} == {f"{FILL_P}/plan"}                # dry runs: no apply, no undo
    assert rows_of(fake) == before and not kinds(tmp_path, "apply_intent")


def test_live_apply_refuses_without_a_good_backup(world, tmp_path):
    a, b, fake, url, good = world
    assert run(url, tmp_path, "apply", "--live") == 2                       # no --backup
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert run(url, tmp_path, "apply", "--live", "--backup", str(empty)) == 2
    old = make_backup(tmp_path / "old.db", fake)
    os.utime(old, (time.time() - 7 * 3600,) * 2)
    assert run(url, tmp_path, "apply", "--live", "--backup", old) == 2
    assert [(x["ok"], (x["reason"] or "").split(":")[0]) for x in kinds(tmp_path, "backup")] == [
        (False, "no --backup"), (False, "tables_missing"), (False, "older_than_6h")]
    assert fill_posts(fake, "apply") == [] and not kinds(tmp_path, "apply_intent")
    # A row missing (A_SEQ) or holding other values (SHARED) skips only that Sequence; the rest is applied.
    a.seqs[SHARED][1]["price"] = 700                                        # backup no longer holds this value
    bad_rows = make_backup(tmp_path / "rows.db", fake, skip={a.seqs[A_SEQ][1]["id"]})
    a.seqs[SHARED][1]["price"] = 0
    assert run(url, tmp_path, "apply", "--live", "--backup", bad_rows) == 0
    assert fill_posts(fake, "apply") == [(b.id, SHARED)]
    assert run(url, tmp_path, "apply", "--live", "--backup", good) == 0
    assert sorted(fill_posts(fake, "apply")) == sorted([(b.id, SHARED), (a.id, A_SEQ), (a.id, SHARED)])
    ok = [x for x in kinds(tmp_path, "backup") if x["ok"]][-1]
    data = Path(good).read_bytes()
    assert (ok["path"], ok["size"], ok["sha256"]) == (str(Path(good).resolve()), len(data),
                                                     hashlib.sha256(data).hexdigest())


def test_dry_run_and_live_skip_a_sequence_the_backup_does_not_hold_alike(world, tmp_path, capsys):
    """W30 F32: dry run and live name one skip per Sequence (`backup_skip`); the start-of-run refusal names the
    file checks it ran, not the rows."""
    a, b, fake, url, good = world
    assert run(url, tmp_path, "apply", "--live") == 2
    refused = capsys.readouterr()
    assert "integrity_check" in refused.out + refused.err and "every row" not in refused.out + refused.err
    a.seqs[SHARED][1]["price"] = 700
    bad_rows = make_backup(tmp_path / "rows.db", fake, skip={a.seqs[A_SEQ][1]["id"]})
    a.seqs[SHARED][1]["price"] = 0
    assert run(url, tmp_path, "apply", "--backup", bad_rows) == 0
    dry = capsys.readouterr().out
    assert f"apply {a.id} {A_SEQ}: would skip (backup:row_missing) [dry run]" in dry, dry
    assert f"apply {a.id} {SHARED}: would skip (backup:row_values) [dry run]" in dry, dry
    assert run(url, tmp_path, "apply", "--live", "--backup", bad_rows) == 0
    live = capsys.readouterr().out
    assert f"apply {a.id} {A_SEQ}: the backup does not hold the rows to write (backup:row_missing)" in live, live
    assert f"apply {a.id} {SHARED}: the backup does not hold the rows to write (backup:row_values)" in live, live


def test_apply_reads_back_keeps_fixed_price_isolates_creators_and_never_applies_twice(world, tmp_path):
    a, b, fake, url, backup = world
    assert run(url, tmp_path, "apply", "--live", "--backup", backup) == 0
    assert fake.applies == [(a.id, SHARED), (a.id, A_SEQ), (b.id, SHARED)]
    assert not any(s in (RES, CONFLICT) for _, s in fill_posts(fake, "apply"))   # reserved / refused: never sent
    s = a.seqs[A_SEQ]
    assert (s[1]["media"], s[1]["previews"], s[1]["price"]) == ([7000001, 7000002], [7000001], 1500)
    assert (s[2]["media"], s[2]["price"]) == ([7000003], 2000)                  # A's Fixed price kept
    assert s[3]["media"] == []                                                   # free_unfilled: not written
    assert {m for r in a.seqs[SHARED] for m in r["media"]} <= a.items           # each from its own vault
    assert {m for r in b.seqs[SHARED] for m in r["media"]} == {8000001}
    applies = {(x["creator"], x["sequence"]): x for x in kinds(tmp_path, "apply")}
    for key, undo in fake.last_undo.items():
        assert applies[key]["undo"] == undo                                     # journal holds what was written
    assert [(x["ok"], x["reasons"]) for x in kinds(tmp_path, "readback")] == [(True, [])] * 3
    lines = journal(tmp_path)
    for x in kinds(tmp_path, "apply"):                                           # intent before, Undo list next
        i = lines.index(x)
        assert lines[i - 1]["kind"] == "apply_intent" and lines[i - 1]["op"] == x["op"]
        assert lines[i + 1]["kind"] == "readback" and lines[i + 1]["op"] == x["op"]
    n = len(fake.posts)
    assert run(url, tmp_path, "apply", "--live", "--backup", backup) == 0
    assert fake.applies == [(a.id, SHARED), (a.id, A_SEQ), (b.id, SHARED)] and len(fake.posts) == n


def test_canary_filters_one_creator_one_sequence(world, tmp_path):
    a, b, fake, url, backup = world
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, "--creator", b.id, "--sequence", SHARED) == 0
    assert fake.applies == [(b.id, SHARED)]


class Crash(BaseException):
    """A kill: not caught by rollout.main."""


def _crash_on_journal(monkeypatch, kind):
    orig = core.Journal.write

    def write(self, k, creator=None, **kw):
        if k == kind:
            raise Crash(k)
        return orig(self, k, creator, **kw)
    monkeypatch.setattr(core.Journal, "write", write)
    return orig


def test_lost_response_is_reconciled_by_read_back_without_a_second_apply(world, tmp_path, monkeypatch):
    a, b, fake, url, backup = world
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    orig = _crash_on_journal(monkeypatch, "apply")      # killed between apply's answer and its journal line
    with pytest.raises(Crash):
        run(url, tmp_path, "apply", "--live", "--backup", backup, *canary)
    monkeypatch.setattr(core.Journal, "write", orig)
    assert fake.applies == [(a.id, A_SEQ)] and not kinds(tmp_path, "apply")
    fills = rd.resume(journal(tmp_path))["fills"].values()
    assert len([op for e in fills for op in e["ops"] if rd.orphan(op)]) == 1
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert fake.applies == [(a.id, A_SEQ)] and len(fill_posts(fake, "apply")) == 1   # never applied twice
    (ap,) = kinds(tmp_path, "apply")
    assert ap["reconstructed"] is True and ap["undo"] == fake.last_undo[(a.id, A_SEQ)]   # Phase 1 UndoEntry
    assert [x["ok"] for x in kinds(tmp_path, "readback")] == [True]
    assert run(url, tmp_path, "undo", "--live", *canary) == 0                  # the rebuilt list undoes it
    s = a.seqs[A_SEQ]
    assert [r["media"] for r in s] == [[]] * 4 and [r["price"] for r in s] == [0, 0, 2000, 0]


def test_lost_response_with_an_unreadable_list_stays_in_flight_and_pauses(world, tmp_path, monkeypatch):
    """W30 F43: the reconcile cannot read the Scripts list, so the lost apply is still unresolved: exit 3 (pause
    `in_flight`), never a green 0; the next run with the list back settles it without a second apply."""
    a, b, fake, url, backup = world
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    orig = _crash_on_journal(monkeypatch, "apply")
    with pytest.raises(Crash):
        run(url, tmp_path, "apply", "--live", "--backup", backup, *canary)
    monkeypatch.setattr(core.Journal, "write", orig)
    fake.fail[(SCRIPTS_P, a.id)] = 401
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == core.EXIT_PAUSED
    assert kinds(tmp_path, "pause")[-1]["reason"] == "in_flight" and not kinds(tmp_path, "apply")
    del fake.fail[(SCRIPTS_P, a.id)]
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert fake.applies == [(a.id, A_SEQ)] and kinds(tmp_path, "apply")[0]["reconstructed"] is True


def test_apply_that_never_landed_is_replanned_and_applied_once(world, tmp_path, monkeypatch):
    a, b, fake, url, backup = world
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    orig = core.Relay.call

    def call(self, method, path, *args, **kw):
        if path.endswith("/fill/apply"):
            raise Crash(path)                            # killed after apply_intent, before the POST
        return orig(self, method, path, *args, **kw)
    monkeypatch.setattr(core.Relay, "call", call)
    with pytest.raises(Crash):
        run(url, tmp_path, "apply", "--live", "--backup", backup, *canary)
    monkeypatch.setattr(core.Relay, "call", orig)
    assert fake.applies == [] and len(kinds(tmp_path, "apply_intent")) == 1
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert fake.applies == [(a.id, A_SEQ)]
    assert [x["status"] for x in kinds(tmp_path, "apply")] == ["not_landed", "ok"]
    assert planned(tmp_path)[(a.id, A_SEQ)]["source"] == "reconcile"


def test_uncertain_apply_is_listed_and_never_undone(world, tmp_path, monkeypatch):
    a, b, fake, url, backup = world
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    orig = _crash_on_journal(monkeypatch, "apply")
    with pytest.raises(Crash):
        run(url, tmp_path, "apply", "--live", "--backup", backup, *canary)
    monkeypatch.setattr(core.Journal, "write", orig)
    a.seqs[A_SEQ][1]["media"] = [7000004]                # someone edited a written row meanwhile
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    (ap,) = kinds(tmp_path, "apply")
    assert (ap["status"], ap["undo"]) == ("uncertain", []) and len(fake.applies) == 1
    assert run(url, tmp_path, "undo", "--live") == 0 and fake.undos == []
    a.seqs[A_SEQ][3]["fill"] = ([7000005], [], None)     # a fresh plan for it would pass the gate again
    assert run(url, tmp_path, "plan", *canary) == 0 and planned(tmp_path)[(a.id, A_SEQ)]["gate"] == []
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert len(fill_posts(fake, "apply")) == 1                                # uncertain: never written on top
    assert rd.fill_outcome(rd.resume(journal(tmp_path))["fills"][(a.id, A_SEQ)]) == "uncertain"


def test_stale_409_replans_and_regates_once(world, tmp_path):
    a, b, fake, url, backup = world
    fake.bump_on_apply[A_SEQ] = 1
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert len(fill_posts(fake, "apply")) == 2 and fake.applies == [(a.id, A_SEQ)]
    assert [x["final"] for x in kinds(tmp_path, "stale")] == [False]
    assert planned(tmp_path)[(a.id, A_SEQ)]["source"] == "stale"


def test_second_stale_skips_and_is_not_retried(world, tmp_path):
    a, b, fake, url, backup = world
    fake.bump_on_apply[A_SEQ] = 5
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert len(fill_posts(fake, "apply")) == 2 and fake.applies == []
    assert [x["final"] for x in kinds(tmp_path, "stale")] == [False, True]
    assert rd.fill_outcome(rd.resume(journal(tmp_path))["fills"][(a.id, A_SEQ)]) == "stale"
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert len(fill_posts(fake, "apply")) == 2


def test_failed_gate_applies_nothing(serve, tmp_path):
    a, b = fill_world()
    a.items.discard(7000002)                              # a picked item gone from the vault
    a.seqs[SHARED][1]["fill"] = ([7000005], [], 150)      # a server plan with an unsendable price
    fake = Fake([a, b])
    url = serve(fake)
    assert run(url, tmp_path, "plan") == 0
    p = planned(tmp_path)
    assert p[(a.id, A_SEQ)]["gate"] == ["media_not_live"] and p[(a.id, SHARED)]["gate"] == ["price_unsendable"]
    before = rows_of(fake)
    assert run(url, tmp_path, "apply", "--live", "--backup", make_backup(tmp_path / "b.db", fake)) == 0
    assert fill_posts(fake, "apply") == [(b.id, SHARED)]
    assert {k: v for k, v in rows_of(fake).items() if k[0] == a.id} == \
        {k: v for k, v in before.items() if k[0] == a.id}


@pytest.mark.parametrize("fault", ["undo_short", "removed_media"])
def test_read_back_mismatch_journals_and_pauses_the_wave(world, tmp_path, capsys, fault):
    a, b, fake, url, backup = world
    if fault == "undo_short":
        fake.undo_short = True                            # FAULT rollout-undo-list-short
    else:
        a.items.discard(7000004)                          # gone from the vault after the plan passed the gate
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, "--creator", a.id) == 3
    assert fake.applies == [(a.id, SHARED)]               # the wave stops: the next Sequence is not sent
    assert [x["reasons"] for x in kinds(tmp_path, "readback")] == [[fault]]
    (pause,) = kinds(tmp_path, "pause")
    assert (pause["reason"], pause["sequence"]) == ("readback_mismatch", SHARED)
    assert "READ-BACK MISMATCH" in capsys.readouterr().out
    fake.undo_short = False                               # the operator fixed the server
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, "--creator", a.id) == 0
    assert fake.applies == [(a.id, SHARED), (a.id, A_SEQ)]   # a re-run goes on; the mismatched one is not re-sent


def test_unreadable_read_back_is_unverified_and_pauses(world, tmp_path):
    a, b, fake, url, backup = world
    canary = ("--creator", b.id, "--sequence", SHARED)
    fake.fail[(SCRIPTS_P, b.id)] = lambda c: 401 if fake.applies else None   # the list dies after the write
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 3
    assert fake.applies == [(b.id, SHARED)] and not kinds(tmp_path, "readback")
    (pause,) = kinds(tmp_path, "pause")
    assert (pause["reason"], pause["sequence"]) == ("unverified", SHARED)
    assert rd.fill_outcome(rd.resume(journal(tmp_path))["fills"][(b.id, SHARED)]) == "unverified"
    del fake.fail[(SCRIPTS_P, b.id)]
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0   # read back, never re-sent
    assert fake.applies == [(b.id, SHARED)] and [x["ok"] for x in kinds(tmp_path, "readback")] == [True]
    assert rd.fill_outcome(rd.resume(journal(tmp_path))["fills"][(b.id, SHARED)]) == "filled"


def test_mismatch_with_an_empty_undo_list_is_never_applied_again(world, tmp_path, capsys):
    a, b, fake, url, backup = world
    canary = ("--creator", b.id, "--sequence", SHARED)   # a one-row write set: the short Undo list is empty
    fake.undo_short = True
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 3
    (ap,) = kinds(tmp_path, "apply")
    assert (ap["status"], ap["undo"]) == ("ok", []) and fake.applies == [(b.id, SHARED)]
    assert [x["reasons"] for x in kinds(tmp_path, "readback")] == [["undo_short"]]
    fake.undo_short = False
    b.seqs[SHARED].append(srow(2, PAID, fill=([8000002], [], 1500)))   # a fresh plan passes the gate again
    assert run(url, tmp_path, "plan", *canary) == 0 and planned(tmp_path)[(b.id, SHARED)]["gate"] == []
    capsys.readouterr()
    assert run(url, tmp_path, "apply", "--live", "--backup", make_backup(tmp_path / "b2.db", fake), *canary) == 0
    assert len(fill_posts(fake, "apply")) == 1 and fake.applies == [(b.id, SHARED)]   # never re-sent
    assert f"apply {b.id} {SHARED}: not sent" in capsys.readouterr().out


def test_undo_replays_newest_first_and_reports_edited_rows(world, tmp_path):
    a, b, fake, url, backup = world
    assert run(url, tmp_path, "apply", "--live", "--backup", backup) == 0
    b.seqs[SHARED][0]["price"] = 1300                     # edited after the Fill
    filled_rows = rows_of(fake)
    assert run(url, tmp_path, "undo") == 0                # dry run: lists, sends nothing
    assert fake.undos == [] and fill_posts(fake, "undo") == [] and rows_of(fake) == filled_rows
    assert not kinds(tmp_path, "undo")
    assert run(url, tmp_path, "undo", "--live") == 0
    assert fake.undos == [(b.id, SHARED), (a.id, A_SEQ), (a.id, SHARED)]    # newest apply first
    sent = {(aid, body["sequence"]): body["undo"] for p, aid, body in fake.posts if p == f"{FILL_P}/undo"}
    assert sent[(a.id, A_SEQ)] == fake.last_undo[(a.id, A_SEQ)]            # verbatim from the journal
    s = a.seqs[A_SEQ]
    assert [r["media"] for r in s] == [[]] * 4 and [r["price"] for r in s] == [0, 0, 2000, 0]
    assert all(r["media"] == [] for r in a.seqs[SHARED])
    left = {x["sequence"]: x["left"] for x in kinds(tmp_path, "undo") if x["creator"] == b.id}
    assert left == {SHARED: [{"id": b.seqs[SHARED][0]["id"], "reason": "edited"}]}
    assert b.seqs[SHARED][0]["media"] == [8000001]
    assert run(url, tmp_path, "undo", "--live") == 0 and len(fake.undos) == 3   # already undone: skipped


def test_undo_settles_a_404_only_when_the_sequence_is_gone(world, tmp_path):
    a, b, fake, url, backup = world
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, "--creator", a.id, "--sequence", A_SEQ) == 0
    fake.fail[(f"{FILL_P}/undo", a.id)] = 404              # a bare 404 (route/proxy), not sequence_not_found
    assert run(url, tmp_path, "undo", "--live") == core.EXIT_PAUSED   # W30 F43: unsettled is never green
    assert not kinds(tmp_path, "undo")                     # unsettled: the next undo run sends it again
    assert kinds(tmp_path, "pause")[-1]["reason"] == "undo_unsettled"
    del fake.fail[(f"{FILL_P}/undo", a.id)]
    del a.seqs[A_SEQ]                                      # the Sequence is gone: sequence_not_found settles it
    assert run(url, tmp_path, "undo", "--live") == 0
    assert [(x["status"], x["error"]) for x in kinds(tmp_path, "undo")] == [("http_404", "sequence_not_found")]


def test_report_fill_columns_are_sanitised_and_contact_sheet_is_host_only(serve, tmp_path):
    a, b = fill_world(describable=600, described=600)    # both at their goal: the fill rate counts them
    fake = Fake([a, b])
    url = serve(fake)
    assert run(url, tmp_path, "plan") == 0
    assert run(url, tmp_path, "apply", "--live", "--backup", make_backup(tmp_path / "b.db", fake)) == 0
    assert run(url, tmp_path, "report", "--sample", "2", "--seed", "7") == 0
    text = (tmp_path / "report.md").read_text()
    full = (tmp_path / "rollout-report-full.md").read_text()
    for secret in (a.id, b.id, "alicefans", "bobby_b", A_SEQ, SHARED, CONFLICT, RES, "7000001", "8000001"):
        assert secret not in text
    assert re.search(r"\d{6,}", text) is None
    assert "## Sequences" not in text and "[redacted]" not in text          # counts and tallies only
    assert "Fill rate (Creators at their goal): 3/4 (75 %)" in text
    assert "status:price_conflict 1" in text and "status:reserved 1" in text and "free_unfilled 1" in text
    assert A_SEQ in full and CONFLICT in full                                # per-Sequence list: host only
    sheet = tmp_path / "sample.html"
    assert oct(sheet.stat().st_mode & 0o777) == "0o600"
    html_text = sheet.read_text()
    assert html_text.count("<section>") == 2 and "data:image/png;base64," in html_text


def test_re_plan_after_filled_never_applies_twice(world, tmp_path):
    a, b, fake, url, backup = world
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    a.seqs[A_SEQ][3]["fill"] = ([7000004], [], None)     # partly filled: a fresh plan is `ok` again (gap)
    assert run(url, tmp_path, "plan", *canary) == 0 and planned(tmp_path)[(a.id, A_SEQ)]["gate"] == []
    assert run(url, tmp_path, "apply", "--live", "--backup", make_backup(tmp_path / "b2.db", fake), *canary) == 0
    assert fake.applies == [(a.id, A_SEQ)] and len(fill_posts(fake, "apply")) == 1


def test_undo_then_re_plan_may_apply_again(world, tmp_path):
    a, b, fake, url, backup = world
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert run(url, tmp_path, "undo", "--live", *canary) == 0
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert fake.applies == [(a.id, A_SEQ)]                                   # undone, not re-planned: not sent
    assert run(url, tmp_path, "plan", *canary) == 0
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert fake.applies == [(a.id, A_SEQ)] * 2


def test_no_fingerprint_is_never_sent(world, tmp_path):
    a, b, fake, url, backup = world
    fake.fingerprint = False
    assert run(url, tmp_path, "plan") == 0
    assert planned(tmp_path)[(a.id, A_SEQ)]["gate"] == ["no_fingerprint"]
    assert run(url, tmp_path, "apply", "--live", "--backup", backup) == 0
    assert fill_posts(fake, "apply") == [] and not kinds(tmp_path, "apply_intent")


def test_journaled_plan_without_fingerprint_is_refused_before_the_post(world, tmp_path):
    a, b, fake, url, backup = world
    p = tmp_path / "j.jsonl"
    lines = [json.loads(x) for x in p.read_text().splitlines()]
    for ln in lines:                                      # a journal from a driver without the gate reason
        if ln["kind"] == "plan" and ln.get("plan"):
            ln["fingerprint"] = None
            ln["plan"].pop("fingerprint", None)
    p.write_text("".join(json.dumps(ln) + "\n" for ln in lines))
    assert run(url, tmp_path, "apply", "--live", "--backup", backup) == 0
    assert fill_posts(fake, "apply") == [] and not kinds(tmp_path, "apply_intent")


def test_fresh_plan_without_fingerprint_is_refused(world, tmp_path):
    a, b, fake, url, backup = world
    fake.fingerprint = False                              # the 409 answer's fresh plan carries none
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert len(fill_posts(fake, "apply")) == 1 and fake.applies == []
    assert planned(tmp_path)[(a.id, A_SEQ)]["gate"] == ["no_fingerprint"]


def test_fresh_plan_rows_are_checked_against_the_backup(world, tmp_path):
    a, b, fake, url, backup = world
    a.seqs[A_SEQ][1]["price"] = 1800                      # edited after the backup: the 409 plan writes this row
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    assert run(url, tmp_path, "apply", "--live", "--backup", backup, *canary) == 0
    assert len(fill_posts(fake, "apply")) == 1 and fake.applies == []
    fresh = planned(tmp_path)[(a.id, A_SEQ)]
    assert fresh["source"] == "stale" and fresh["gate"] == []
    assert len(kinds(tmp_path, "apply_intent")) == 1      # no intent for the refused fresh plan


def test_failed_apply_journal_write_prints_the_undo_list(world, tmp_path, monkeypatch, capsys):
    a, b, fake, url, backup = world
    orig = core.Journal.write

    def write(self, k, creator=None, **kw):
        if k == "apply":
            raise OSError(28, "No space left on device")
        return orig(self, k, creator, **kw)
    monkeypatch.setattr(core.Journal, "write", write)
    with pytest.raises(OSError):
        run(url, tmp_path, "apply", "--live", "--backup", backup, "--creator", a.id, "--sequence", A_SEQ)
    err = capsys.readouterr().err
    (line,) = [ln for ln in err.splitlines() if ln.startswith("UNDO LIST ")]
    got = json.loads(line[len("UNDO LIST "):])
    assert (got["creator"], got["sequence"], got["undo"]) == (a.id, A_SEQ, fake.last_undo[(a.id, A_SEQ)])


def test_undo_checks_livez_per_creator(world, tmp_path):
    a, b, fake, url, backup = world
    assert run(url, tmp_path, "apply", "--live", "--backup", backup) == 0
    fake.livez_status = 503
    assert run(url, tmp_path, "undo", "--live") == 3
    assert fake.undos == [] and kinds(tmp_path, "pause")[-1]["reason"] == "livez_down"


def test_orphan_of_a_creator_off_the_roster_is_listed(world, tmp_path, monkeypatch, capsys):
    a, b, fake, url, backup = world
    canary = ("--creator", a.id, "--sequence", A_SEQ)
    orig = _crash_on_journal(monkeypatch, "apply")
    with pytest.raises(Crash):
        run(url, tmp_path, "apply", "--live", "--backup", backup, *canary)
    monkeypatch.setattr(core.Journal, "write", orig)
    fake.accounts[0]["is_active"] = False                 # A left the roster with an intent in flight
    capsys.readouterr()
    assert run(url, tmp_path, "apply", "--live", "--backup", backup) == 0
    out = capsys.readouterr().out
    assert f"orphan {a.id} {A_SEQ}" in out and "not reconciled" in out
