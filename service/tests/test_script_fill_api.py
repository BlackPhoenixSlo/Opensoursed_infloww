#!/usr/bin/env python3
"""test_script_fill_api — the Fill routes over HTTP (`script_fill_api`, spec phase 01 › Seam 2, ticket 11).

Real owner / chatter session cookies on the shared two-Agency fixture (`_agency_fixtures`). Creator A's vault
holds the decide suite's WHITE Shoot (101..113: free-safe 101-103, $10 suggestive 104-107 + clip 108, $50
explicit 109-112 + clip 113), an exact copy of 104 (114, one dupe set), a red Shoot (131..143, same layout) and
two undescribed photos (remaining Describe work). Red clip 143, the vault's top clip, sits in OF list 7, priced $99
(a folder price).
Creator B (Agency B) has its own Shoot and a same-named, priced Sequence; Creators A2 / A3 are Agency A's
siblings for template prices. The DB is read back through a fresh sqlite3 connection, not the routes.

  case_gate_refusals               empty account_id 400; B owner and B chatter 403; folder-limited chatter 403
                                   folder_not_allowed; unknown Sequence 404; unreadable vault 503, nothing written
  case_plan_writes_nothing         plan on every Sequence leaves A's rows byte-identical
  case_apply_writes_and_reads_back plan -> apply -> DB: media (house VaultMedia, previews first), previews, price,
                                   updated_at; Fixed price untouched; B's media and prices never used; dupe set
                                   never twice; Undo list shape; applied Options
  case_reapply_already_filled      re-press / lost-response retry: already_filled, zero writes, no bump
  case_stale_fingerprint           edit between plan and fingerprinted apply -> 409 stale + fresh plan, nothing
                                   written; unfingerprinted apply after the edit applies the fresh plan
  case_concurrent_applies          two applies at once -> one ok, one already_filled
  case_non_ok_statuses_write_nothing  not_enough_content, no_fit, price_conflict, price_out_of_range, reserved,
                                   no_paid_steps: 200, byte-identical rows
  case_describe_block              owner can_describe with nothing blocking; Scripts-only chatter with Whole-vault
                                   access and remaining work: can_describe false, "no Vault Pro access"
  case_template_prices             same-Agency sibling's prices (most priced steps, then lowest id; highest
                                   price per step); never another Agency's, even for a two-Agency caller
  case_template_prices_two_owner_creator  A also linked to a second owner (pinned ids "0" and "~": each
                                   ordering of the tie-break runs): a two-Agency chatter borrows only from the
                                   Agency it acts in for A
  case_plan_runs_off_the_event_loop  `script_fill_decide.plan` runs on a worker thread for plan and apply
  case_vault_fails_closed          through fill/apply: a load row with no live vault_items row is never
                                   written (control: kept, it wins the clip ask); a planned id missing from the
                                   live rows raises inside the write transaction, rows byte-identical
  case_undo_refuses_reserved       hand-built entries on a reserved FM Sequence: every one kept `reserved`
  case_undo                        restores empty Options, keeps a Fixed price, zeroes only price_set; an edited
                                   row, altered values, a moved row, a Fixed price edit, another account's row:
                                   kept and reported per row; only untouched Options revert

Run: ./venv/bin/python service/tests/test_script_fill_api.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import sqlite3  # noqa: E402
import threading  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import _script_fill_fixtures as sf  # noqa: E402
import chatter_identity_cache  # noqa: E402
import employees  # noqa: E402
import script_fill_api  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_jev_pass  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chatter, ChatterFolderAccess, ChatterUser, User, UserAccount  # noqa: E402

IDS = fx.seed_two_agencies()
A, B = IDS["creator_a"], IDS["creator_b"]
A2, A3 = "1000011", "1000010"     # Agency A siblings (template prices); A3 sorts first
AX = "1000020"                    # a second owner's Creator (template prices, two-owner case)
FIRST, LAST = "0", "~"            # owner ids sorting before / after Agency A owner's uuid hex
SEQ = "Spicy intro"
WHITE = set(range(101, 114))
DUPE = (104, 114)
RED = set(range(131, 144))
B_IDS = set(range(501, 514))
UNDESCRIBED = (190, 191)


async def _seed() -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        for aid in (A2, A3, AX):
            s.add(Account(id=aid, nickname=f"creator_{aid}", color="#aaaaaa"))
        for uid in (FIRST, LAST):
            s.add(User(id=uid, username=f"owner_{ord(uid)}", password=fx.PASSWORD))
        s.add(Chatter(id=(fl := uuid.uuid4().hex), username="chatter_fl", password=fx.PASSWORD,
                      display_name="chatter_fl", color="#bbbbbb", created_at=now, last_seen_at=now))
    async with get_session() as s:
        for aid in (A2, A3):
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=aid))
        s.add(ChatterUser(chatter_id=fl, user_id=IDS["agency_a_owner"], created_at=now))
        s.add(ChatterFolderAccess(chatter_id=fl, account_id=A, folder_id=12, folder_name="f12", created_at=now))
    rows = sf.shoot(A, 100)
    rows.append(sf.vault_row(A, 114, "suggestive", dupe_of=104,       # exact copy of 104
                             created_at=rows[3]["created_at"]))
    rows += sf.shoot(A, 130, "red", at=sf.T0 + timedelta(days=3))
    rows[26]["of_folder_ids"] = json.dumps([7])                       # clip 143 in OF list 7
    rows += [sf.vault_row(A, m, "suggestive", describe_status=None, colour="blue") for m in UNDESCRIBED]
    rows += sf.shoot(B, 500)
    await sf.insert_vault(rows, {(A, "of:7"): 9900})
    # Agency B: same Sequence name, priced, on its own Creator.
    await sf.insert_sequence(sf.sequence_rows(B, SEQ, {**sf.S1, 3: ("1/3, ppv", "wanna see more?", 2500)}))


asyncio.run(_seed())
fx.store_blob(IDS["agency_a_owner"], "roles", {"enforce": False})
fx.store_blob(IDS["agency_b_owner"], "roles", {"enforce": False})
for _uid in (FIRST, LAST):
    fx.store_blob(_uid, "roles", {"enforce": False})
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_B = fx.login_chatter("chatter_b")
CHATTER_AB = fx.login_chatter("chatter_ab")
CHATTER_FL = fx.login_chatter("chatter_fl")


# ── Helpers ──────────────────────────────────────────────────────────

def _sql(query: str, *args) -> list[tuple]:
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        rows = con.execute(query, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def _snapshot(account: str = A) -> list[tuple]:
    """Every saved_replies row of the Creator, every column (byte-identical check)."""
    return _sql("SELECT * FROM saved_replies WHERE account_id = ? ORDER BY id", account)


def _rows(script: str = SEQ, account: str = A) -> dict[int, dict]:
    """{step: row} of a one-Option-per-Step Sequence, read back from the DB."""
    out: dict = {}
    for rid, step, price, media, previews, updated in _sql(
            "SELECT id, script_step, price_cents, media_json, previews_json, updated_at FROM saved_replies "
            "WHERE account_id = ? AND script_id = ? ORDER BY script_step, id", account, script):
        assert step not in out, ("one Option per Step here", step)
        out[step] = {"id": rid, "price": price, "media": json.loads(media), "previews": json.loads(previews),
                     "updated_at": updated}
    return out


def _new_seq(script: str, steps: dict, account: str = A, last: int = 13) -> None:
    _sql("DELETE FROM saved_replies WHERE account_id = ? AND script_id = ?", account, script)
    asyncio.run(sf.insert_sequence(sf.sequence_rows(account, script, steps, last)))


def _url(route: str, account: str | None = A) -> str:
    return f"/admin/saved-replies/fill/{route}" + ("" if account is None else f"?account_id={account}")


def _plan(c=OWNER_A, script: str = SEQ, account: str = A):
    return c.post(_url("plan", account), json={"sequence": script})


def _apply(c=OWNER_A, script: str = SEQ, account: str = A, fingerprint: str | None = None):
    body = {"sequence": script, **({"fingerprint": fingerprint} if fingerprint else {})}
    return c.post(_url("apply", account), json=body)


def _undo(entries: list[dict], c=OWNER_A, script: str = SEQ, account: str = A):
    return c.post(_url("undo", account), json={"sequence": script, "undo": entries})


def _ok(r) -> dict:
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()


def _opts(plan: dict) -> dict:
    return {o["step"] if o["option"] == 1 else (o["step"], o["option"]): o for o in plan["options"]}


def _ids(media: list) -> list[int]:
    return [m["id"] for m in media]


def _unblocked():
    """Describe key, cap and Jev all ready (the test stack has no vision key)."""
    budget, jev = vault_ai_vision._vision_budget, vault_jev_pass.plan

    async def _budget(*_a, **_k):
        return {"blocked_reason": "", "capped": False, "key_missing": False}

    async def _jev(*_a, **_k):
        return {"ready": True, "reason": ""}

    vault_ai_vision._vision_budget, vault_jev_pass.plan = _budget, _jev
    return lambda: (setattr(vault_ai_vision, "_vision_budget", budget), setattr(vault_jev_pass, "plan", jev))


# Step 5 carries a Fixed $50; the rest is S1, unpriced.
S_FIXED = {**sf.S1, 5: ("2/3", "sending you 2 pics 🙈", 5000)}


# ── Gate ─────────────────────────────────────────────────────────────

def case_gate_refusals():
    _new_seq(SEQ, S_FIXED)
    before = _snapshot()
    for route in ("plan", "apply", "undo"):
        body = {"sequence": SEQ, "undo": []}
        r = OWNER_A.post(_url(route, None), json=body)
        assert r.status_code == 400 and r.json()["detail"] == {"error": "account_id_required"}, (route, r.text)
        r = OWNER_A.post(_url(route, ""), json=body)
        assert r.status_code == 400, (route, r.text)
        for c, who in ((OWNER_B, "Agency B owner"), (CHATTER_B, "Agency B chatter")):
            r = c.post(_url(route), json=body)
            assert r.status_code == 403, (route, who, r.status_code, r.text)
        r = CHATTER_FL.post(_url(route), json=body)
        assert r.status_code == 403 and r.json()["detail"] == {"error": "folder_not_allowed"}, (route, r.text)
        r = OWNER_A.post(_url(route), json={**body, "sequence": "No such sequence"})
        assert r.status_code == 404 and r.json()["detail"] == {"error": "sequence_not_found"}, (route, r.text)
    # Unreadable vault (a bad folder-ids value fails `load_rows` closed): 503, nothing written.
    _sql("UPDATE vault_items SET of_folder_ids = 'not json' WHERE account_id = ? AND media_id = 105", A)
    try:
        for route in ("plan", "apply"):
            r = OWNER_A.post(_url(route), json={"sequence": SEQ})
            assert r.status_code == 503 and r.json()["detail"] == {"error": "inventory_unknown"}, (route, r.text)
    finally:
        _sql("UPDATE vault_items SET of_folder_ids = '[]' WHERE account_id = ? AND media_id = 105", A)
    assert _snapshot() == before, "a refused call wrote"


# ── Plan and apply ───────────────────────────────────────────────────

def case_plan_writes_nothing():
    _new_seq(SEQ, S_FIXED)
    _new_seq("Price trouble", {**sf.S1, 3: ("1/3, ppv", "", 5000), 5: ("2/3", "", 2000)})
    before = _snapshot()
    for script in (SEQ, "Price trouble"):
        p = _ok(_plan(script=script))
        assert p["status"] in ("ok", "price_conflict"), p["status"]
        assert set(p) == {"status", "options", "flags", "conflict", "describe", "fingerprint"}, sorted(p)
    assert _snapshot() == before, "fill/plan wrote"


def case_apply_writes_and_reads_back():
    _new_seq(SEQ, S_FIXED)
    before = _rows()
    p = _ok(_plan())
    assert p["status"] == "ok", p
    r = _ok(_apply(fingerprint=p["fingerprint"]))
    assert r["status"] == "ok" and r["plan"]["fingerprint"] == p["fingerprint"], r
    after = _rows()
    # Over the whole pool (issue 16): free step 1 the lowest free-safe photo; step 3 the lowest $10 photo + the
    # lowest clip, preview first, its $50 List held to step 5's Fixed $50; step 5 (the last photo Step) the top
    # photo pair of one Shoot (red 141, 142) + the next clip + preview; step 7 the top clip, red 143, priced at its
    # $99 folder price (over $50, so no ladder lift).
    assert (_ids(after[1]["media"]), after[1]["previews"], after[1]["price"]) == ([101], [], 0), after[1]
    assert (_ids(after[3]["media"]), after[3]["previews"], after[3]["price"]) == ([102, 104, 108], [102], 5000), \
        after[3]
    assert (_ids(after[5]["media"]), after[5]["previews"], after[5]["price"]) == ([131, 141, 142, 138], [131], 5000)
    assert (_ids(after[7]["media"]), after[7]["previews"], after[7]["price"]) == ([143], [], 9900), after[7]
    # House VaultMedia shape from the vault row.
    assert after[3]["media"][0] == {"id": 102, "type": "photo",
                                    "files": {"thumb": {"url": f"https://cdn.example/{A}/102_t.jpg"}}}
    assert after[7]["media"][0]["type"] == "video" and after[3]["media"][-1]["type"] == "video", "clip last"
    # Written rows bumped; chat rows untouched.
    for step in (1, 3, 5, 7):
        assert after[step]["updated_at"] != before[step]["updated_at"], step
    for step in (2, 4, 6, 8, 13):
        assert after[step] == before[step], step
    every = [m for s in after.values() for m in _ids(s["media"])]
    assert set(every) <= WHITE | RED, ("A's own vault only; never B's or the copy", every)
    assert not set(every) & B_IDS
    assert not set(DUPE) <= set(every), "one dupe set used at most once"
    # Undo list: one entry per written Option, price after apply, price_set only where Fill set it.
    undo = {u["id"]: u for u in r["undo"]}
    assert set(undo) == {after[s]["id"] for s in (1, 3, 5, 7)}, r["undo"]
    assert undo[after[3]["id"]] == {"id": after[3]["id"], "media_ids": [102, 104, 108], "previews": [102],
                                    "price_cents": 5000, "price_set": True}
    assert undo[after[5]["id"]]["price_set"] is False and undo[after[5]["id"]]["price_cents"] == 5000
    assert undo[after[1]["id"]]["price_set"] is False and undo[after[1]["id"]]["price_cents"] == 0
    assert {o["id"] for o in r["applied"]} == set(undo), r["applied"]
    assert all(o["media"] for o in r["applied"])


def case_reapply_already_filled():
    _new_seq(SEQ, S_FIXED)
    _ok(_apply())
    before = _snapshot()
    for _ in range(2):    # a re-press, then a lost-response retry
        r = _ok(_apply())
        assert r["status"] == "already_filled" and r["applied"] == [] and r["undo"] == [], r
    assert _snapshot() == before, "already_filled wrote or bumped updated_at"


def case_stale_fingerprint():
    _new_seq(SEQ, S_FIXED)
    p = _ok(_plan())
    rid = _rows()[2]["id"]
    _sql("UPDATE saved_replies SET text = 'edited after the plan' WHERE id = ?", rid)
    before = _snapshot()
    r = _apply(fingerprint=p["fingerprint"])
    assert r.status_code == 409, (r.status_code, r.text)
    detail = r.json()["detail"]
    assert detail["error"] == "stale" and detail["plan"]["status"] == "ok", detail
    assert detail["plan"]["fingerprint"] != p["fingerprint"], "fresh plan, fresh fingerprint"
    assert detail["plan"]["fingerprint"] == _ok(_plan())["fingerprint"], "the 409 carries the fresh plan"
    assert _snapshot() == before, "a stale apply wrote"
    r = _ok(_apply())
    assert r["status"] == "ok" and r["plan"]["fingerprint"] == detail["plan"]["fingerprint"], r["status"]


def case_concurrent_applies():
    _new_seq(SEQ, S_FIXED)
    clients = [fx.login_owner("agency_a_owner"), fx.login_owner("agency_a_owner")]
    load = script_fill_api._load_vault

    async def _slow(*a):
        await asyncio.sleep(0.4)     # widen the window: the other apply must wait on the write lock
        return await load(*a)

    script_fill_api._load_vault = _slow
    out: list = [None, None]
    gate = threading.Barrier(2)

    def run(i):
        gate.wait()
        out[i] = _apply(clients[i])

    try:
        threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
    finally:
        script_fill_api._load_vault = load
    statuses = sorted(_ok(r)["status"] for r in out)
    assert statuses == ["already_filled", "ok"], statuses


def case_non_ok_statuses_write_nothing():
    cases = [
        # (script, steps, status, conflict)
        ("Big ask", {s: ("ppv", "the full video", 0) for s in (1, 2, 3, 4, 5)}, "not_enough_content", None),
        ("Price trouble", {**sf.S1, 3: ("1/3, ppv", "", 5000), 5: ("2/3", "", 2000)}, "price_conflict",
         {"step": 5, "rule": "below_earlier", "price_cents": 2000}),
        ("Two dollars", {**sf.S1, 3: ("1/3, ppv", "", 200)}, "price_out_of_range",
         {"step": 3, "rule": "under_min", "price_cents": 200}),
        ("FM12", sf.S1, "reserved", None),
        ("Just chat", {1: ("1/2, bridge", "hi", 0)}, "no_paid_steps", None),
    ]
    for script, steps, _s, _c in cases:
        _new_seq(script, steps)
    before = _snapshot()
    for script, _steps, status, conflict in cases:
        for call in (_plan, _apply):
            body = _ok(call(script=script))
            plan = body if call is _plan else body["plan"]
            assert plan["status"] == status and plan["conflict"] == conflict, (script, call.__name__, plan["status"],
                                                                               plan["conflict"])
            if call is _apply:
                assert body["status"] == status and body["applied"] == [] and body["undo"] == [], body
    assert _snapshot() == before, "a non-ok status wrote"
    # The same ask with no Describe work left: no_fit, still nothing written.
    _sql(f"UPDATE vault_items SET removed_at = '2026-07-02 00:00:00' WHERE account_id = ? "
         f"AND media_id IN ({','.join(map(str, UNDESCRIBED))})", A)
    try:
        body = _ok(_apply(script="Big ask"))
        assert body["status"] == "no_fit" and body["plan"]["describe"]["remaining"] == 0, body["plan"]["describe"]
    finally:
        _sql(f"UPDATE vault_items SET removed_at = NULL WHERE account_id = ? "
             f"AND media_id IN ({','.join(map(str, UNDESCRIBED))})", A)
    assert _snapshot() == before, "no_fit wrote"


def case_describe_block():
    _new_seq(SEQ, S_FIXED)
    restore = _unblocked()
    try:
        d = _ok(_plan())["describe"]
        # 27 described (two Shoots + the copy) + 2 undescribed = 29 describable: goal 29, remaining 2.
        assert d == {"described": 27, "target": 29, "remaining": 2, "can_describe": True,
                     "blocked_reason": None}, d
        # A Scripts-only role on chatter_a (Whole-vault access: no folder limit).
        emp = asyncio.run(employees.get_or_create_mirror_employee(
            IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))
        role = {"id": "role-scripts", "name": "Scripts only", "description": "", "scope": "all",
                "permissions": {"/growth/scripts": True}}
        fx.store_blob(IDS["agency_a_owner"], "roles",
                      {"enforce": True, "roles": [role], "assignments": {str(emp): "role-scripts"}})
        try:
            p = _ok(_plan(CHATTER_A))
            assert p["describe"]["can_describe"] is False, p["describe"]
            assert p["describe"]["blocked_reason"] == "no Vault Pro access", p["describe"]
            assert p["describe"]["remaining"] == 2
            # describe-all itself would refuse this caller (the sentence's claim).
            r = CHATTER_A.post("/admin/vault-ai/describe-all", json={"account_id": A, "target": 1000})
            assert r.status_code == 403, (r.status_code, r.text)
        finally:
            fx.store_blob(IDS["agency_a_owner"], "roles", {"enforce": False})
    finally:
        restore()
    # Unpatched, the test stack's own sentence blocks (no vision key): never the Vault Pro one for an owner.
    d = _ok(_plan())["describe"]
    assert d["can_describe"] is False and d["blocked_reason"] and d["blocked_reason"] != "no Vault Pro access", d


def case_template_prices():
    plain = {**sf.S1}
    _new_seq(SEQ, plain)
    # Agency B's priced same-named Sequence never lends: List prices as without any template.
    o = _opts(_ok(_plan()))
    assert [o[s]["price_cents"] for s in (3, 5, 7)] == [5000, 7500, 9900], [o[s]["price_cents"] for s in (3, 5, 7)]
    assert not any("template_price" in o[s]["flags"] for s in (3, 5, 7))
    # Not even for a caller holding both Agencies' Creators (chatter_ab): the source must share A's Agency.
    o = _opts(_ok(_plan(CHATTER_AB)))
    assert [o[s]["price_cents"] for s in (3, 5, 7)] == [5000, 7500, 9900], [o[s]["price_cents"] for s in (3, 5, 7)]
    # A3 (lower id) prices one step; A2 three: A2 wins on priced steps. A2's step 3 has two Options: the highest.
    _new_seq(SEQ, {**sf.S1, 3: ("1/3, ppv", "", 3000)}, account=A3)
    _new_seq(SEQ, {**sf.S1, 3: ("1/3, ppv", "", 2500), 5: ("2/3", "", 4000), 7: ("3/3, ppv", "", 6000)}, account=A2)
    asyncio.run(sf.insert_sequence([{**sf.sequence_rows(A2, SEQ, {3: ("1/3, ppv", "", 1500)}, last=3)[2]}]))
    o = _opts(_ok(_plan()))
    assert {s: o[s]["price_cents"] for s in (3, 5, 7)} == {3: 2500, 5: 4000, 7: 6000}, o
    assert all("template_price" in o[s]["flags"] for s in (3, 5, 7))
    # A tie on priced steps: the lowest account id (A3).
    _new_seq(SEQ, {**sf.S1, 3: ("1/3, ppv", "", 2000), 5: ("2/3", "", 3000), 7: ("3/3, ppv", "", 4000)}, account=A3)
    o = _opts(_ok(_plan()))
    assert {s: o[s]["price_cents"] for s in (3, 5, 7)} == {3: 2000, 5: 3000, 7: 4000}, o
    # Applied, the template price is what lands.
    r = _ok(_apply())
    assert r["status"] == "ok" and _rows()[3]["price"] == 2000, r["status"]
    for acct in (A2, A3):
        _sql("DELETE FROM saved_replies WHERE account_id = ?", acct)


def _link_owner(uid: str, linked: bool) -> None:
    """Owner `uid` holds Creators A and AX and is linked to chatter_ab (`linked`), or none of it."""
    links = (("user_accounts", "user_id", uid, "account_id", A), ("user_accounts", "user_id", uid, "account_id", AX),
             ("chatter_users", "user_id", uid, "chatter_id", IDS["chatter_ab"]))
    for table, k1, v1, k2, v2 in links:
        if linked:
            extra = ", created_at" if table == "chatter_users" else ""
            _sql(f"INSERT INTO {table} ({k1}, {k2}{extra}) VALUES (?, ?{', ?' if extra else ''})",
                 v1, v2, *((datetime.utcnow().isoformat(" "),) if extra else ()))
        else:
            _sql(f"DELETE FROM {table} WHERE {k1} = ? AND {k2} = ?", v1, v2)
    chatter_identity_cache.invalidate()   # a seeded link emits no assignment_changed


def case_template_prices_two_owner_creator():
    """Creator A also held by a second owner, both linked to chatter_ab: chatter_ab borrows only from the Agency
    it acts in for A (the house tie-break, `_sorted_holder_owner_ids`: alphabetically first holder), never from a
    Creator of A's other owner. Both orderings run every time, the acting owner pinned by id: "0" sorts before
    Agency A's owner (uuid hex) and acts; "~" sorts after it, so Agency A acts."""
    _new_seq(SEQ, {**sf.S1})
    # Agency A's sibling A2 prices three steps; the second owner's Creator AX prices step 3 only.
    _new_seq(SEQ, {**sf.S1, 3: ("1/3, ppv", "", 3000), 5: ("2/3", "", 4000), 7: ("3/3, ppv", "", 6000)}, account=A2)
    _new_seq(SEQ, {**sf.S1, 3: ("1/3, ppv", "", 2500)}, account=AX)
    assert FIRST < IDS["agency_a_owner"] < LAST, "precondition: pinned ids sort around Agency A's owner"
    try:
        for other, want in ((FIRST, {3: (2500, True), 5: (5000, False), 7: (9900, False)}),   # AX lends, A2 never
                            (LAST, {3: (3000, True), 5: (4000, True), 7: (6000, True)})):     # A2 lends, AX never
            _link_owner(other, True)
            try:
                o = _opts(_ok(_plan(CHATTER_AB)))
            finally:
                _link_owner(other, False)
            got = {s: (o[s]["price_cents"], "template_price" in o[s]["flags"]) for s in (3, 5, 7)}
            assert got == want, (other, got)
    finally:
        for acct in (A2, AX):
            _sql("DELETE FROM saved_replies WHERE account_id = ?", acct)


# ── Off the event loop, fail closed ──────────────────────────────────

def case_plan_runs_off_the_event_loop():
    """plan and apply run `script_fill_decide.plan` (synchronous, the whole vault) on a worker thread, not on
    the relay's event loop."""
    _new_seq(SEQ, S_FIXED)
    seen: dict = {"plan": []}
    load, real_plan = script_fill_api._load_vault, script_fill_api.decide.plan

    async def _load(*a):
        seen["loop"] = threading.get_ident()
        return await load(*a)

    def _decide(*a, **k):
        seen["plan"].append(threading.get_ident())
        return real_plan(*a, **k)

    script_fill_api._load_vault, script_fill_api.decide.plan = _load, _decide
    try:
        assert _ok(_plan())["status"] == "ok"
        assert _ok(_apply())["status"] == "ok"
    finally:
        script_fill_api._load_vault, script_fill_api.decide.plan = load, real_plan
    assert len(seen["plan"]) == 2 and seen["loop"] not in seen["plan"], seen


def case_vault_fails_closed():
    """Through fill/apply. A `load_rows` row with no live `vault_items` row is not in Fill's vault: 777, a copy of
    clip 143 sorting after it, is never written (control: kept in the vault, it wins the clip ask). A planned
    media id the vault's live rows do not hold (143 dropped from them) raises inside the write transaction:
    rolled back, rows byte-identical, never a guessed photo."""
    _new_seq(SEQ, S_FIXED)
    load_rows, load_vault = script_fill_api.fs.load_rows, script_fill_api._load_vault

    async def _ghost(account_id):
        rows, groups, prints = await load_rows(account_id)
        return rows + [{**next(r for r in rows if r["media_id"] == 143), "media_id": 777}], groups, prints

    async def _ghost_kept(*a):                     # control: as if the drop were missing
        vault = await load_vault(*a)
        vault.items.append({**next(i for i in vault.items if i["media_id"] == 143), "media_id": 777})
        vault.live[777] = vault.live[143]
        return vault

    script_fill_api._load_vault = _ghost_kept
    try:
        assert _opts(_ok(_plan()))[7]["media"] == [777], "control: a vault 777 would win the clip ask"
    finally:
        script_fill_api._load_vault = load_vault
    script_fill_api.fs.load_rows = _ghost
    try:
        r = _ok(_apply())
    finally:
        script_fill_api.fs.load_rows = load_rows
    every = {m for o in r["applied"] for m in o["media"]}
    assert r["status"] == "ok" and 143 in every and 777 not in every, (r["status"], sorted(every))
    assert 777 not in {m["id"] for s in _rows().values() for m in s["media"]}

    _new_seq(SEQ, S_FIXED)
    before = _snapshot()

    async def _no_live_143(*a):
        vault = await load_vault(*a)
        del vault.live[143]
        return vault

    script_fill_api._load_vault = _no_live_143
    try:
        try:
            failed = _apply().status_code >= 500
        except KeyError:
            failed = True
    finally:
        script_fill_api._load_vault = load_vault
    assert failed, "a media id outside the vault's live rows was written"
    assert _snapshot() == before, "the failed apply wrote: no rollback"


# ── Undo ─────────────────────────────────────────────────────────────

def case_undo_refuses_reserved():
    """A reserved FM Sequence is never emptied by undo, even by hand-built entries matching its rows: every
    entry kept as `reserved`, nothing written."""
    _new_seq("FM12", {**sf.S1, 3: ("1/3, ppv", "", 2500)})
    rows = _rows("FM12")
    _sql("UPDATE saved_replies SET media_json = ? WHERE id = ?", json.dumps([{"id": 101, "type": "photo"}]),
         rows[1]["id"])
    _sql("UPDATE saved_replies SET media_json = ? WHERE id = ?", json.dumps([{"id": 104, "type": "photo"}]),
         rows[3]["id"])
    before = _snapshot()
    entries = [{"id": rows[1]["id"], "media_ids": [101], "previews": [], "price_cents": 0, "price_set": False},
               {"id": rows[3]["id"], "media_ids": [104], "previews": [], "price_cents": 2500, "price_set": True}]
    got = _ok(_undo(entries, script="FM12"))
    assert got == {"undone": [], "kept": [{"id": rows[1]["id"], "reason": "reserved"},
                                          {"id": rows[3]["id"], "reason": "reserved"}]}, got
    assert _snapshot() == before, "undo wrote to a reserved FM Sequence"
    _sql("DELETE FROM saved_replies WHERE account_id = ? AND script_id = 'FM12'", A)

def case_undo():
    _new_seq(SEQ, S_FIXED)
    empty = _rows()
    r = _ok(_apply())
    entries = r["undo"]
    got = _ok(_undo(entries))
    assert sorted(got["undone"]) == sorted(e["id"] for e in entries) and got["kept"] == [], got
    back = _rows()
    for step in (1, 3, 5, 7):
        assert (back[step]["media"], back[step]["previews"]) == ([], []), (step, back[step])
    assert back[3]["price"] == 0, "price_set: zeroed"
    assert back[5]["price"] == 5000, "a Fixed price stays"
    assert back[3]["updated_at"] != empty[3]["updated_at"]

    # Fill again, then: step 3 edited (an unrelated edit to its media), step 5's Fixed price edited, step 7 moved
    # to another Sequence; one entry with altered values; one id of another account's row.
    r = _ok(_apply())
    e = {x["id"]: x for x in r["undo"]}
    rows = _rows()
    s1, s3, s5, s7 = (rows[s]["id"] for s in (1, 3, 5, 7))
    _sql("UPDATE saved_replies SET media_json = ? WHERE id = ?", json.dumps([{"id": 104, "type": "photo"}]), s3)
    _sql("UPDATE saved_replies SET price_cents = 6000 WHERE id = ?", s5)
    _sql("UPDATE saved_replies SET script_id = 'Elsewhere' WHERE id = ?", s7)
    b_row = _sql("SELECT id FROM saved_replies WHERE account_id = ? LIMIT 1", B)[0][0]
    before_b = _snapshot(B)
    altered = {**e[s1], "previews": [999]}
    got = _ok(_undo([altered, e[s1], e[s3], e[s5], e[s7], {**e[s1], "id": b_row}]))
    assert got["undone"] == [s1], got
    assert got["kept"] == [{"id": s1, "reason": "edited"}, {"id": s3, "reason": "edited"},
                           {"id": s5, "reason": "edited"}, {"id": s7, "reason": "moved"},
                           {"id": b_row, "reason": "missing"}], got["kept"]
    after = _rows()
    assert after[1]["media"] == [] and after[3]["media"] == [{"id": 104, "type": "photo"}], "only untouched revert"
    assert after[5]["price"] == 6000 and _ids(after[5]["media"]) == e[s5]["media_ids"], after[5]
    assert _snapshot(B) == before_b, "another account's row untouched"
    _sql("DELETE FROM saved_replies WHERE account_id = ? AND script_id = 'Elsewhere'", A)


_harness.run()
