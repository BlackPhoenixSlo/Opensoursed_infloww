#!/usr/bin/env python3
"""Agency context and Employee identity on the Relay (docs/spec/phase-01).

The seam is the Relay over HTTP with real session cookies: every principal logs
in through `/auth/login` or `/chatter/login` via the shared two-Agency fixture,
and probe routes registered on the app in THIS process only answer with
`agency_context(account_id=<query>)` or with the outbound Employee resolver's
verdict. No ContextVar is set by hand and no production route is added.

The outbound probe pins chat-send "Sent by" attribution across the Mirror
Employee get-or-create split: owner header pick, anonymous header fallback and
the chatter's Mirror Employee all answer exactly as before.

Run: ./venv/bin/python service/tests/test_agency_context.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import dataclasses  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402

from fastapi import Request  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import employees  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Chatter, ChatterAccountAccess, ChatterUser, Employee, UserAccount,
)

# ASSUMPTION: the probe lives under /admin so the account isolation middleware
# guards it like the production outbound routes; the anonymous case opts in
# via ALLOW_ANONYMOUS_ADMIN. Overturned if the spec names a different prefix
# or an anonymous path that needs no env flag.
OUTBOUND_PROBE = "/admin/_probe/outbound-employee"


async def _outbound_probe(request: Request, account_id: str | None = None) -> dict:
    return {"employee_id": await employees.resolve_outbound_employee_id(request, account_id)}


server.app.add_api_route(OUTBOUND_PROBE, _outbound_probe, methods=["GET"])

# ASSUMPTION: the agency_context probe sits beside the outbound probe under
# /admin for the same reason (the isolation middleware guards it as it will
# guard later Phases' endpoints). Overturned with the outbound probe's prefix.
AGENCY_PROBE = "/admin/_probe/agency-context"


# The Creator arrives as `?creator=`, a parameter the isolation middleware does
# not read — the stand-in for a Creator in a body or path, where only
# agency_context's own check can refuse it. Its refusals are the handler's
# JSON `{"detail": ...}`, never the middleware's plain text.
async def _agency_probe(creator: str | None = None) -> dict:
    return dataclasses.asdict(await employees.agency_context(account_id=creator))


server.app.add_api_route(AGENCY_PROBE, _agency_probe, methods=["GET"])

IDS = fx.seed_two_agencies()


# ASSUMPTION: roster Employees are this test file's own seed, not the shared
# fixture's — no other Phase needed them yet. Overturned once a second test
# file needs roster Employees per Agency (then move them into _agency_fixtures).
async def _seed_roster_employee(owner_id: str, name: str) -> int:
    async with get_session() as s:
        row = Employee(display_name=name, is_active=True,
                       created_at=datetime.utcnow(), user_id=owner_id)
        s.add(row)
        await s.flush()
        return row.id


ROSTER_A = asyncio.run(_seed_roster_employee(IDS["agency_a_owner"], "roster_a"))
ROSTER_B = asyncio.run(_seed_roster_employee(IDS["agency_b_owner"], "roster_b"))


# ASSUMPTION: the chatter cases' extra rows (a second Creator in Agency A, a
# Creator cross-granted to both Agencies, two Chatter Access allowlists and a
# chatter whose links get removed) are this test file's own seed, like the
# roster Employees. Overturned once a second test file needs them (then move
# them into _agency_fixtures).
CREATOR_A2 = "1000003"         # a second Creator held by Agency A
CREATOR_SHARED = "1000004"     # held by both Agencies (the cross-grant edge)
# Owner ids are random hex, so which Agency sorts first is read at seed time.
FIRST_AGENCY, LATER_AGENCY = sorted(("agency_a_owner", "agency_b_owner"), key=IDS.get)
_OWN_CREATOR = {"agency_a_owner": "creator_a", "agency_b_owner": "creator_b"}


async def _seed_chatter_cases() -> str:
    now = datetime.utcnow()
    orphan_id = "c0ffee" * 5 + "00"
    async with get_session() as s:
        for aid in (CREATOR_A2, CREATOR_SHARED):
            s.add(Account(id=aid, nickname=f"creator_{aid}", color="#aaaaaa"))
            (account_registry.ACCOUNTS_DIR / aid).mkdir()
        s.add(Chatter(id=orphan_id, username="chatter_orphan", password=fx.PASSWORD,
                      display_name="chatter_orphan", color="#bbbbbb",
                      created_at=now, last_seen_at=now))
    async with get_session() as s:
        s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=CREATOR_A2))
        for owner in ("agency_a_owner", "agency_b_owner"):
            s.add(UserAccount(user_id=IDS[owner], account_id=CREATOR_SHARED))
        s.add(ChatterUser(chatter_id=orphan_id, user_id=IDS["agency_a_owner"], created_at=now))
        # chatter_a may work only Creator A in Agency A, so Creator A2 is out.
        s.add(ChatterAccountAccess(chatter_id=IDS["chatter_a"], user_id=IDS["agency_a_owner"],
                                   account_id=IDS["creator_a"]))
        # chatter_ab is allowlisted out of the shared Creator under the
        # alphabetically first Agency only; the later Agency grants it.
        s.add(ChatterAccountAccess(chatter_id=IDS["chatter_ab"], user_id=IDS[FIRST_AGENCY],
                                   account_id=IDS[_OWN_CREATOR[FIRST_AGENCY]]))
    return orphan_id


ORPHAN = asyncio.run(_seed_chatter_cases())


# The query parameter each probe reads its Creator from.
_CREATOR_PARAM = {OUTBOUND_PROBE: "account_id", AGENCY_PROBE: "creator"}


def _probe(client, path: str, account_id: str | None = None,
           employee_header: int | str | None = None):
    params = {_CREATOR_PARAM[path]: account_id} if account_id else {}
    headers = {"X-Employee-Id": str(employee_header)} if employee_header is not None else {}
    return client.get(path, params=params, headers=headers)


def _owner_context(owner: str, *, is_master: bool = False) -> dict:
    return {"agency_user_id": IDS[owner], "employee_id": None,
            "is_owner": True, "is_master": is_master}


def _chatter_context(owner: str, employee_id: int) -> dict:
    return {"agency_user_id": IDS[owner], "employee_id": employee_id,
            "is_owner": False, "is_master": False}


async def _employee_row(emp_id: int) -> tuple[str, str]:
    async with get_session() as s:
        row = await s.get(Employee, emp_id)
        return (row.user_id, row.chatter_id)


async def _mirror_rows(chatter_id: str) -> list[tuple[int, str]]:
    async with get_session() as s:
        res = await s.execute(select(Employee.id, Employee.user_id)
                              .where(Employee.chatter_id == chatter_id))
        return [tuple(r) for r in res.all()]


# ── The fixture ──────────────────────────────────────────────────────

def case_seeded_creators_pass_the_isolation_check_only_for_their_own_owner():
    owner_a = fx.login_owner("agency_a_owner")
    r = _probe(owner_a, OUTBOUND_PROBE, IDS["creator_a"])
    assert r.status_code == 200, f"own Creator: {r.status_code} {r.text}"
    r = _probe(owner_a, OUTBOUND_PROBE, IDS["creator_b"])
    assert r.status_code == 403 and r.text == "not your account", \
        f"other Agency's Creator: {r.status_code} {r.text}"
    r = _probe(fx.login_owner("agency_b_owner"), OUTBOUND_PROBE, IDS["creator_b"])
    assert r.status_code == 200, f"owner B, own Creator: {r.status_code} {r.text}"


def case_fixture_ids_are_neutral_and_seeding_twice_is_the_same_mapping():
    assert IDS["creator_a"].isdigit() and IDS["creator_b"].isdigit(), IDS
    assert fx.seed_two_agencies() == IDS, "second seed changed the mapping"
    for name in ("chatter_a", "chatter_b", "chatter_ab"):
        fx.login_chatter(name)
    fx.login_owner("agency_master")


# ── Owner header pick ("Sent by") ──────────────────────────────────

def case_owner_header_naming_an_employee_of_its_own_agency_is_returned():
    r = _probe(fx.login_owner("agency_a_owner"), OUTBOUND_PROBE, IDS["creator_a"], ROSTER_A)
    assert r.status_code == 200, r.text
    assert r.json() == {"employee_id": ROSTER_A}, r.json()


def case_owner_header_naming_an_employee_of_another_agency_falls_back_to_the_owner():
    # The owner acts as self: a header naming another Agency's row is a spoof,
    # so the write is stamped with the owner's own Owner row, never ROSTER_B.
    owner_a = fx.login_owner("agency_a_owner")
    own = _probe(owner_a, OUTBOUND_PROBE, IDS["creator_a"]).json()["employee_id"]
    assert isinstance(own, int) and own != ROSTER_B, own
    r = _probe(owner_a, OUTBOUND_PROBE, IDS["creator_a"], ROSTER_B)
    assert r.status_code == 200, r.text
    assert r.json() == {"employee_id": own}, r.json()


# ── Internal cron fallback, unchanged ────────────────────────────────

def case_anonymous_digit_header_is_returned_as_is():
    # The isolation middleware 401s an anonymous /admin caller unless the
    # deployment sets ALLOW_ANONYMOUS_ADMIN; set it for this call only.
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    try:
        r = _probe(_harness.make_client(), OUTBOUND_PROBE, None, 777)
    finally:
        os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)
    assert r.status_code == 200, r.text
    assert r.json() == {"employee_id": 777}, r.json()


# ── Chatter Mirror Employee ──────────────────────────────────────────

def case_chatter_gets_its_mirror_employee_and_a_second_call_reuses_it():
    chatter_a = fx.login_chatter("chatter_a")
    first = _probe(chatter_a, OUTBOUND_PROBE, IDS["creator_a"])
    assert first.status_code == 200, first.text
    emp_id = first.json()["employee_id"]
    assert isinstance(emp_id, int), first.json()
    assert asyncio.run(_mirror_rows(IDS["chatter_a"])) == [(emp_id, IDS["agency_a_owner"])]

    second = _probe(chatter_a, OUTBOUND_PROBE, IDS["creator_a"])
    assert second.json() == {"employee_id": emp_id}, second.json()
    assert asyncio.run(_mirror_rows(IDS["chatter_a"])) == [(emp_id, IDS["agency_a_owner"])], \
        "a second call created another Mirror Employee"


def case_chatter_header_is_ignored_for_its_mirror_employee():
    chatter_a = fx.login_chatter("chatter_a")
    mirror = _probe(chatter_a, OUTBOUND_PROBE, IDS["creator_a"]).json()["employee_id"]
    assert isinstance(mirror, int) and mirror != ROSTER_A, mirror
    r = _probe(chatter_a, OUTBOUND_PROBE, IDS["creator_a"], ROSTER_A)
    assert r.status_code == 200, r.text
    assert r.json() == {"employee_id": mirror}, r.json()


def case_chatter_resolver_calls_the_split_get_or_create_with_the_owning_agency():
    calls = []

    async def _recording(chatter_id, owner_user_id, *, display_name, color):
        calls.append((chatter_id, owner_user_id, display_name, color))
        return 424242

    original = employees.get_or_create_mirror_employee
    employees.get_or_create_mirror_employee = _recording
    try:
        r = _probe(fx.login_chatter("chatter_b"), OUTBOUND_PROBE, IDS["creator_b"])
    finally:
        employees.get_or_create_mirror_employee = original
    assert r.json() == {"employee_id": 424242}, r.json()
    assert calls == [(IDS["chatter_b"], IDS["agency_b_owner"], "chatter_b", "#bbbbbb")], calls



# ── agency_context: owner, Master, impersonation, anonymous ──────────

def case_owner_is_the_agency_with_no_employee():
    r = _probe(fx.login_owner("agency_a_owner"), AGENCY_PROBE)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json() == _owner_context("agency_a_owner"), r.json()


def case_owner_naming_its_own_creator_gets_its_own_agency():
    r = _probe(fx.login_owner("agency_a_owner"), AGENCY_PROBE, IDS["creator_a"])
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json() == _owner_context("agency_a_owner"), r.json()


def case_owner_naming_another_agencys_creator_is_403():
    r = _probe(fx.login_owner("agency_a_owner"), AGENCY_PROBE, IDS["creator_b"])
    assert r.status_code == 403 and r.json() == {"detail": "not your account"}, \
        f"{r.status_code} {r.text}"


def case_owner_employee_header_never_becomes_the_employee():
    owner_a = fx.login_owner("agency_a_owner")
    for header in (ROSTER_A, ROSTER_B):
        r = _probe(owner_a, AGENCY_PROBE, IDS["creator_a"], header)
        assert r.status_code == 200, f"header {header}: {r.status_code} {r.text}"
        assert r.json() == _owner_context("agency_a_owner"), (header, r.json())


def case_owner_cookie_wins_over_a_chatter_cookie_in_the_same_client():
    both = fx.login_owner("agency_a_owner")
    rc = both.post("/chatter/login", json={"username": "chatter_b", "password": fx.PASSWORD})
    assert rc.status_code == 200, f"chatter login on the owner client: {rc.status_code} {rc.text}"
    r = _probe(both, AGENCY_PROBE)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json() == _owner_context("agency_a_owner"), r.json()


def case_master_keeps_its_own_agency_with_the_master_flag():
    master = fx.login_owner("agency_master")
    r = _probe(master, AGENCY_PROBE)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json() == _owner_context("agency_master", is_master=True), r.json()
    # Naming another Agency's Creator does not move the Master into it.
    r = _probe(master, AGENCY_PROBE, IDS["creator_b"])
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json() == _owner_context("agency_master", is_master=True), r.json()


def case_master_impersonating_owner_b_sees_agency_b():
    master = fx.login_owner("agency_master")
    r = master.post("/admin/impersonate", json={
        "user_id": IDS["agency_b_owner"],
        "admin_password": os.environ["ADMIN_PASSWORD"],
    })
    assert r.status_code == 200, f"impersonate: {r.status_code} {r.text}"
    r = _probe(master, AGENCY_PROBE)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json() == _owner_context("agency_b_owner"), r.json()


def case_anonymous_is_401_even_with_anonymous_admin_allowed():
    # The flag lets the isolation middleware pass an anonymous caller through,
    # so the 401 below is agency_context's own refusal.
    anon = _harness.make_client()
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    try:
        r = _probe(anon, AGENCY_PROBE)
        named = _probe(anon, AGENCY_PROBE, IDS["creator_a"])
    finally:
        os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)
    for resp in (r, named):
        assert resp.status_code == 401 and resp.json() == {"detail": "sign in required"}, \
            f"{resp.status_code} {resp.text}"


# ── agency_context: chatters ─────────────────────────────────────────

def case_chatter_a_gets_agency_a_and_its_own_mirror_employee_reused():
    chatter_a = fx.login_chatter("chatter_a")
    first = _probe(chatter_a, AGENCY_PROBE)
    assert first.status_code == 200, f"{first.status_code} {first.text}"
    emp_id = first.json()["employee_id"]
    assert isinstance(emp_id, int), first.json()
    assert first.json() == _chatter_context("agency_a_owner", emp_id), first.json()
    assert asyncio.run(_employee_row(emp_id)) == (IDS["agency_a_owner"], IDS["chatter_a"])
    rows = asyncio.run(_mirror_rows(IDS["chatter_a"]))
    assert rows == [(emp_id, IDS["agency_a_owner"])], rows

    second = _probe(chatter_a, AGENCY_PROBE)
    assert second.json() == _chatter_context("agency_a_owner", emp_id), second.json()
    assert asyncio.run(_mirror_rows(IDS["chatter_a"])) == rows, \
        "a second call created another Mirror Employee"


def case_chatter_employee_header_never_becomes_the_employee():
    chatter_a = fx.login_chatter("chatter_a")
    own = _probe(chatter_a, AGENCY_PROBE).json()["employee_id"]
    assert isinstance(own, int) and own not in (ROSTER_A, ROSTER_B), own
    for header in (ROSTER_A, ROSTER_B):
        r = _probe(chatter_a, AGENCY_PROBE, IDS["creator_a"], header)
        assert r.status_code == 200, f"header {header}: {r.status_code} {r.text}"
        assert r.json() == _chatter_context("agency_a_owner", own), (header, r.json())


def case_chatter_a_naming_creator_b_is_403():
    r = _probe(fx.login_chatter("chatter_a"), AGENCY_PROBE, IDS["creator_b"])
    assert r.status_code == 403 and r.json() == {"detail": "not your account"}, \
        f"{r.status_code} {r.text}"


def case_chatter_allowlisted_away_from_a_creator_of_its_own_agency_is_403():
    # Owner A holds Creator A2, so the refusal is chatter_a's allowlist and
    # not its Agency links.
    r = _probe(fx.login_owner("agency_a_owner"), AGENCY_PROBE, CREATOR_A2)
    assert r.status_code == 200, f"owner A, Creator A2: {r.status_code} {r.text}"
    r = _probe(fx.login_chatter("chatter_a"), AGENCY_PROBE, CREATOR_A2)
    assert r.status_code == 403 and r.json() == {"detail": "not your account"}, \
        f"{r.status_code} {r.text}"


def case_two_agency_chatter_is_placed_by_the_creator_it_names():
    chatter_ab = fx.login_chatter("chatter_ab")
    r = _probe(chatter_ab, AGENCY_PROBE)
    assert r.status_code == 400 and r.json() == {"detail": "name a creator to choose the agency"}, \
        f"no Creator: {r.status_code} {r.text}"

    in_a = _probe(chatter_ab, AGENCY_PROBE, IDS["creator_a"])
    in_b = _probe(chatter_ab, AGENCY_PROBE, IDS["creator_b"])
    assert in_a.status_code == 200 and in_b.status_code == 200, (in_a.text, in_b.text)
    emp_a, emp_b = in_a.json()["employee_id"], in_b.json()["employee_id"]
    assert in_a.json() == _chatter_context("agency_a_owner", emp_a), in_a.json()
    assert in_b.json() == _chatter_context("agency_b_owner", emp_b), in_b.json()
    assert isinstance(emp_a, int) and isinstance(emp_b, int) and emp_a != emp_b, (emp_a, emp_b)
    assert asyncio.run(_employee_row(emp_a)) == (IDS["agency_a_owner"], IDS["chatter_ab"])
    assert asyncio.run(_employee_row(emp_b)) == (IDS["agency_b_owner"], IDS["chatter_ab"])


def case_cross_granted_creator_resolves_past_the_agency_that_allowlists_it_out():
    chatter_ab = fx.login_chatter("chatter_ab")
    r = _probe(chatter_ab, AGENCY_PROBE, CREATOR_SHARED)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    emp = r.json()["employee_id"]
    assert r.json() == _chatter_context(LATER_AGENCY, emp), r.json()
    assert asyncio.run(_employee_row(emp)) == (IDS[LATER_AGENCY], IDS["chatter_ab"])

    # The chat-send resolver keeps its unfiltered tie-break: alphabetically
    # first Agency, allowlist or not.
    sent = _probe(chatter_ab, OUTBOUND_PROBE, CREATOR_SHARED)
    assert sent.status_code == 200, f"{sent.status_code} {sent.text}"
    sent_emp = sent.json()["employee_id"]
    assert isinstance(sent_emp, int), sent.json()
    assert asyncio.run(_employee_row(sent_emp)) == (IDS[FIRST_AGENCY], IDS["chatter_ab"])


def case_chatter_with_every_agency_link_removed_is_403():
    orphan = fx.login_chatter("chatter_orphan")
    r = _probe(orphan, AGENCY_PROBE)
    assert r.status_code == 200, f"while linked: {r.status_code} {r.text}"

    async def _unlink():
        async with get_session() as s:
            await s.execute(delete(ChatterUser).where(ChatterUser.chatter_id == ORPHAN))
    asyncio.run(_unlink())

    r = _probe(orphan, AGENCY_PROBE)
    assert r.status_code == 403 and r.json() == {"detail": "chatter is not linked to an agency"}, \
        f"{r.status_code} {r.text}"


def case_chatter_gets_503_when_the_mirror_employee_cannot_be_resolved():
    async def _db_down(chatter_id, owner_user_id, *, display_name, color):
        return None

    chatter_a = fx.login_chatter("chatter_a")
    original = employees.get_or_create_mirror_employee
    employees.get_or_create_mirror_employee = _db_down
    try:
        r = _probe(chatter_a, AGENCY_PROBE, IDS["creator_a"])
    finally:
        employees.get_or_create_mirror_employee = original
    assert r.status_code == 503 and r.json() == {"detail": "mirror employee unavailable"}, \
        f"{r.status_code} {r.text}"


def case_chatter_agency_context_and_outbound_resolver_name_the_same_employee():
    chatter_a = fx.login_chatter("chatter_a")
    ctx = _probe(chatter_a, AGENCY_PROBE, IDS["creator_a"])
    sent = _probe(chatter_a, OUTBOUND_PROBE, IDS["creator_a"])
    assert ctx.status_code == 200 and sent.status_code == 200, (ctx.text, sent.text)
    assert isinstance(sent.json()["employee_id"], int), sent.json()
    assert ctx.json()["employee_id"] == sent.json()["employee_id"], (ctx.json(), sent.json())


_harness.run()
