#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import os  # noqa: E402

os.environ["OFM_NEW_WRITES_ENABLED"] = "1"

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import importlib.util  # noqa: E402
import re  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import auth  # noqa: E402
import agency_context as agency_ctx  # noqa: E402
import employees  # noqa: E402
import permissions  # noqa: E402
import server  # noqa: E402
from chatters import _CHATTER_BLOCKED_ADMIN_PREFIXES  # noqa: E402
from db.engine import engine, get_session  # noqa: E402
from db.models import Action, AiDecision, ChatterAccountAccess, Message, SavedReply, Transaction  # noqa: E402
from sqlalchemy import delete, event, func, select, text  # noqa: E402

IDS = fx.seed_two_agencies()
account_registry.upsert_account(IDS["creator_a"], nickname="creator_a")
NAV = Path(__file__).resolve().parents[2] / "app" / "lib" / "nav.ts"


_PLUGIN_LINK = re.compile(r'\{\s*group:\s*"([^"]+)",(?:\s*first:\s*true,)?\s*link:\s*(\{[^}]*\})\s*\}')


def _nav_text() -> str:
    nav_ts = NAV.read_text()
    for reg in sorted(NAV.parents[1].glob("plugins/*/register.ts")):
        for group, link in _PLUGIN_LINK.findall(reg.read_text()):
            head, tail = nav_ts.split(f'label: "{group}"', 1)
            nav_ts = head + f'label: "{group}"' + tail.replace("children: [", f"children: [\n      {link},", 1)
    return nav_ts


def _mirror(chatter: str, owner: str) -> int:
    emp = asyncio.run(employees.get_or_create_mirror_employee(
        IDS[chatter], IDS[owner], display_name=chatter, color="#bbbbbb"))
    assert emp is not None
    return emp


EMP_A = _mirror("chatter_a", "agency_a_owner")
EMP_AB_A = _mirror("chatter_ab", "agency_a_owner")
EMP_AB_B = _mirror("chatter_ab", "agency_b_owner")

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_AB = fx.login_chatter("chatter_ab")

REVENUE = "/admin/stats/revenue?from=2026-06-10&to=2026-06-11&group_by=day"
REFERRALS = "/admin/stats/referrals?from=2026-06-10&to=2026-06-11"
DENIED_DASHBOARD = {"detail": "Your role does not allow Dashboard"}


def _put(client, tab: str, blob: dict) -> None:
    r = client.put(f"/admin/settings/{tab}", json=blob)
    assert r.status_code == 200, f"PUT {tab}: {r.status_code} {r.text}"


def _role(role_id: str, pages: dict[str, bool], scope: str = "self") -> dict:
    return {"id": role_id, "name": f"Fixture {role_id}", "description": "", "permissions": pages,
            "scope": scope}


def _roles(client, enforce: bool, assignments: dict[int, str], *roles: dict) -> None:
    _put(client, "roles", {"enforce": enforce, "roles": list(roles),
                           "assignments": {str(e): r for e, r in assignments.items()}})


def _only(*hrefs: str) -> dict[str, bool]:
    return {h: True for h in hrefs}


def _all_but(*hrefs: str) -> dict[str, bool]:
    return {h: h not in hrefs for h in permissions.PAGE_MAP}


def _reset() -> None:
    _put(OWNER_A, "roles", {"enforce": False})
    _put(OWNER_B, "roles", {"enforce": False})


class _FakeOF:

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name):
        def _call(*_a, **_k):
            self.calls.append(name)
            return {"ok": True}
        return _call


def _with_fake_of(fn):
    fake = _FakeOF()
    original = server._get_client
    server._get_client = lambda *_a, **_k: fake
    try:
        fn(fake)
    finally:
        server._get_client = original


def _db(query):
    async def _run():
        async with get_session() as s:
            return (await s.execute(query)).scalar_one()
    return asyncio.run(_run())



def case_same_route_is_allowed_with_enforcement_off_and_refused_when_on():
    pro = _role("role-pro", _only("/messages-pro"))
    _roles(OWNER_A, False, {EMP_A: "role-pro"}, pro)
    try:
        assert CHATTER_A.get(REVENUE).status_code == 200
        _roles(OWNER_A, True, {EMP_A: "role-pro"}, pro)
        r = CHATTER_A.get(REVENUE)
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, f"{r.status_code} {r.text}"
        _roles(OWNER_A, False, {EMP_A: "role-pro"}, pro)
        assert CHATTER_A.get(REVENUE).status_code == 200
    finally:
        _reset()


def case_a_denied_put_writes_nothing_and_calls_no_onlyfans_fake():
    async def _seed():
        async with get_session() as s:
            row = SavedReply(account_id=IDS["creator_a"], title="Fixture reply", text="before",
                             price_cents=0, media_json="[]", tagged_users_json="[]",
                             previews_json="[]")
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return row.id
    reply_id = asyncio.run(_seed())
    actions = select(func.count()).select_from(Action)
    _roles(OWNER_A, True, {EMP_A: "role-none"}, _role("role-none", {}))
    try:
        before = _db(actions)
        r = CHATTER_A.put(f"/admin/saved-replies/{reply_id}",
                          json={"title": "Changed", "text": "after"})
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Scripts"}, r.text
        assert _db(select(SavedReply.text).where(SavedReply.id == reply_id)) == "before"
        assert _db(actions) == before

        def _template(fake):
            r = CHATTER_A.put("/api/of/v2/subscriptions/42/note", json={"note": "after"})
            assert r.status_code == 403 and r.json() == {
                "detail": "Your role does not allow Messages Basic"}, r.text
            assert fake.calls == []
        _with_fake_of(_template)
        assert _db(actions) == before
    finally:
        _reset()

    def _allowed(fake):
        r = CHATTER_A.put("/api/of/v2/subscriptions/42/note", json={"note": "after"})
        assert r.status_code == 200, r.text
        assert fake.calls == ["set_fan_note"]
    _with_fake_of(_allowed)


def case_a_route_shared_by_two_pages_is_allowed_when_either_is_granted():
    shared_routes = ("/api/of/v2/subscriptions/count/all", REVENUE)
    for shared in shared_routes:
        assert permissions.route_pages(shared.split("?")[0], "GET") == ("/", "/analytics/creator-reports"), shared

    def _check(fake):
        for shared in shared_routes:
            for granted in ("/", "/analytics/creator-reports"):
                _roles(OWNER_A, True, {EMP_A: "role-one"}, _role("role-one", _only(granted)))
                r = CHATTER_A.get(shared)
                assert r.status_code == 200, f"{shared} {granted}: {r.status_code} {r.text}"
            _roles(OWNER_A, True, {EMP_A: "role-one"}, _role("role-one", _only("/messages-pro")))
            r = CHATTER_A.get(shared)
            assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, f"{shared}: {r.text}"
        assert fake.calls == ["subscription_counts_all"] * 2
    try:
        _with_fake_of(_check)
    finally:
        _reset()


def case_an_auto_post_only_route_is_refused_a_smart_messages_only_chatter_and_served_one_granted_auto_post():
    path = "/admin/automation-kinds"
    assert permissions.route_pages(path, "GET") == ("/growth/auto-post",)

    def _check(fake):
        _roles(OWNER_A, True, {EMP_A: "role-sm"}, _role("role-sm", _only("/growth/smart-messages")))
        r = CHATTER_A.get(path)
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Auto Post"}, r.text
        _roles(OWNER_A, True, {EMP_A: "role-ap"}, _role("role-ap", _only("/growth/auto-post")))
        r = CHATTER_A.get(path)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert fake.calls == [], fake.calls
    try:
        _with_fake_of(_check)
    finally:
        _reset()


def case_my_automations_is_opt_in_for_a_chatter_refused_with_enforcement_off_served_when_granted():
    path = "/admin/automation-kinds"
    config = f"/admin/autoreply-config?account_id={IDS['creator_a']}"
    style = f"/admin/style-config?account_id={IDS['creator_a']}"
    assert permissions.route_pages("/admin/autoreply-config", "GET") == ("/growth/auto-post", "/growth/auto-reply")
    assert permissions.route_pages("/admin/style-config", "GET") == ("/growth/auto-post", "/growth/auto-reply")
    rules = f"/admin/automation-rules?account_id={IDS['creator_a']}"
    assert not set(permissions.route_pages("/admin/automation-rules", "GET")) <= permissions.OPT_IN_PAGES

    def _check(fake):
        _reset()
        r = CHATTER_A.get(path)
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Auto Post"}, r.text
        r = CHATTER_A.get(config)
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Auto Post or Auto-reply"}, r.text
        assert CHATTER_A.get(rules).status_code == 200
        assert OWNER_A.get(path).status_code == 200
        _roles(OWNER_A, False, {EMP_A: "role-ap"}, _role("role-ap", _only("/growth/auto-post")))
        assert CHATTER_A.get(path).status_code == 403
        _roles(OWNER_A, True, {EMP_A: "role-ar"}, _role("role-ar", _only("/growth/auto-reply")))
        assert CHATTER_A.get(config).status_code == 200
        assert CHATTER_A.get(style).status_code == 200
        assert CHATTER_A.get(path).status_code == 403
        _roles(OWNER_A, True, {EMP_A: "admin"})
        assert CHATTER_A.get(REVENUE).status_code == 200
        assert CHATTER_A.get(path).status_code == 403
        _roles(OWNER_A, True, {EMP_A: "admin"}, _role("admin", _only("/growth/auto-post"), "all"))
        assert CHATTER_A.get(path).status_code == 200
        assert fake.calls == [], fake.calls
    try:
        _with_fake_of(_check)
    finally:
        _reset()


def case_a_my_automations_rule_kind_needs_its_page_on_the_shared_rules_route():
    new = {"account_id": IDS["creator_a"], "kind": "mass_premade", "name": "Fixture auto mass",
           "every_seconds": 86400, "payload": {"messages": [{"text": "hi"}]}, "is_enabled": False}
    denied = {"detail": "Your role does not allow Auto Mass"}
    try:
        _reset()
        r = CHATTER_A.post("/admin/automation-rules", json=new)
        assert r.status_code == 403 and r.json() == denied, r.text
        r = CHATTER_A.post("/admin/automation-rules", json={**new, "kind": "unsend_messages", "payload": None})
        assert r.status_code == 200, r.text
        assert CHATTER_A.delete(f"/admin/automation-rules/{r.json()['id']}").status_code == 200
        _roles(OWNER_A, True, {EMP_A: "role-sm"}, _role("role-sm", _only("/growth/smart-messages")))
        r = CHATTER_A.post("/admin/automation-rules", json=new)
        assert r.status_code == 403 and r.json() == denied, r.text
        _roles(OWNER_A, True, {EMP_A: "role-am"}, _role("role-am", _only("/growth/auto-mass")))
        r = CHATTER_A.post("/admin/automation-rules", json=new)
        assert r.status_code == 200, r.text
        rule_id = r.json()["id"]
        assert CHATTER_A.patch(f"/admin/automation-rules/{rule_id}", json={"name": "Renamed"}).status_code == 200
        _roles(OWNER_A, True, {EMP_A: "role-sm"}, _role("role-sm", _only("/growth/smart-messages")))
        for r in (CHATTER_A.patch(f"/admin/automation-rules/{rule_id}", json={"name": "No"}),
                  CHATTER_A.post(f"/admin/automation-rules/{rule_id}/run-now"),
                  CHATTER_A.delete(f"/admin/automation-rules/{rule_id}"),
                  CHATTER_A.post("/admin/automation/enqueue",
                                 json={"account_id": IDS["creator_a"], "kind": "mass_premade",
                                       "payload": {"messages": [{"text": "hi"}], "dry_run": True}}),
                  CHATTER_A.post("/admin/automation-rules/switch",
                                 json={"account_id": IDS["creator_a"], "kind": "auto_posts", "enable": False})):
            assert r.status_code == 403, f"{r.status_code} {r.text}"
        assert OWNER_A.delete(f"/admin/automation-rules/{rule_id}").status_code == 200
    finally:
        _reset()


def case_the_gen_info_switch_needs_the_gen_info_page():
    body = {"account_id": IDS["creator_a"], "kind": "gen_info", "enable": False}
    denied = {"detail": "Your role does not allow Gen-Info"}
    try:
        _reset()
        r = CHATTER_A.post("/admin/automation-rules/switch", json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        _roles(OWNER_A, True, {EMP_A: "role-am"}, _role("role-am", _only("/growth/auto-mass")))
        r = CHATTER_A.post("/admin/automation-rules/switch", json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        _roles(OWNER_A, True, {EMP_A: "role-gi"}, _role("role-gi", _only("/growth/gen-info")))
        r = CHATTER_A.post("/admin/automation-rules/switch", json=body)
        assert r.status_code == 200, r.text
        assert OWNER_A.post("/admin/automation-rules/switch", json=body).status_code == 200
    finally:
        _reset()


def case_the_full_ai_chat_switch_is_owner_only_and_the_today_read_follows_the_page():
    body = {"account_id": IDS["creator_a"], "kind": "full_ai_chat", "enable": False}
    denied = {"detail": "Your role does not allow Full AI Chat"}
    today = f"/admin/full-ai/today?account_id={IDS['creator_a']}"
    try:
        _reset()
        r = CHATTER_A.post("/admin/automation-rules/switch", json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        _roles(OWNER_A, True, {EMP_A: "role-fa"}, _role("role-fa", _only("/full-ai-chatter")))
        r = CHATTER_A.post("/admin/automation-rules/switch", json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        r = CHATTER_A.get(today)
        assert r.status_code == 200, r.text
        _roles(OWNER_A, True, {EMP_A: "role-gi"}, _role("role-gi", _only("/growth/gen-info")))
        r = CHATTER_A.post("/admin/automation-rules/switch", json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        r = CHATTER_A.get(today)
        assert r.status_code == 403 and r.json() == denied, r.text
        assert OWNER_A.post("/admin/automation-rules/switch", json=body).status_code == 200
        assert OWNER_A.get(today).status_code == 200
    finally:
        _reset()


def case_full_ai_prepare_content_is_owner_only_and_account_checked():
    start, status = "/admin/full-ai/prepare-content", f"/admin/full-ai/prepare-content/status?account_id={IDS['creator_a']}"
    body = {"account_id": IDS["creator_a"]}
    try:
        _roles(OWNER_A, True, {EMP_A: "role-fa"}, _role("role-fa", _only("/full-ai-chatter")))
        for r in (CHATTER_A.post(start, json=body), CHATTER_A.get(status)):
            assert r.status_code == 403 and "owner-only endpoint" in r.text, (r.status_code, r.text)
        _reset()
        for r in (CHATTER_A.post(start, json=body), CHATTER_A.get(status)):
            assert r.status_code == 403 and "owner-only endpoint" in r.text, (r.status_code, r.text)
        for r in (OWNER_B.post(start, json=body), OWNER_B.get(status)):
            assert r.status_code == 403, (r.status_code, r.text)
        r = OWNER_A.get(status)
        assert r.status_code == 200 and r.json()["run_id"] is None, r.text
    finally:
        _reset()


def case_the_full_ai_test_turn_is_owner_only_and_the_session_read_follows_the_page():
    aid = IDS["creator_a"]
    turn = {"account_id": aid, "pair": "role-pair", "side": "checkpoint", "n": 2, "text": "hey"}
    session = f"/admin/full-ai/test/session?account_id={aid}&pair=role-pair"
    denied = {"detail": "Your role does not allow Full AI Chat"}
    try:
        _reset()
        r = CHATTER_A.post("/admin/full-ai/test/turn", json=turn)
        assert r.status_code == 403 and r.json() == denied, r.text
        _roles(OWNER_A, True, {EMP_A: "role-fa"}, _role("role-fa", _only("/full-ai-chatter")))
        r = CHATTER_A.post("/admin/full-ai/test/turn", json=turn)
        assert r.status_code == 403 and r.json() == denied, r.text
        r = CHATTER_A.get(session)
        assert r.status_code == 200 and r.json() == {"rows": []}, r.text
        _roles(OWNER_A, True, {EMP_A: "role-gi"}, _role("role-gi", _only("/growth/gen-info")))
        r = CHATTER_A.get(session)
        assert r.status_code == 403 and r.json() == denied, r.text
        r = OWNER_A.post("/admin/full-ai/test/turn", json=turn)
        assert r.status_code == 409 and r.json() == {"row_id": None}, r.text
        assert OWNER_A.get(session).status_code == 200
        assert _db(select(func.count()).select_from(AiDecision)) == 0
    finally:
        _reset()


def case_the_full_ai_test_settle_is_owner_only():
    body = {"account_id": IDS["creator_a"], "pair": "role-pair", "side": "draft", "row_id": 424242,
            "outcome": "bought"}
    denied = {"detail": "Your role does not allow Full AI Chat"}
    settle = "/admin/full-ai/test/settle"
    try:
        _reset()
        r = CHATTER_A.post(settle, json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        _roles(OWNER_A, True, {EMP_A: "role-fa"}, _role("role-fa", _only("/full-ai-chatter")))
        r = CHATTER_A.post(settle, json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        r = OWNER_A.post(settle, json=body)
        assert r.status_code == 404 and r.json() == {"detail": "not_this_session"}, r.text
    finally:
        _reset()


def case_a_full_ai_config_put_carrying_sell_on_is_owner_only():
    put = "/admin/full-ai/config/draft"
    body = {"account_id": IDS["creator_a"], "draft": {"sell_on": True}, "rev": 99}
    denied = {"detail": "Your role does not allow Full AI Chat"}
    try:
        _reset()
        r = CHATTER_A.put(put, json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        _roles(OWNER_A, True, {EMP_A: "role-fa"}, _role("role-fa", _only("/full-ai-chatter")))
        r = CHATTER_A.put(put, json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        r = OWNER_A.put(put, json=body)
        assert r.status_code == 409 and r.json()["rev"] == 0, r.text
    finally:
        _reset()


def case_the_full_ai_persona_draft_is_owner_only_even_with_the_page_granted():
    draft = "/admin/full-ai/persona/draft"
    body = {"account_id": IDS["creator_a"], "current_text": ""}
    denied = {"detail": "Your role does not allow Full AI Chat"}
    try:
        _reset()
        r = CHATTER_A.post(draft, json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        _roles(OWNER_A, True, {EMP_A: "role-fa"}, _role("role-fa", _only("/full-ai-chatter")))
        r = CHATTER_A.post(draft, json=body)
        assert r.status_code == 403 and r.json() == denied, r.text
        r = OWNER_A.post(draft, json=body)
        assert r.status_code == 200 and r.json()["need_describe"] is True, r.text
    finally:
        _reset()


def case_funnel_writes_are_auto_funnels_and_the_list_stays_open():
    new = {"name": "Fixture opt-in funnel", "opening_message": "hey"}
    denied = {"detail": "Your role does not allow Auto Funnel"}
    try:
        _reset()
        assert CHATTER_A.get("/admin/funnels").status_code == 200
        r = CHATTER_A.post("/admin/funnels", json=new)
        assert r.status_code == 403 and r.json() == denied, r.text
        r = CHATTER_A.put(f"/admin/funnels/1/media/{IDS['creator_a']}", json={})
        assert r.status_code == 403 and r.json() == denied, r.text
        _roles(OWNER_A, True, {EMP_A: "role-af"}, _role("role-af", _only("/growth/auto-funnel")))
        r = CHATTER_A.post("/admin/funnels", json=new)
        assert r.status_code == 200, r.text
        assert CHATTER_A.delete(f"/admin/funnels/{r.json()['id']}").status_code == 200
    finally:
        _reset()


def case_unconfirmed_send_dismiss_is_auto_funnels_like_retry_and_agency_scoped():
    import json
    from datetime import timedelta
    from db.models import FollowupState
    denied = {"detail": "Your role does not allow Auto Funnel"}
    q = f"?account_id={IDS['creator_a']}"
    marked_at = datetime.utcnow().replace(microsecond=0) - timedelta(hours=1)
    body = {"kind": "followup", "fan_id": 424242, "since": marked_at.isoformat() + "Z"}

    async def _seed():
        async with get_session() as s:
            s.add(FollowupState(account_id=IDS["creator_a"], fan_id=424242, phase="tracking", cycle=1,
                                messages_sent="{}", sending_at=marked_at,
                                sending_ctx=json.dumps({"step": 1})))

    async def _marker():
        async with get_session() as s:
            return (await s.get(FollowupState, (IDS["creator_a"], 424242))).sending_at
    asyncio.run(_seed())
    try:
        _reset()
        for path in ("retry", "dismiss"):
            r = CHATTER_A.post(f"/admin/unconfirmed-sends/{path}{q}", json=body)
            assert r.status_code == 403 and r.json() == denied, (path, r.text)
        r = OWNER_B.post(f"/admin/unconfirmed-sends/dismiss{q}", json=body)
        assert r.status_code == 403, ("another Agency's Creator", r.text)
        assert asyncio.run(_marker()) == marked_at, "refused: the row untouched"
        _roles(OWNER_A, True, {EMP_A: "role-af"}, _role("role-af", _only("/growth/auto-funnel")))
        r = CHATTER_A.post(f"/admin/unconfirmed-sends/dismiss{q}", json=body)
        assert (r.status_code, r.json()) == (200, {"status": "dismissed"}), r.text
        assert asyncio.run(_marker()) is None
        r = OWNER_A.post(f"/admin/unconfirmed-sends/dismiss{q}", json=body)
        assert (r.status_code, r.json()) == (200, {"status": "already_sent"}), r.text
    finally:
        _reset()


def case_a_two_agency_chatter_is_granted_an_opt_in_page_by_the_enforcing_agency_beside_one_that_is_off():
    new = {"name": "Fixture two-agency funnel", "opening_message": "hey"}
    path = "/admin/automation-kinds"
    try:
        _reset()
        assert CHATTER_AB.get(path).status_code == 403
        _roles(OWNER_A, True, {EMP_AB_A: "role-am"},
               _role("role-am", _only("/growth/auto-mass", "/growth/auto-post", "/growth/auto-funnel")))

        def _kinds(fake):
            r = CHATTER_AB.get(path)
            assert r.status_code == 200, r.text
        _with_fake_of(_kinds)
        r = CHATTER_AB.post("/admin/funnels", json=new)
        assert r.status_code == 200, r.text
        assert OWNER_A.delete(f"/admin/funnels/{r.json()['id']}").status_code == 200
        r = CHATTER_AB.post("/admin/automation-rules",
                            json={"account_id": IDS["creator_b"], "kind": "mass_premade", "is_enabled": False,
                                  "payload": {"messages": [{"text": "hi"}]}})
        assert r.status_code == 403, r.text
        r = CHATTER_AB.post("/admin/automation-rules",
                            json={"account_id": IDS["creator_a"], "kind": "mass_premade", "is_enabled": False,
                                  "payload": {"messages": [{"text": "hi"}]}})
        assert r.status_code == 200, r.text
        assert OWNER_A.delete(f"/admin/automation-rules/{r.json()['id']}").status_code == 200
    finally:
        _reset()


def case_the_opt_in_pages_are_the_navs_opt_in_groups():
    nav_ts = _nav_text()
    groups = [nav_ts.split(f'label: "{g}"', 1)[1].split("],", 1)[0] for g in ("My Automations", "My AI Chatter")]
    assert all("chatterOptIn: true" in g for g in groups)
    assert nav_ts.count("chatterOptIn: true") == 2
    opt_in = {href for g in groups for href, rest in re.findall(r'href: "([^"]+)"([^}]*)\}', g)
              if "notOptIn: true" not in rest}
    assert opt_in == permissions.OPT_IN_PAGES
    assert "/growth/get-to-know-fans" in groups[1] and "/growth/get-to-know-fans" not in permissions.OPT_IN_PAGES


def case_a_creator_reports_only_chatter_reads_revenue_and_a_role_granting_neither_page_does_not():
    try:
        _roles(OWNER_A, True, {EMP_A: "role-cr"}, _role("role-cr", _only("/analytics/creator-reports")))
        for path in (REVENUE, "/admin/stats/revenue?group_by=kind",
                     "/admin/stats/revenue?group_by=day&include_net=true", "/admin/stats/per-model", REFERRALS):
            r = CHATTER_A.get(path)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
        _roles(OWNER_A, True, {EMP_A: "role-none"},
               _role("role-none", _all_but("/", "/analytics/creator-reports")))
        for path in (REVENUE, REFERRALS):
            r = CHATTER_A.get(path)
            assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, f"{path}: {r.text}"
    finally:
        _reset()


def case_creator_reports_multi_select_checks_each_named_creators_agency():
    both = f"{REVENUE}&account_id={IDS['creator_a']},{IDS['creator_b']}"
    cr = _role("role-cr", _only("/analytics/creator-reports"))
    try:
        _roles(OWNER_A, True, {EMP_AB_A: "role-cr"}, cr)
        _roles(OWNER_B, True, {EMP_AB_B: "role-cr"}, cr)
        r = CHATTER_AB.get(both)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        _roles(OWNER_B, True, {EMP_AB_B: "role-none"}, _role("role-none", {}))
        r = CHATTER_AB.get(both)
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, r.text
    finally:
        _reset()


def case_a_creator_named_in_the_header_and_another_in_the_query_are_both_checked():
    a, b = IDS["creator_a"], IDS["creator_b"]
    cr = _role("role-cr", _only("/analytics/creator-reports"))
    try:
        _roles(OWNER_A, True, {EMP_AB_A: "role-cr"}, cr)
        _roles(OWNER_B, True, {EMP_AB_B: "role-none"}, _role("role-none", {}))
        assert CHATTER_AB.get(f"{REVENUE}&account_id={a}", headers={"X-Account-Id": a}).status_code == 200
        for header, query in ((a, b), (b, a), (a, f"{a},{b}")):
            r = CHATTER_AB.get(f"{REVENUE}&account_id={query}", headers={"X-Account-Id": header})
            assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, f"{header} / {query}: {r.text}"
    finally:
        _reset()


def case_a_repeated_account_id_param_checks_every_creator_it_names():
    a, b = IDS["creator_a"], IDS["creator_b"]
    path = "/admin/stats/sales-records?from=2026-06-10&to=2026-06-11"
    sr = _role("role-sr", _only("/analytics/sales-records"))
    denied = {"detail": "Your role does not allow Sales records"}
    try:
        _roles(OWNER_A, True, {EMP_AB_A: "role-sr"}, sr)
        _roles(OWNER_B, True, {EMP_AB_B: "role-none"}, _role("role-none", {}))
        r = CHATTER_AB.get(f"{path}&account_id={a}")
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        for query in (f"account_id={b}&account_id={a}", f"account_id={a}&account_id={b}"):
            r = CHATTER_AB.get(f"{path}&{query}")
            assert r.status_code == 403 and r.json() == denied, f"{query}: {r.status_code} {r.text}"
    finally:
        _reset()


def case_empty_items_in_a_comma_list_name_no_creator():
    a, b = IDS["creator_a"], IDS["creator_b"]
    assert auth.split_account_ids(f" ,{a}, ,{a},", None, f"{b} ,") == [a, b]
    cr = _role("role-cr", _only("/analytics/creator-reports"))
    try:
        _roles(OWNER_A, True, {EMP_AB_A: "role-cr"}, cr)
        _roles(OWNER_B, True, {EMP_AB_B: "role-none"}, _role("role-none", {}))
        r = CHATTER_AB.get(f"{REVENUE}&account_id=,{a},")
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert r.json() == CHATTER_AB.get(f"{REVENUE}&account_id={a}").json()
        r = CHATTER_AB.get(f"{REVENUE}&account_id=,", headers={"X-Account-Id": " "})
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, r.text
    finally:
        _reset()


def case_an_opt_in_route_naming_several_creators_needs_each_ones_grant():
    a, b = IDS["creator_a"], IDS["creator_b"]
    config = "/admin/autoreply-config?account_id="
    denied = {"detail": "Your role does not allow Auto Post or Auto-reply"}
    try:
        _reset()
        _roles(OWNER_A, True, {EMP_AB_A: "role-ar"}, _role("role-ar", _only("/growth/auto-reply")))
        assert CHATTER_AB.get(f"{config}{a}").status_code == 200
        for named in (f"{a},{b}", f"{b},{a}", f" {a} , {b} ,"):
            r = CHATTER_AB.get(f"{config}{named}")
            assert r.status_code == 403 and r.json() == denied, f"{named}: {r.text}"
        r = CHATTER_AB.get(f"{config}{a}", headers={"X-Account-Id": b})
        assert r.status_code == 403 and r.json() == denied, r.text
    finally:
        _reset()


def case_unmapped_routes_pass_for_a_chatter_granted_nothing():
    _roles(OWNER_A, True, {EMP_A: "role-none"}, _role("role-none", {}))
    try:
        for path in ("/chatter/me", "/livez", "/admin/settings/applied"):
            r = CHATTER_A.get(path)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
        assert fx.login_chatter("chatter_a").get("/chatter/me").status_code == 200
    finally:
        _reset()


def case_an_unassigned_employee_and_a_stale_role_are_refused_every_mapped_route():
    pro = _role("role-pro", _only(*permissions.PAGE_MAP))
    try:
        fx.store_blob(IDS["agency_a_owner"], "roles", {"enforce": True, "roles": [pro], "assignments": {}})
        r = CHATTER_A.get(REVENUE)
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, r.text
        fx.store_blob(IDS["agency_a_owner"], "roles",
                      {"enforce": True, "roles": [pro], "assignments": {str(EMP_A): "role-gone"}})
        r = CHATTER_A.get(REVENUE)
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, r.text
        assert CHATTER_A.get("/chatter/me").status_code == 200
    finally:
        _reset()


def case_owner_and_master_are_never_refused():
    _roles(OWNER_A, True, {EMP_A: "role-none"}, _role("role-none", {}))
    fx.store_blob(IDS["agency_master"], "roles", {"enforce": True, "roles": [], "assignments": {}})
    try:
        assert OWNER_A.get(REVENUE + f"&account_id={IDS['creator_a']}").status_code == 200
        assert OWNER_A.get(REVENUE).status_code == 200
        assert MASTER.get(REVENUE).status_code == 200
    finally:
        _reset()
        fx.store_blob(IDS["agency_master"], "roles", {})



def case_two_agency_chatter_is_checked_in_the_agency_of_the_named_creator():
    _roles(OWNER_A, True, {EMP_AB_A: "role-none"}, _role("role-none", {}))
    try:
        r = CHATTER_AB.get(REVENUE + f"&account_id={IDS['creator_a']}")
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, r.text
        r = CHATTER_AB.get(REVENUE, headers={"X-Account-Id": IDS["creator_a"]})
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, r.text
        assert CHATTER_AB.get(REVENUE + f"&account_id={IDS['creator_b']}").status_code == 200
    finally:
        _reset()


def case_two_agency_chatter_naming_no_creator_is_refused_if_any_enforcing_agency_denies():
    dash = _role("role-dash", _only("/"))
    none = _role("role-none", {})
    try:
        _roles(OWNER_A, True, {EMP_AB_A: "role-dash"}, dash)
        _roles(OWNER_B, True, {EMP_AB_B: "role-none"}, none)
        r = CHATTER_AB.get(REVENUE)
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, r.text
        _roles(OWNER_B, False, {EMP_AB_B: "role-none"}, none)
        r = CHATTER_AB.get(REVENUE)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
    finally:
        _reset()



def _blocked(path: str) -> bool:
    return any(path.startswith(p) for p in _CHATTER_BLOCKED_ADMIN_PREFIXES)


def _app_paths() -> list[str]:
    return sorted({route.path for route in server.app.routes})


def case_every_route_is_mapped_owner_only_or_unmapped():
    paths = _app_paths()
    loose = [p for p in paths if not _blocked(p) and permissions.route_pages(p, "GET") is None]
    assert loose == [], f"routes in no table (add them to PAGE_MAP or UNMAPPED): {loose}"
    mapped = {p for _, (_, prefixes) in permissions.PAGE_MAP.items() for p in prefixes}
    both = mapped & set(permissions.UNMAPPED)
    assert both == set(), f"prefixes both mapped and unmapped: {both}"
    dead = sorted(p for p in mapped | set(permissions.UNMAPPED)
                  if not any(path.startswith(p) for path in paths))
    assert dead == [], f"prefixes starting no route: {dead}"


SHARED_ONLY = {
    "/of-manager/messages": "its chats are Messages Pro's",
    "/of-manager/vault": "its vault routes are Vault Pro's and the vault picker's",
    "/of-manager/release-forms": "its tag lists and row hide are New post's and Messages Basic's tag dialog's",
    "/analytics/creator-reports": "its stats are the Dashboard's and Employee reports'",
    "/growth/auto-story": "automation rules and the vault picker are other pages' too",
    "/growth/auto-mass": "its rules, run log, OF lists and vault picker are Auto Post's too",
    "/growth/auto-reply": "its autoreply config and OF lists are Auto Post's and Messages Pro's too",
    "/growth/get-to-know-fans": "its account config (Model info) is Messages Pro's and Auto Post's too",
    "/growth/gen-info": "its automation rules and enqueue routes are Auto Post's too",
    "/employees": "its writes are owner-only; it reads vault lists for folder access",
    "/share-for-share/settings": "its S4S profiles and the rail's requests are the other S4S pages' too",
    "/of-manager/collections": "its lists, labels, fans and user lookups are other pages' too; bookmarks are Bookmarks'",
}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def _routes_by_pages() -> dict[str, list[tuple[str, str, tuple[str, ...]]]]:
    out: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {h: [] for h in permissions.PAGE_MAP}
    for route in server.app.routes:
        methods = sorted(getattr(route, "methods", None) or [])
        if not methods or _blocked(route.path):
            continue
        pages = permissions.route_pages(route.path, methods[0]) or ()
        for page in pages:
            out[page].append((methods[0], _concrete(route.path), pages))
    return out


def case_a_chatter_lacking_only_a_page_gets_403_on_one_of_its_routes():
    by_page = _routes_by_pages()
    shared_only = {h for h, rows in by_page.items() if rows and all(len(p) > 1 for *_, p in rows)}
    assert shared_only == set(SHARED_ONLY), f"pages with no route of their own: {sorted(shared_only)}"
    assert by_page["/creators/proxy"] == [] and permissions.PAGE_MAP["/creators/proxy"][1] == ()
    failures = []

    def _loop(fake):
        for page, rows in by_page.items():
            if not rows:
                continue
            fewest = min(len(p) for *_, p in rows)
            denied = next(p for *_, p in rows if len(p) == fewest)
            _roles(OWNER_A, True, {EMP_A: "role-most"}, _role("role-most", _all_but(*denied)))
            want = {"detail": permissions.denied_detail(denied) if set(denied) <= permissions.OPT_IN_PAGES
                    else f"Your role does not allow {permissions.PAGE_MAP[denied[0]][0]}"}
            for method, path, pages in rows:
                if pages != denied:
                    continue
                r = CHATTER_A.request(method, path)
                if r.status_code == 403 and r.json() == want:
                    break
            else:
                failures.append(page)
        assert fake.calls == [], f"a handler ran: {fake.calls}"
    try:
        _with_fake_of(_loop)
    finally:
        _reset()
    assert failures == [], f"no 403 for: {failures}"


def case_notifications_runs_both_searches_and_a_role_with_none_of_their_pages_is_refused():
    searches = ("/api/of/v2/users/search?q=synth&limit=5", "/api/of/v2/posts/search?query=synth&limit=5")
    for path in searches:
        assert "/of-manager/notifications" in permissions.route_pages(path.split("?")[0], "GET"), path
    try:
        _roles(OWNER_A, True, {EMP_A: "role-notifications"}, _role("role-notifications", _only("/of-manager/notifications")))

        def _granted(fake):
            for path in searches:
                r = CHATTER_A.get(path)
                assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
            assert fake.calls == ["search_users", "search_posts"], fake.calls
        _with_fake_of(_granted)
        _roles(OWNER_A, True, {EMP_A: "role-other"},
               _role("role-other", _all_but("/of-manager/home", "/of-manager/new-post", "/of-manager/notifications",
                                         "/of-manager/streaming")))

        def _refused(fake):
            for path, page in zip(searches, ("Home", "Go live")):
                r = CHATTER_A.get(path)
                assert r.status_code == 403 and r.json() == {"detail": f"Your role does not allow {page}"}, (
                    f"{path}: {r.status_code} {r.text}")
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)
    finally:
        _reset()


def case_the_strips_streams_are_homes_and_a_highlights_stories_my_profiles():
    feed, highlight = "/api/of/v2/streams/feed", "/api/of/v2/stories/highlights/1195022"
    assert permissions.route_pages(feed, "GET") == ("/of-manager/home",)
    assert permissions.route_pages(highlight, "GET") == ("/of-manager/profile",)
    assert "/of-manager/streaming" in permissions.route_pages("/api/of/v2/streams", "GET")
    try:
        for path, page, other in ((feed, "/of-manager/home", "/of-manager/streaming"),
                                  (highlight, "/of-manager/profile", "/of-manager/home")):
            _roles(OWNER_A, True, {EMP_A: "role-page"}, _role("role-page", _only(page)))

            def _granted(fake, path=path):
                r = CHATTER_A.get(path)
                assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
                assert len(fake.calls) == 1, fake.calls
            _with_fake_of(_granted)
            _roles(OWNER_A, True, {EMP_A: "role-other"}, _role("role-other", _only(other)))

            def _refused(fake, path=path, page=page):
                r = CHATTER_A.get(path)
                want = {"detail": f"Your role does not allow {permissions.PAGE_MAP[page][0]}"}
                assert r.status_code == 403 and r.json() == want, f"{path}: {r.status_code} {r.text}"
                assert fake.calls == [], fake.calls
            _with_fake_of(_refused)
    finally:
        _reset()


def case_a_growth_link_page_alone_reads_the_fan_lists_its_list_select_offers():
    try:
        for page in ("/growth/free-trial-links", "/growth/tracking-links", "/growth/profile-promotion"):
            _roles(OWNER_A, True, {EMP_A: "role-page"}, _role("role-page", _only(page)))

            def _read(fake, page=page):
                r = CHATTER_A.get("/api/of/v2/lists?limit=50")
                assert r.status_code == 200, f"{page}: {r.status_code} {r.text}"
                assert fake.calls == ["get_lists"], fake.calls
            _with_fake_of(_read)
    finally:
        _reset()


def case_a_page_added_after_a_role_was_saved_is_denied_for_that_role():
    saved = _all_but("/growth/tracking-links")
    del saved["/growth/tracking-links"]
    _roles(OWNER_A, True, {EMP_A: "role-saved"}, _role("role-saved", saved))
    try:
        assert CHATTER_A.get(REVENUE).status_code == 200
        r = CHATTER_A.get(f"/admin/tracking-links?account_id={IDS['creator_a']}")
        assert r.status_code == 403 and r.json() == {
            "detail": "Your role does not allow Tracking links"}, r.text
    finally:
        _reset()


def case_a_smart_messages_only_chatter_loads_and_saves_the_nudge_config_and_a_role_without_it_is_refused():
    read = f"/admin/nudge-config?account_id={IDS['creator_a']}"
    save = {"account_id": IDS["creator_a"], "config": {"enabled": False}}
    denied = {"detail": "Your role does not allow Smart Messages"}

    def _check(fake):
        _roles(OWNER_A, True, {EMP_A: "role-sm"}, _role("role-sm", _only("/growth/smart-messages")))
        r = CHATTER_A.get(read)
        assert r.status_code == 200, f"GET: {r.status_code} {r.text}"
        r = CHATTER_A.put("/admin/nudge-config", json=save)
        assert r.status_code == 200 and r.json()["config"] == {"enabled": False}, f"PUT: {r.status_code} {r.text}"
        _roles(OWNER_A, True, {EMP_A: "role-none"},
               _role("role-none", _all_but("/growth/smart-messages", "/growth/auto-post")))
        for r in (CHATTER_A.get(read), CHATTER_A.put("/admin/nudge-config", json=save)):
            assert r.status_code == 403 and r.json() == denied, f"{r.status_code} {r.text}"
        assert fake.calls == []
    try:
        _with_fake_of(_check)
    finally:
        _reset()


def case_nudge_config_bulk_checks_the_page_for_every_named_creator():
    q = f"?account_id={IDS['creator_a']}"
    body = {"account_ids": [IDS["creator_a"], IDS["creator_b"]], "config": {"enabled": False}}
    read_b = f"/admin/nudge-config?account_id={IDS['creator_b']}"

    def _check(fake):
        _roles(OWNER_A, True, {EMP_AB_A: "role-sm"}, _role("role-sm", _only("/growth/smart-messages")))
        before = OWNER_B.get(read_b).json()["config"]
        _roles(OWNER_B, True, {EMP_AB_B: "role-none"},
               _role("role-none", _all_but("/growth/smart-messages", "/growth/auto-post")))
        r = CHATTER_AB.put(f"/admin/nudge-config/bulk{q}", json=body)
        assert r.status_code == 403, f"{r.status_code} {r.text}"
        assert OWNER_B.get(read_b).json()["config"] == before, "refused: Agency B's Creator untouched"
        r = CHATTER_AB.put(f"/admin/nudge-config/bulk{q}", json={**body, "account_ids": [IDS["creator_a"]]})
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        _reset()
        _roles(OWNER_A, True, {EMP_AB_A: "role-sm"}, _role("role-sm", _only("/growth/smart-messages")))
        r = CHATTER_AB.put(f"/admin/nudge-config/bulk{q}", json=body)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert fake.calls == []
    try:
        _with_fake_of(_check)
    finally:
        _reset()


def case_a_smart_messages_only_chatter_loads_and_saves_the_purchase_followup_and_a_role_without_it_is_refused():
    read = f"/admin/purchase-followup-config?account_id={IDS['creator_a']}"
    save = {"account_id": IDS["creator_a"], "config": {"enabled": False, "text": "thanks"}}
    denied = {"detail": "Your role does not allow Smart Messages"}

    def _check(fake):
        _roles(OWNER_A, True, {EMP_A: "role-sm"}, _role("role-sm", _only("/growth/smart-messages")))
        r = CHATTER_A.get(read)
        assert r.status_code == 200 and r.json()["config"]["enabled"] is False, f"GET: {r.status_code} {r.text}"
        r = CHATTER_A.put("/admin/purchase-followup-config", json=save)
        assert r.status_code == 200 and r.json()["config"] == {
            "enabled": False, "text": "thanks", "media_ids": [], "price_cents": 0,
            "frequency": "every", "starts_at": None, "ends_at": None,
            "unsend_minutes": 0, "delay_range": [1, 3]}, f"PUT: {r.status_code} {r.text}"
        on = {**save, "config": {"enabled": True, "text": "thanks"}}
        r = CHATTER_A.put("/admin/purchase-followup-config", json=on)
        assert r.status_code == 403, f"a chatter switched it on: {r.status_code} {r.text}"
        r = OWNER_A.put("/admin/purchase-followup-config", json=on)
        assert r.status_code == 200 and r.json()["config"]["enabled"] is True, f"owner: {r.status_code} {r.text}"
        r = CHATTER_A.put("/admin/purchase-followup-config", json=save)
        assert r.status_code == 200 and r.json()["config"]["enabled"] is False, f"off: {r.status_code} {r.text}"
        _roles(OWNER_A, True, {EMP_A: "role-none"}, _role("role-none", _all_but("/growth/smart-messages")))
        for r in (CHATTER_A.get(read), CHATTER_A.put("/admin/purchase-followup-config", json=save)):
            assert r.status_code == 403 and r.json() == denied, f"{r.status_code} {r.text}"
        assert fake.calls == []
    try:
        _with_fake_of(_check)
    finally:
        _reset()


def case_a_smart_messages_only_chatter_loads_and_saves_the_welcome_slot_of_its_own_creator_only():
    own = {"X-Account-Id": IDS["creator_a"]}
    routes = (
        ("GET", "/api/of/v2/messages/templates", None),
        ("GET", "/api/of/v2/users/me/settings?refresh=true", None),
        ("PATCH", "/api/of/v2/users/me/reply-on-subscribe", {"enabled": False}),
    )
    for method, url, _ in routes:
        pages = permissions.route_pages(url.split("?")[0], method)
        assert "/growth/smart-messages" in pages and "/growth/scripts" in pages, f"{url}: {pages}"

    def _check(fake):
        _roles(OWNER_A, True, {EMP_A: "role-sm"}, _role("role-sm", _only("/growth/smart-messages")))
        for method, path, body in routes:
            r = CHATTER_A.request(method, path, headers=own, json=body)
            assert r.status_code == 200, f"{method} {path}: {r.status_code} {r.text}"
        assert fake.calls == ["message_templates", "my_settings", "set_reply_on_subscribe"], fake.calls
        for method, path, body in routes:
            r = CHATTER_A.request(method, path, headers={"X-Account-Id": IDS["creator_b"]}, json=body)
            assert r.status_code == 403, f"{method} {path}: {r.status_code} {r.text}"
        assert len(fake.calls) == 3, fake.calls
    original = server.account_registry.get_account
    fixture_creators = {IDS["creator_a"], IDS["creator_b"]}
    server.account_registry.get_account = lambda aid: {"id": aid} if aid in fixture_creators else original(aid)
    try:
        _with_fake_of(_check)
    finally:
        server.account_registry.get_account = original
        _reset()



ACTIONS_TS = NAV.parent / "permissionActions.ts"
UNSEND = "/api/of/v2/messages/5"
SALES = "/admin/stats/sales-records?from=2026-06-10&to=2026-06-11"


def case_a_denied_action_is_refused_by_name_and_the_pages_other_routes_stay_open():
    role = _role("role-basic", {**_only("/of-manager/messages"), "/of-manager/messages#unsend": False})
    _roles(OWNER_A, True, {EMP_A: "role-basic"}, role)

    def _check(fake):
        r = CHATTER_A.delete(UNSEND)
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Unsend messages"}, r.text
        assert fake.calls == []
        r = CHATTER_A.delete("/api/of/v2/chats/7", headers={"X-Account-Id": IDS["creator_a"]})
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert fake.calls == ["delete_chat"]
        assert CHATTER_A.get("/api/of/v2/chats").status_code != 403
    original = server.account_registry.get_account
    server.account_registry.get_account = lambda aid: {"id": aid} if aid == IDS["creator_a"] else original(aid)
    try:
        _with_fake_of(_check)
    finally:
        server.account_registry.get_account = original
        _reset()


def case_a_missing_or_true_action_key_keeps_the_page_grant_and_a_page_not_granted_still_refuses():
    def _check(fake):
        for stored in ({}, {"/of-manager/messages#unsend": True}):
            role = _role("role-basic", {**_only("/of-manager/messages"), **stored})
            _roles(OWNER_A, True, {EMP_A: "role-basic"}, role)
            r = CHATTER_A.delete(UNSEND)
            assert r.status_code == 200, f"{stored}: {r.status_code} {r.text}"
        assert fake.calls == ["unsend_message"] * 2
        _roles(OWNER_A, True, {EMP_A: "role-x"}, _role("role-x", {
            "/": True, "/of-manager/messages": False, "/of-manager/messages#unsend": True}))
        r = CHATTER_A.delete(UNSEND)
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Messages Basic"}, r.text
    try:
        _with_fake_of(_check)
    finally:
        _reset()


def case_an_action_denied_under_any_page_is_refused_on_every_page_serving_its_route():
    assert permissions.route_pages(UNSEND, "DELETE") == ("/of-manager/messages", "/messages-pro")
    both = _only("/of-manager/messages", "/messages-pro")
    refused = {"detail": "Your role does not allow Unsend messages"}

    def _check(fake):
        for stored in ({**both, "/of-manager/messages#unsend": False, "/messages-pro#unsend": True},
                       {**both, "/messages-pro#unsend": False},
                       {**_only("/messages-pro"), "/of-manager/messages#unsend": False}):
            _roles(OWNER_A, True, {EMP_A: "role-two"}, _role("role-two", stored))
            r = CHATTER_A.delete(UNSEND)
            assert r.status_code == 403 and r.json() == refused, f"{stored}: {r.text}"
        _roles(OWNER_A, True, {EMP_A: "role-two"}, _role("role-two", both))
        assert CHATTER_A.delete(UNSEND).status_code == 200
        assert fake.calls == ["unsend_message"]
    try:
        _with_fake_of(_check)
    finally:
        _reset()


def case_a_denied_mass_message_refuses_starting_or_resuming_a_priority_mass_run():
    role = _role("role-sm", {**_only("/growth/smart-messages"), "/growth/smart-messages#mass-message": False})
    _roles(OWNER_A, True, {EMP_A: "role-sm"}, role)
    refused = {"detail": "Your role does not allow Send or unsend mass messages"}
    try:
        for path in ("/admin/priority-mass/runs", "/admin/priority-mass/runs/9/resume"):
            r = CHATTER_A.post(path, json={})
            assert r.status_code == 403 and r.json() == refused, f"{path}: {r.status_code} {r.text}"
        assert CHATTER_A.post("/admin/priority-mass/runs/9/cancel").status_code != 403
        assert CHATTER_A.get(f"/admin/priority-mass/runs?account_id={IDS['creator_a']}").status_code != 403
    finally:
        _reset()


def case_an_export_action_refuses_the_csv_form_only():
    role = _role("role-sr", {**_only("/analytics/sales-records"), "/analytics/sales-records#export": False})
    _roles(OWNER_A, True, {EMP_A: "role-sr"}, role)
    try:
        r = CHATTER_A.get(f"{SALES}&format=csv")
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Export CSV"}, r.text
        assert CHATTER_A.get(SALES).status_code == 200
        assert CHATTER_A.get(f"{SALES}&format=json").status_code == 200
        assert CHATTER_A.get(f"{SALES}&format=CSV").status_code == 422
    finally:
        _reset()


def case_the_reports_excel_export_is_the_export_action_of_creator_and_employee_reports():
    xlsx, body = "/admin/stats/xlsx", {"rows": [["a"]]}
    assert permissions.route_pages(xlsx, "POST") == ("/analytics/creator-reports", "/analytics/employee-reports")
    try:
        for page in ("/analytics/creator-reports", "/analytics/employee-reports"):
            _roles(OWNER_A, True, {EMP_A: "role-rep"}, _role("role-rep", _only(page)))
            assert CHATTER_A.post(xlsx, json=body).status_code == 200, page
            _roles(OWNER_A, True, {EMP_A: "role-rep"}, _role("role-rep", {**_only(page), f"{page}#export": False}))
            r = CHATTER_A.post(xlsx, json=body)
            assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Export CSV"}, r.text
        _roles(OWNER_A, True, {EMP_A: "role-rep"}, _role("role-rep", _only("/analytics/fan-reports")))
        assert CHATTER_A.post(xlsx, json=body).status_code == 403
    finally:
        _reset()


def case_every_route_that_can_answer_csv_is_the_export_action():
    no_pattern = {"/api/of/v2/users/{user_id}/posts": "OF's own feed format (`infinite`), passed through"}
    csv_routes = []
    for r in server.app.routes:
        for q in getattr(getattr(r, "dependant", None), "query_params", ()):
            if q.alias != "format":
                continue
            pats = [m.pattern for m in q.field_info.metadata if getattr(m, "pattern", None)]
            if not pats:
                assert r.path in no_pattern, f"{r.path}: a format param with no pattern"
            elif any(re.fullmatch(pat, "csv") for pat in pats):
                assert all(not re.fullmatch(pat, "CSV") for pat in pats), r.path
                csv_routes.append(r.path)
                for m in r.methods:
                    assert permissions.route_action(m, r.path, {"format": "csv"}) == "export", f"{m} {r.path}"
    assert sorted(csv_routes) == ["/admin/paid-messages", "/admin/stats/fan-report", "/admin/stats/sales-records",
                                  "/admin/tips-list", "/admin/top-tippers"]


def case_a_method_aware_action_refuses_shift_writes_and_keeps_the_schedule_readable():
    role = _role("role-sh", {**_only("/employees/shifts"), "/employees/shifts#edit-shifts": False})
    _roles(OWNER_A, True, {EMP_A: "role-sh"}, role)
    denied = {"detail": "Your role does not allow Create, edit or cancel shifts"}
    try:
        for method, path in (("POST", "/admin/shifts"), ("PATCH", "/admin/shifts/1"), ("POST", "/admin/shifts/1/cancel")):
            r = CHATTER_A.request(method, path, json={})
            assert r.status_code == 403 and r.json() == denied, f"{method} {path}: {r.status_code} {r.text}"
        for method, path in (("GET", "/admin/shifts?from=2026-06-08T00:00:00Z&to=2026-06-15T00:00:00Z"),
                             ("PATCH", "/admin/shifts/clock-events/1")):
            r = CHATTER_A.request(method, path, json={} if method == "PATCH" else None)
            assert "Your role does not allow" not in r.text, f"{method} {path}: {r.status_code} {r.text}"
    finally:
        _reset()


def case_owners_and_enforcement_off_ignore_a_denied_action():
    role = _role("role-sr", {**_only("/analytics/sales-records"), "/analytics/sales-records#export": False})
    try:
        _roles(OWNER_A, False, {EMP_A: "role-sr"}, role)
        assert CHATTER_A.get(f"{SALES}&format=csv").status_code == 200
        _roles(OWNER_A, True, {EMP_A: "role-sr"}, role)
        assert OWNER_A.get(f"{SALES}&format=csv").status_code == 200
        _roles(OWNER_A, True, {EMP_A: "admin"})
        assert CHATTER_A.get(f"{SALES}&format=csv").status_code == 200
    finally:
        _reset()


def case_the_applied_read_lists_denied_actions_and_no_action_key_as_a_page():
    role = _role("role-pro", {**_only("/messages-pro"), "/messages-pro#export": False, "/messages-pro#unsend": True})
    _roles(OWNER_A, True, {EMP_A: "role-pro"}, role)
    try:
        perms = CHATTER_A.get("/admin/settings/applied").json()["permissions"]
        assert perms["pages"] == ["/messages-pro"], perms
        assert perms["denied_actions"] == ["/messages-pro#export"], perms
        assert OWNER_A.get("/admin/settings/applied").json()["permissions"]["denied_actions"] == []
    finally:
        _reset()


def case_every_action_matches_a_route_a_chatter_reaches_and_no_opt_in_only_route():
    routes = [(m, _concrete(r.path)) for r in server.app.routes for m in (getattr(r, "methods", None) or ())]
    for action, (label, patterns) in permissions.ACTIONS.items():
        for pattern in patterns:
            method, target = pattern.split(" ", 1)
            path = target.split("?")[0].replace("*", "1")
            assert (method, path) in routes, f"{pattern}: no such route"
            assert permissions.route_action(method, path, {"format": "csv"}) == action, pattern
            pages = permissions.route_pages(path, method)
            assert pages and not set(pages) <= permissions.OPT_IN_PAGES, f"{pattern}: {pages}"
    assert len(permissions.ACTION_KEYS) == 43


def case_each_actions_alternate_routes_map_to_it():
    for method, path, action in (
            ("PUT", "/api/of/v2/schedules/9/publish", "mass-message"),
            ("POST", "/api/of/v2/messages/queue", "mass-message"),
            ("POST", "/admin/priority-mass/runs", "mass-message"),
            ("POST", "/admin/priority-mass/runs/9/resume", "mass-message"),
            ("POST", "/admin/priority-mass/runs/9/cancel", None),
            ("DELETE", "/api/of/v2/campaigns/9", "delete-link"),
            ("DELETE", "/api/of/v2/trials/9", "delete-link"),
            ("DELETE", "/admin/promotions/9", "delete-link"),
            ("DELETE", "/api/of/v2/promotions/9", "delete-link"),
            ("POST", "/api/of/v2/promotions/9/finish", "delete-link"),
            ("DELETE", "/api/of/v2/messages/9", "unsend"),
            ("GET", "/admin/stats/fan-report", None),
            ("POST", "/api/of/v2/chats/9/messages", None),
            ("POST", "/api/of/v2/chats/9/messages/scheduled", None),
            ("POST", "/api/of/v2/scheduled-sends", None),
            ("POST", "/admin/mass-messages/refresh", None),
            ("POST", "/admin/vault/sends", None)):
        assert permissions.route_action(method, path) == action, f"{method} {path}"
    assert permissions.route_action("GET", "/admin/stats/fan-report", {"format": "csv"}) == "export"


_NOT_ACTION_DELETES: dict[str, str] = {
    "/admin/do-not-mass": "takes a fan off the do-not-mass list",
    "/admin/automation-rules/{rule_id}": "an automation's own rule, governed by its page",
    "/admin/funnels/{funnel_id}": "an automation's own funnel, governed by its page",
    "/admin/funnels/{funnel_id}/media/{account_id}": "a funnel's media pick",
    "/admin/s4s/blocks/{profile_id}": "unblocks an S4S profile, undoing a block",
    "/admin/s4s/profiles/{account_id}/posts/{post_id}": "an S4S profile's relay-side post entry",
    "/admin/vault-ai/category-icons/{category}": "resets a standard vault category thumbnail to its default",
    "/admin/smart-lists/{list_id}": "a whole Smart list, a saved fan filter: the fans and chats stay",
    "/api/of/v2/lists/{list_id}": "a whole OF fan list (collection): the fans and chats stay; Infloww has no such action",
    "/api/of/v2/lists/{list_id}/users/{user_id}": "takes a fan out of a list",
    "/api/of/v2/lists/{list_id}/users": "takes fans out of a list",
    "/api/of/v2/messages/{message_id}/bookmark": "undoes a bookmark",
    "/api/of/v2/messages/{message_id}/like": "undoes a like",
    "/api/of/v2/messages/{message_id}/pin/user/{user_id}": "undoes a pin",
    "/api/of/v2/chats/{chat_id}/messages/pin": "undoes a pin",
    "/api/of/v2/chats/{chat_id}/mark-as-read": "marks a chat unread",
    "/api/of/v2/chats/{chat_id}/mute": "unmutes a chat",
    "/api/of/v2/chats/{chat_id}/hide": "unhides a chat",
    "/api/of/v2/subscriptions/bundles/{bundle_id}": "a subscription bundle, the OF settings page's pricing",
    "/api/of/v2/scheduled-sends/{job_id}": "cancels a pending 1:1 send before it fires",
    "/api/of/v2/posts/{post_id}/like": "undoes a like",
    "/api/of/v2/posts/{post_id}/pin": "unpins a post",
}
_NOT_ACTION_DELETES["/api/of/v2/users/social/buttons/{button_id}"] = "a profile's social media button, the OF settings page's"
_NOT_ACTION_DELETES["/api/of/v2/users/links/{link_id}"] = "a profile's Things I Like link, the OF settings page's"


def case_every_delete_a_chatter_reaches_is_an_action_or_listed_as_none():
    deletes = {r.path for r in server.app.routes if "DELETE" in (getattr(r, "methods", None) or ())
               and permissions.route_pages(_concrete(r.path), "DELETE")}
    unsorted = {p for p in deletes if permissions.route_action("DELETE", _concrete(p)) is None} - set(_NOT_ACTION_DELETES)
    assert not unsorted, unsorted
    stale = {p for p in _NOT_ACTION_DELETES if p not in deletes or permissions.route_action("DELETE", _concrete(p))}
    assert not stale, stale


def case_the_editors_action_list_is_the_relays():
    ts = dict(re.findall(r'^\s*"([^"]+#[^"]+)":\s*"([^"]+)",', ACTIONS_TS.read_text(), re.M))
    assert ts == permissions.ACTION_KEYS, {k: (ts.get(k), permissions.ACTION_KEYS.get(k))
                                           for k in set(ts) ^ set(permissions.ACTION_KEYS)}
    assert list(ts) == list(permissions.ACTION_KEYS)



SETTINGS = "/of-manager/settings"
LOCKOUT_KEY = f"{SETTINGS}#account-lockout"
LOCKOUT_REFUSED = {"detail": "Your role does not allow Block countries or IPs, close sessions, reset the stream key"}
LOCKOUT_ROUTES: list[tuple[str, str, dict | None]] = []
LOCKOUT_ROUTES += [("DELETE", "/api/of/v2/sessions", None)]
LOCKOUT_ROUTES += [
    ("PUT", "/api/of/v2/users/me/settings/security/blocked-countries", {"blockedCountries": ["AQ"], "blockedStates": []}),
    ("PUT", "/api/of/v2/users/me/settings/security/blocked-ips", {"blockedIps": ["192.0.2.1"]}),
]
LOCKOUT_ROUTES += [("DELETE", "/api/of/v2/streams/obs/key?type=obs_agora", None)]


def _lockout_route_follows_the_house_rule(method: str, path: str, body: dict | None) -> None:
    def call():
        return CHATTER_A.request(method, path, json=body, headers={"X-Account-Id": IDS["creator_a"]})

    def _check(fake):
        denies = _role("role-set", {**_only(SETTINGS), LOCKOUT_KEY: False})
        _roles(OWNER_A, True, {EMP_A: "role-set"}, denies)
        r = call()
        assert r.status_code == 403 and r.json() == LOCKOUT_REFUSED, f"{method} {path}: {r.status_code} {r.text}"
        assert fake.calls == [], fake.calls
        _roles(OWNER_A, True, {EMP_A: "role-set"}, _role("role-set", _all_but(SETTINGS)))
        r = call()
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow OF settings"}, \
            f"{method} {path} no OF settings: {r.status_code} {r.text}"
        assert fake.calls == [], fake.calls
        _roles(OWNER_A, False, {EMP_A: "role-set"}, denies)
        r = call()
        assert r.status_code == 200, f"{method} {path} enforcement off: {r.status_code} {r.text}"
        for stored in ({}, {LOCKOUT_KEY: True}):
            _roles(OWNER_A, True, {EMP_A: "role-set"}, _role("role-set", {**_only(SETTINGS), **stored}))
            r = call()
            assert r.status_code == 200, f"{method} {path} {stored or 'key unset'}: {r.status_code} {r.text}"
    original = server.account_registry.get_account
    server.account_registry.get_account = lambda aid: {"id": aid} if aid == IDS["creator_a"] else original(aid)
    try:
        _with_fake_of(_check)
    finally:
        server.account_registry.get_account = original
        _reset()


def case_every_lockout_route_follows_the_house_rule():
    assert LOCKOUT_KEY in permissions.ACTION_KEYS
    for method, path, body in LOCKOUT_ROUTES:
        assert permissions.route_pages(path, method) == (SETTINGS,), f"{method} {path}"
        _lockout_route_follows_the_house_rule(method, path, body)


def case_a_planted_lockout_route_is_refused_only_for_a_role_storing_the_key_false_under_enforcement():
    method, path = "PUT", "/api/of/v2/users/me/settings/oi-lockout-plant"

    async def _plant():
        return {"ok": True}

    patterns = permissions._ACTION_PATTERNS
    permissions._ACTION_PATTERNS = [("account-lockout", permissions._pattern(f"{method} {path}")), *patterns]
    server.app.router.add_api_route(path, _plant, methods=[method])
    planted = server.app.router.routes.pop()
    server.app.router.routes.insert(0, planted)
    try:
        assert permissions.route_pages(path, method) == (SETTINGS,)
        assert permissions.route_action(method, path) == "account-lockout"
        _lockout_route_follows_the_house_rule(method, path, {"blockedIps": ["192.0.2.1"]})
    finally:
        server.app.router.routes.remove(planted)
        permissions._ACTION_PATTERNS = patterns
    assert permissions.route_action(method, path) is None


BLOCK_FAN_KEY = f"{SETTINGS}#block-fan"


def case_stream_block_routes_are_block_fan_under_of_settings():
    assert BLOCK_FAN_KEY in permissions.ACTION_KEYS
    refused = {"detail": "Your role does not allow Block or restrict fans"}
    rows = [("POST", "/api/of/v2/streams/users/oi_synthetic_fan/block"), ("DELETE", "/api/of/v2/streams/users/7/block")]
    assert permissions.route_pages("/api/of/v2/streams/users/blocked", "GET") == (SETTINGS,)

    def _check(fake):
        for method, path in rows:
            assert permissions.route_pages(path, method) == (SETTINGS,), f"{method} {path}"
            assert permissions.route_action(method, path) == "block-fan", f"{method} {path}"

            def call():
                return CHATTER_A.request(method, path, headers={"X-Account-Id": IDS["creator_a"]})
            sent = list(fake.calls)
            for stored in ({BLOCK_FAN_KEY: False}, {"/of-manager/messages#block-fan": False}):
                _roles(OWNER_A, True, {EMP_A: "role-set"}, _role("role-set", {**_only(SETTINGS, "/of-manager/messages"), **stored}))
                r = call()
                assert r.status_code == 403 and r.json() == refused, f"{method} {path} {stored}: {r.status_code} {r.text}"
            _roles(OWNER_A, True, {EMP_A: "role-set"}, _role("role-set", _all_but(SETTINGS)))
            r = call()
            assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow OF settings"}, r.text
            assert fake.calls == sent, fake.calls
            _roles(OWNER_A, False, {EMP_A: "role-set"}, _role("role-set", {**_only(SETTINGS), BLOCK_FAN_KEY: False}))
            assert call().status_code == 200, f"{method} {path} enforcement off"
            _roles(OWNER_A, True, {EMP_A: "role-set"}, _role("role-set", _only(SETTINGS)))
            assert call().status_code == 200, f"{method} {path} key unset"
        assert fake.calls == ["block_stream_viewer"] * 2 + ["unblock_stream_viewer"] * 2, fake.calls
        head = {"X-Account-Id": IDS["creator_a"]}
        for method, path, body in (("POST", "/api/of/v2/streams/users/fan/block", {"x": 1}),
                                   ("POST", "/api/of/v2/streams/users/" + "a" * 25 + "/block", None),
                                   ("POST", "/api/of/v2/streams/users/a%20b/block", None),
                                   ("DELETE", "/api/of/v2/streams/users/abc/block", None)):
            r = CHATTER_A.request(method, path, json=body, headers=head)
            assert r.status_code == 422, (method, path, r.status_code, r.text)
        assert len(fake.calls) == 4, fake.calls
    original = server.account_registry.get_account
    server.account_registry.get_account = lambda aid: {"id": aid} if aid == IDS["creator_a"] else original(aid)
    try:
        _with_fake_of(_check)
    finally:
        server.account_registry.get_account = original
        _reset()


def case_reset_stream_key_is_account_lockout_and_takes_only_ofs_two_servers():
    path = "/api/of/v2/streams/obs/key"
    assert permissions.route_action("DELETE", path) == "account-lockout"

    def _check(fake):
        _roles(OWNER_A, True, {EMP_A: "role-set"}, _role("role-set", _only(SETTINGS)))
        head = {"X-Account-Id": IDS["creator_a"]}
        for query, body in (("", None), ("?type=mux", None), ("?type=obs_agora", {"type": "obs_agora"})):
            r = CHATTER_A.request("DELETE", path + query, json=body, headers=head)
            assert r.status_code == 422, (query, body, r.status_code, r.text)
        assert fake.calls == [], fake.calls
        r = CHATTER_A.request("DELETE", path + "?type=mux_direct", headers=head)
        assert r.status_code == 200 and fake.calls == ["reset_stream_key"], (r.status_code, r.text, fake.calls)
    original = server.account_registry.get_account
    server.account_registry.get_account = lambda aid: {"id": aid} if aid == IDS["creator_a"] else original(aid)
    try:
        _with_fake_of(_check)
    finally:
        server.account_registry.get_account = original
        _reset()



def case_a_disabled_role_grants_nothing_and_its_employees_keep_it():
    role = _role("role-dash", _only("/"))
    try:
        _roles(OWNER_A, True, {EMP_A: "role-dash"}, {**role, "disabled": True})
        r = CHATTER_A.get(REVENUE)
        assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, r.text
        assert CHATTER_A.get("/admin/settings/applied").json()["permissions"]["pages"] == []
        import settings_api
        blob = {"roles": [{**role, "disabled": True}], "assignments": {str(EMP_A): "role-dash"}}
        assert settings_api._with_roles_for(blob, [EMP_A], "chatter") == (blob, 0)
        _roles(OWNER_A, True, {EMP_A: "role-dash"}, {**role, "disabled": False})
        assert CHATTER_A.get(REVENUE).status_code == 200
        _roles(OWNER_A, True, {EMP_A: "chatter"}, {**_role("chatter", _only("/")), "disabled": True})
        assert CHATTER_A.get(REVENUE).status_code == 200
    finally:
        _reset()



_LINK = re.compile(r'\{\s*label:\s*"([^"]+)",\s*href:\s*"([^"]+)"([^}]*)\}')


def _nav_pages(nav_ts: str) -> dict[str, str]:
    sidebar = nav_ts.split("export const ONLYFANS_NAV:", 1)[1].split("export const FANSLY_NAV", 1)[0]
    return {href: label for label, href, rest in _LINK.findall(sidebar)
            if not re.search(r"\blegacy:\s*true\b|\bpermission:", rest)}


def _drift(nav_ts: str) -> list[str]:
    nav = _nav_pages(nav_ts)
    mapped = {href: label for href, (label, _) in permissions.PAGE_MAP.items()}
    return ([f"nav page {h} has no page-map entry" for h in nav if h not in mapped]
            + [f"page-map entry {h} is not a nav page" for h in mapped if h not in nav]
            + [f"{h}: nav says {nav[h]!r}, map says {mapped[h]!r}"
               for h in nav if h in mapped and nav[h] != mapped[h]])


def case_the_page_map_follows_the_nav():
    nav_ts = _nav_text()
    assert len(_nav_pages(nav_ts)) == 49
    assert _drift(nav_ts) == []


def case_the_drift_check_fails_on_a_nav_page_with_no_map_entry():
    nav_ts = _nav_text().replace(
        '{ label: "Dashboard", href: "/", icon: Grid01Line },',
        '{ label: "Dashboard", href: "/", icon: Grid01Line },\n'
        '  { label: "Fixture page", href: "/fixture-page" },', 1)
    assert _drift(nav_ts) == ["nav page /fixture-page has no page-map entry"]
    legacy = nav_ts.replace('href: "/fixture-page" }', 'href: "/fixture-page", legacy: true }')
    assert _drift(legacy) == []


def case_the_drift_check_skips_a_link_that_answers_to_another_page():
    """As nav.ts `isPermissionPage`: a `permission:` link is no page of its own, top-level or a
    group's child alike."""
    nav_ts = _nav_text()
    nav_ts = nav_ts.replace(
        '{ label: "Dashboard", href: "/", icon: Grid01Line },',
        '{ label: "Dashboard", href: "/", icon: Grid01Line },\n'
        '  { label: "Fixture top", href: "/fixture-top", permission: "/messages-pro" },', 1).replace(
        '{ label: "Smart Messages", href: "/growth/smart-messages" },',
        '{ label: "Smart Messages", href: "/growth/smart-messages" },\n'
        '      { label: "Fixture child", href: "/growth/fixture-child", permission: "/messages-pro" },', 1)
    assert "/fixture-top" in nav_ts and "/growth/fixture-child" in nav_ts
    assert _drift(nav_ts) == []



def case_flipping_enforce_leaves_one_actions_row_for_the_put():
    rows = select(func.count()).select_from(Action).where(Action.action == "PUT /admin/settings/roles")
    try:
        for enforce in (True, False):
            before = _db(rows)
            _roles(OWNER_A, enforce, {EMP_A: "role-pro"}, _role("role-pro", _only("/messages-pro")))
            assert _db(rows) == before + 1
    finally:
        _reset()


def case_the_applied_read_reports_enforced_and_the_granted_pages():
    _roles(OWNER_A, True, {EMP_A: "role-pro"}, _role("role-pro", _only("/messages-pro", "/")))
    try:
        r = CHATTER_A.get("/admin/settings/applied")
        assert r.status_code == 200, r.text
        assert r.json()["permissions"] == {"enforced": True, "pages": ["/", "/messages-pro"],
                                           "scope": "self", "opt_in": [], "denied_actions": [],
                                           "denied_cards": []}
        _roles(OWNER_A, True, {EMP_A: "role-pro"}, _role("role-pro", _only("/messages-pro", "/growth/auto-mass")))
        assert CHATTER_A.get("/admin/settings/applied").json()["permissions"]["opt_in"] == ["/growth/auto-mass"]
    finally:
        _reset()



PER_EMPLOYEE = "/admin/stats/per-employee?from=2026-06-10&to=2026-06-11"


def _seed_employee_report() -> None:
    when = datetime(2026, 6, 10, 12, 0)
    path = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions" / \
        "20261027_0100_converters_window.py"
    spec = importlib.util.spec_from_file_location("mig_attr_view", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    async def _seed():
        async with get_session() as s:
            await s.execute(text("DROP VIEW IF EXISTS per_employee_revenue_with_attribution"))
            await s.execute(text(mig._NEW_VIEW_SQL))
            for mid, sender in ((9001, EMP_A), (9002, EMP_A), (9003, EMP_AB_A)):
                s.add(Message(account_id=IDS["creator_a"], fan_id=77, message_id=mid, direction="out",
                              body="x", sent_by_employee_id=sender, created_at=when, ingested_at=when))
            s.add(Transaction(account_id=IDS["creator_a"], fan_id=78, kind="tip", amount_cents=500,
                              currency="USD", occurred_at=when))
            await s.commit()
    asyncio.run(_seed())


_seed_employee_report()


def _report_rows(client) -> dict:
    r = client.get(PER_EMPLOYEE)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    return {row["employee_id"]: row["messages_sent"] for row in r.json()["employees"]}


EVERY_ROW = {EMP_A: 2, EMP_AB_A: 1, None: 0}


def case_per_employee_stats_show_a_self_scope_only_its_own_row():
    try:
        assert _report_rows(CHATTER_A) == EVERY_ROW
        _roles(OWNER_A, True, {EMP_A: "role-rep"},
               _role("role-rep", _only("/analytics/employee-reports"), "self"))
        assert _report_rows(CHATTER_A) == {EMP_A: 2}
        assert _report_rows(OWNER_A) == EVERY_ROW
    finally:
        _reset()


def _members(group_id: int | None, employee_ids: list[int]) -> None:
    r = OWNER_A.put("/admin/employee-groups/members", json={"group_id": group_id, "employee_ids": employee_ids})
    assert r.status_code == 200, r.text


def case_per_employee_stats_under_self_and_subordinates_add_the_groups_below_never_peers():
    def group(name: str, parent_id: int | None) -> int:
        r = OWNER_A.post("/admin/employee-groups", json={"name": name, "parent_id": parent_id})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    lead = group("Fixture RE Lead", None)
    below = group("Fixture RE Below", lead)
    try:
        _members(lead, [EMP_A])
        _members(below, [EMP_AB_A])
        _roles(OWNER_A, True, {EMP_A: "role-rep"},
               _role("role-rep", _only("/analytics/employee-reports"), "subordinates"))
        assert _report_rows(CHATTER_A) == {EMP_A: 2, EMP_AB_A: 1}
        assert _report_rows(OWNER_A) == EVERY_ROW
        assert _report_rows(MASTER) == EVERY_ROW
        _members(lead, [EMP_AB_A])
        assert _report_rows(CHATTER_A) == {EMP_A: 2}
    finally:
        _reset()
        _members(None, [EMP_A, EMP_AB_A])


def case_per_employee_stats_show_every_row_for_all_scope_or_enforcement_off():
    rep = _role("role-rep", _only("/analytics/employee-reports"), "all")
    try:
        _roles(OWNER_A, True, {EMP_A: "role-rep"}, rep)
        assert _report_rows(CHATTER_A) == EVERY_ROW
        _roles(OWNER_A, False, {EMP_A: "role-rep"}, {**rep, "scope": "self"})
        assert _report_rows(CHATTER_A) == EVERY_ROW
    finally:
        _reset()


def case_an_all_scope_chatter_under_enforcement_still_gets_403_from_timesheet_and_clocked_in():
    owner_only = {"detail": "only the agency owner manages the Shift schedule"}
    _roles(OWNER_A, True, {EMP_A: "role-every"},
           _role("role-every", _only(*permissions.PAGE_MAP), "all"))
    try:
        for path in ("/admin/shifts/timesheet?from=2026-06-08T00:00:00Z&to=2026-06-15T00:00:00Z",
                     "/admin/shifts/clocked-in"):
            r = CHATTER_A.get(path)
            assert r.status_code == 403 and r.json() == owner_only, f"{path}: {r.status_code} {r.text}"
            assert OWNER_A.get(path).status_code == 200, path
    finally:
        _reset()



_D = "start=2026-10-01+00%3A00%3A00&end=2026-10-16+23%3A59%3A59"


def _statistics_family(paths: list[str], also: tuple[str, ...] = ()) -> None:
    stats = _role("role-stats", _only("/of-manager/statistics"))
    other = _role("role-other", _all_but("/of-manager/statistics", *also))
    try:
        _roles(OWNER_A, True, {EMP_A: "role-stats"}, stats, other)

        def _granted(fake):
            for path in paths:
                r = CHATTER_A.get(path, headers={"X-Account-Id": IDS["creator_a"]})
                assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
            assert len(fake.calls) == len(paths), fake.calls
        _with_fake_of(_granted)
        _roles(OWNER_A, True, {EMP_A: "role-other"}, stats, other)

        def _refused(fake):
            for path in paths:
                pages = permissions.route_pages(path.split("?")[0], "GET")
                assert "/of-manager/statistics" in pages, (path, pages)
                want = {"detail": f"Your role does not allow {permissions.PAGE_MAP[pages[0]][0]}"}
                r = CHATTER_A.get(path)
                assert r.status_code == 403 and r.json() == want, f"{path}: {r.status_code} {r.text}"
            assert fake.calls == []
        _with_fake_of(_refused)
    finally:
        _reset()


def case_statistics_earnings_posts_and_subscriber_charts_are_statistics_reads():
    _statistics_family([f"/api/of/v2/earnings/chart?{_D}&filter=tips_count,tips_amount",
                        f"/api/of/v2/posts/chart?{_D}&by=views"])
    _statistics_family([f"/api/of/v2/subscriptions/subscribers/chart?{_D}&by=renew"],
                       also=("/", "/analytics/creator-reports"))


def case_statistics_chargebacks_list_is_statistics_and_statements():
    _statistics_family([f"/api/of/v2/payouts/chargebacks?{_D}"], also=("/of-manager/statements",))
    statements = _role("role-statements", _only("/of-manager/statements"))
    _roles(OWNER_A, True, {EMP_A: "role-statements"}, statements)
    try:
        def _read(fake):
            r = CHATTER_A.get(f"/api/of/v2/payouts/chargebacks?{_D}")
            assert r.status_code == 200, f"{r.status_code} {r.text}"
        _with_fake_of(_read)
    finally:
        _reset()


def case_statistics_top_highlights_and_streaks():
    _statistics_family([f"/api/of/v2/users/me/stats/top/{k}?{_D}" for k in ("message", "stream", "story", "fan")]
                       + [f"/api/of/v2/streaks?{_D}", "/api/of/v2/streaks/top",
                          "/api/of/v2/users/me/stats/today-activity"])


def case_statistics_message_tabs_buyers_and_chart():
    _statistics_family(["/api/of/v2/users/me/stats/messages/direct?startDate=2026-10-01+00%3A00%3A00"
                        "&endDate=2026-10-16+23%3A59%3A59&query=synthetic",
                        f"/api/of/v2/messages/queue/chart?{_D}&type=direct",
                        "/api/of/v2/messages/queue/buyers?queue_id=56001"])


def case_statistics_fans_tabs():
    _statistics_family([f"/api/of/v2/subscriptions/subscribers/latest?{_D}&by=new",
                        f"/api/of/v2/subscriptions/subscribers/top?{_D}&by=tips",
                        f"/api/of/v2/fans-activity/list?{_D}&format=hours"])


def case_statistics_stream_and_story_lists():
    _statistics_family([f"/api/of/v2/streams/top?{_D}", f"/api/of/v2/stories/top?{_D}"])


def case_statistics_reach_tables():
    _statistics_family([f"/api/of/v2/promotions/stats?{_D}", f"/api/of/v2/trials/stats?{_D}",
                        f"/api/of/v2/campaigns/stats?{_D}"])


def case_statistics_referred_creators_and_users():
    _statistics_family([f"/api/of/v2/users/me/referrals?{_D}&onlyPerformers=1",
                        f"/api/of/v2/users/me/referrals?{_D}"])


def case_statistics_earnings_list_profile_stats_and_posts_top():
    _statistics_family([f"/api/of/v2/payouts/transactions?startDate=2026-10-01+00%3A00%3A00"
                        f"&marker=1792195199&type=tips&tipsSource=chat"],
                       also=("/of-manager/statements", "/messages-pro"))
    _statistics_family([f"/api/of/v2/users/me/profile/stats?{_D}&by=guests&limit=50&filter=topCountries"])
    _statistics_family([f"/api/of/v2/posts/top?{_D}&by=likes&offset=10"], also=("/analytics/message-dashboard",))


def case_statistics_statements_reach_and_engagement_charts():
    _statistics_family([f"/api/of/v2/payouts/chart?{_D}", f"/api/of/v2/payouts/referrals/chart?{_D}",
                        f"/api/of/v2/promotions/chart?{_D}", f"/api/of/v2/trials/chart?{_D}",
                        f"/api/of/v2/campaigns/chart?{_D}", f"/api/of/v2/stories/chart?{_D}&by=views",
                        f"/api/of/v2/streams/chart?{_D}&by=tips"])
    _statistics_family([f"/api/of/v2/payouts/chargebacks/chart?{_D}"], also=("/of-manager/statements",))


def case_statistics_stream_and_story_viewer_lists():
    _statistics_family(["/api/of/v2/streams/viewers?stream_id=57001&tips_only=1",
                        "/api/of/v2/stories/viewers?story_id=58001"])


def case_statistics_payout_invoice_download():
    class _Pdf:
        ok, status_code, content, headers = True, 200, b"%PDF synthetic", {"content-type": "application/pdf"}

    class _InvoiceOF(_FakeOF):
        def payout_invoice(self, *_a, **_k):
            self.calls.append("payout_invoice")
            return _Pdf()
    path = "/api/of/v2/payouts/download-approved-invoice?invoiceId=4242"
    stats = _role("role-stats", _only("/of-manager/statistics"))
    other = _role("role-other", _all_but("/of-manager/statistics"))
    original = server._get_client
    fake = _InvoiceOF()
    server._get_client = lambda *_a, **_k: fake
    try:
        _roles(OWNER_A, True, {EMP_A: "role-stats"}, stats, other)
        r = CHATTER_A.get(path)
        assert r.status_code == 200 and r.content == b"%PDF synthetic", f"{r.status_code} {r.text}"
        _roles(OWNER_A, True, {EMP_A: "role-other"}, stats, other)
        r = CHATTER_A.get(path)
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Statistics"}, r.text
        assert fake.calls == ["payout_invoice"], fake.calls
    finally:
        server._get_client = original
        _reset()




def case_statistics_item_stats_and_user_lists():
    _statistics_family(["/api/of/v2/posts/stats?post_id=59001",
                        "/api/of/v2/posts/buyers?post_id=59001&offset=10", "/api/of/v2/posts/tips?post_id=59001",
                        "/api/of/v2/promotions/claims?promo_id=61001", "/api/of/v2/trials/claims?trial_id=62001",
                        "/api/of/v2/campaigns/claimers?campaign_id=60001&offset=10"])
    _statistics_family(["/api/of/v2/posts/likes?post_id=59001&offset=10"], also=("/of-manager/home", "/of-manager/profile"))



ME = "/api/of/v2/users/me"
ME_WRITES = (("PATCH", ME, {"about": "bio"}),
             ("PATCH", f"{ME}/settings/security", {"showPostsTips": True}),
             ("PUT", f"{ME}/settings/security", {"hasWatermarkPhoto": True}))


def case_users_me_writes_need_of_settings_where_reads_follow_the_map():
    for method, path, _ in ME_WRITES:
        assert permissions.route_pages(path, method) == ("/of-manager/settings",), (method, path)
    assert len(permissions.route_pages(ME, "GET")) > 1
    try:
        _roles(OWNER_A, True, {EMP_A: "role-most"}, _role("role-most", _all_but("/of-manager/settings")))

        def _refused(fake):
            for method, path, body in ME_WRITES:
                r = CHATTER_A.request(method, path, json=body)
                assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow OF settings"}, \
                    f"{method} {path}: {r.status_code} {r.text}"
            assert fake.calls == []
            r = CHATTER_A.get(ME)
            assert r.status_code != 403, f"GET {ME}: {r.status_code} {r.text}"
        _with_fake_of(_refused)

        _roles(OWNER_A, True, {EMP_A: "role-settings"}, _role("role-settings", _only("/of-manager/settings")))

        def _allowed(fake):
            for method, path, body in ME_WRITES:
                r = CHATTER_A.request(method, path, json=body)
                assert r.status_code == 200, f"{method} {path}: {r.status_code} {r.text}"
            assert fake.calls == ["update_profile", "patch_security_settings", "put_security_settings"], fake.calls
        resolve, server._resolve_account_id = server._resolve_account_id, lambda _ctx: IDS["creator_a"]
        try:
            _with_fake_of(_allowed)
        finally:
            server._resolve_account_id = resolve
    finally:
        _reset()


PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def case_the_profile_image_upload_needs_of_settings():
    path = f"{ME}/profile-image"
    assert permissions.route_pages(path, "POST") == ("/of-manager/settings",)
    files = {"file": ("cover.png", PNG_1PX, "image/png")}
    try:
        _roles(OWNER_A, True, {EMP_A: "role-most"}, _role("role-most", _all_but("/of-manager/settings")))

        def _refused(fake):
            r = CHATTER_A.post(path, files=files, data={"kind": "header"})
            assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow OF settings"}, r.text
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)

        _roles(OWNER_A, True, {EMP_A: "role-settings"}, _role("role-settings", _only("/of-manager/settings")))

        def _allowed(fake):
            fake.upload_media = lambda *_a, **_k: fake.calls.append("upload_media") or {
                "ready": True, "send_with": [{"processId": "p1", "host": "h", "name": "cover.png"}]}
            r = CHATTER_A.post(path, files=files, data={"kind": "header"})
            assert r.status_code == 200 and r.json()["processId"] == "p1", r.text
            assert fake.calls == ["upload_media"], fake.calls
        resolve, server._resolve_account_id = server._resolve_account_id, lambda _ctx: IDS["creator_a"]
        try:
            _with_fake_of(_allowed)
        finally:
            server._resolve_account_id = resolve
    finally:
        _reset()


def case_social_media_buttons_need_of_settings():
    path = "/api/of/v2/users/social/buttons"
    body = {"socialMedia": "instagram", "label": "IG", "link": "", "username": "alpha"}
    for method, p in (("GET", path), ("PUT", path), ("DELETE", f"{path}/7"), ("GET", "/api/of/v2/init")):
        assert permissions.route_pages(p, method) == ("/of-manager/settings",), (method, p)
    calls = (("get", path, {}, "social_buttons"), ("put", path, {"json": body}, "add_social_button"),
             ("delete", f"{path}/7", {}, "delete_social_button"),
             ("get", "/api/of/v2/init", {}, "social_media_providers"))
    try:
        _roles(OWNER_A, True, {EMP_A: "role-most"}, _role("role-most", _all_but("/of-manager/settings")))

        def _refused(fake):
            for verb, p, kw, _ in calls:
                r = getattr(CHATTER_A, verb)(p, **kw)
                assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow OF settings"}, r.text
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)

        _roles(OWNER_A, True, {EMP_A: "role-settings"}, _role("role-settings", _only("/of-manager/settings")))

        def _allowed(fake):
            for verb, p, kw, _ in calls:
                r = getattr(CHATTER_A, verb)(p, **kw)
                assert r.status_code == 200, (verb, r.status_code, r.text)
            assert fake.calls == [name for *_, name in calls], fake.calls
        resolve, server._resolve_account_id = server._resolve_account_id, lambda _ctx: IDS["creator_a"]
        try:
            _with_fake_of(_allowed)
        finally:
            server._resolve_account_id = resolve
    finally:
        _reset()


def case_things_i_like_links_need_of_settings():
    path = "/api/of/v2/users/links"
    body = {"link": "https://www.youtube.com/watch?v=alpha"}
    for method, p in (("GET", path), ("PUT", path), ("DELETE", f"{path}/7")):
        assert permissions.route_pages(p, method) == ("/of-manager/settings",), (method, p)
    calls = (("get", path, {}, "users_links"), ("put", path, {"json": body}, "add_users_link"),
             ("delete", f"{path}/7", {}, "delete_users_link"))
    try:
        _roles(OWNER_A, True, {EMP_A: "role-most"}, _role("role-most", _all_but("/of-manager/settings")))

        def _refused(fake):
            for verb, p, kw, _ in calls:
                r = getattr(CHATTER_A, verb)(p, **kw)
                assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow OF settings"}, r.text
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)

        _roles(OWNER_A, True, {EMP_A: "role-settings"}, _role("role-settings", _only("/of-manager/settings")))

        def _allowed(fake):
            for verb, p, kw, _ in calls:
                r = getattr(CHATTER_A, verb)(p, **kw)
                assert r.status_code == 200, (verb, r.status_code, r.text)
            assert fake.calls == [name for *_, name in calls], fake.calls
        resolve, server._resolve_account_id = server._resolve_account_id, lambda _ctx: IDS["creator_a"]
        try:
            _with_fake_of(_allowed)
        finally:
            server._resolve_account_id = resolve
    finally:
        _reset()



def case_a_never_stored_or_invalid_switch_reads_on_and_only_false_turns_it_off():
    assert permissions.enforced({}) and permissions.enforced({"enforce": True})
    assert not permissions.enforced({"enforce": False})
    try:
        for blob in ({}, {"enforce": "yes"}, {"assignments": {}}):
            fx.store_blob(IDS["agency_a_owner"], "roles", blob)
            r = CHATTER_A.get(REVENUE)
            assert r.status_code == 403 and r.json() == DENIED_DASHBOARD, f"{blob}: {r.status_code} {r.text}"
            assert OWNER_A.get(REVENUE).status_code == 200, blob
    finally:
        _reset()
    assert CHATTER_A.get(REVENUE).status_code == 200


def case_owner_only_settings_tabs_refuse_a_chatter_by_url_even_one_holding_admin():
    _roles(OWNER_A, True, {EMP_A: "admin"})
    try:
        for tab in ("roles", "time-tracking", "preferences"):
            assert CHATTER_A.get(f"/admin/settings/{tab}").status_code == 401, tab
            r = CHATTER_A.put(f"/admin/settings/{tab}", json={"enforce": False})
            assert r.status_code == 401, f"PUT {tab}: {r.status_code}"
        assert CHATTER_A.get("/admin/employees").status_code == 403
        assert OWNER_A.get("/admin/settings/roles").status_code == 200
    finally:
        _reset()


def case_role_and_agency_reads_share_one_fresh_checkout():
    _roles(OWNER_A, True, {EMP_A: "admin"})
    counts = {"roles": 0, "agency": 0, "mirror": 0}
    agency_queries = []
    originals = (permissions.get_session, agency_ctx.get_session, employees.get_session)
    original_contexts = permissions.agency_contexts

    def counted(name, original):
        @contextlib.asynccontextmanager
        async def wrapped():
            counts[name] += 1
            async with original() as session:
                yield session
        return wrapped

    permissions.get_session = counted("roles", originals[0])
    agency_ctx.get_session = counted("agency", originals[1])
    employees.get_session = counted("mirror", originals[2])
    async def counted_contexts(*args, **kwargs):
        def record(_conn, _cursor, statement, _params, _context, _many):
            agency_queries.append(statement)
        event.listen(engine.sync_engine, "before_cursor_execute", record)
        try:
            return await original_contexts(*args, **kwargs)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record)
    permissions.agency_contexts = counted_contexts
    resolve, server._resolve_account_id = server._resolve_account_id, lambda _req: IDS["creator_a"]
    try:
        def check(_fake):
            r = CHATTER_A.get(f"{ME}?account_id={IDS['creator_a']}")
            assert r.status_code == 200, (r.status_code, r.text)
        _with_fake_of(check)
        assert counts == {"roles": 1, "agency": 0, "mirror": 0}, counts
        assert len(agency_queries) == 3, agency_queries
    finally:
        server._resolve_account_id = resolve
        permissions.get_session, agency_ctx.get_session, employees.get_session = originals
        permissions.agency_contexts = original_contexts
        _reset()


def case_single_agency_role_guard_reads_current_allowlist():
    _roles(OWNER_A, True, {EMP_A: "admin"})
    account_id = IDS["creator_a"]
    other_account = IDS["creator_b"]
    resolve = server._resolve_account_id
    server._resolve_account_id = lambda _req: account_id
    def warm(_fake):
        r = CHATTER_A.get(f"{ME}?account_id={account_id}",
                          headers={"X-Account-Id": account_id})
        assert r.status_code == 200, r.text

    async def change(restrict: bool):
        async with get_session() as s:
            if restrict:
                s.add(ChatterAccountAccess(chatter_id=IDS["chatter_a"],
                                           user_id=IDS["agency_a_owner"],
                                           account_id=other_account))
            else:
                await s.execute(delete(ChatterAccountAccess).where(
                    ChatterAccountAccess.chatter_id == IDS["chatter_a"],
                    ChatterAccountAccess.user_id == IDS["agency_a_owner"],
                    ChatterAccountAccess.account_id == other_account,
                ))

    try:
        _with_fake_of(warm)
        asyncio.run(change(True))
        r = CHATTER_A.get(f"{ME}?account_id={account_id}",
                          headers={"X-Account-Id": account_id})
        assert r.status_code == 403 and r.json() == {"detail": "not your account"}, r.text
    finally:
        server._resolve_account_id = resolve
        asyncio.run(change(False))
        _reset()


def case_send_and_audit_resolve_one_chatter_employee_per_request():
    _roles(OWNER_A, True, {EMP_A: "admin"})
    original = employees.resolve_chatter_employee_id
    resolve = server._resolve_account_id
    calls = []

    async def counted(*args, **kwargs):
        employee_id = await original(*args, **kwargs)
        calls.append((kwargs.get("account_id"), employee_id))
        return employee_id

    employees.resolve_chatter_employee_id = counted
    server._resolve_account_id = lambda _req: IDS["creator_a"]
    try:
        def check(_fake):
            response = CHATTER_A.post(
                "/api/of/v2/chats/627000001/messages",
                headers={"X-Account-Id": IDS["creator_a"]}, json={"text": "test send"},
            )
            assert response.status_code == 200, (response.status_code, response.text)
        _with_fake_of(check)
        assert calls == [], calls
        _reset()
        _with_fake_of(check)
        assert calls == [(IDS["creator_a"], EMP_A)], calls
    finally:
        server._resolve_account_id = resolve
        employees.resolve_chatter_employee_id = original
        _reset()


def case_full_ai_config_writes_are_owner_only_and_the_read_follows_the_page():
    aid = IDS["creator_a"]
    get = f"/admin/full-ai/config?account_id={aid}"
    writes = (("put", "/admin/full-ai/config/draft", {"account_id": aid, "draft": {}, "rev": 0}),
              ("put", "/admin/full-ai/config/checkpoint", {"account_id": aid, "checkpoint": {}, "rev": 0}),
              ("post", "/admin/full-ai/config/save", {"account_id": aid, "rev": 0}),
              ("post", "/admin/full-ai/config/rollback", {"account_id": aid, "rev": 0}))
    denied = {"detail": "Your role does not allow Full AI Chat"}

    def write(client, how, path, body):
        return getattr(client, how)(path, json=body)

    try:
        _reset()
        for w in writes:
            r = write(CHATTER_A, *w)
            assert r.status_code == 403 and r.json() == denied, (w[1], r.text)
        _roles(OWNER_A, True, {EMP_A: "role-fa"}, _role("role-fa", _only("/full-ai-chatter")))
        for w in writes:
            r = write(CHATTER_A, *w)
            assert r.status_code == 403 and r.json() == denied, (w[1], r.text)
        r = CHATTER_A.get(get)
        assert r.status_code == 200 and r.json()["rev"] == 0, r.text
        _roles(OWNER_A, True, {EMP_A: "role-gi"}, _role("role-gi", _only("/growth/gen-info")))
        r = CHATTER_A.get(get)
        assert r.status_code == 403 and r.json() == denied, r.text
        assert OWNER_B.get(get).status_code == 403
        for w in writes:
            r = write(OWNER_B, *w)
            assert r.status_code == 403, (w[1], r.status_code, r.text)
        assert OWNER_A.get(get).json()["rev"] == 0
        put, ckpt, save, rollback = (write(OWNER_A, *w) for w in writes)
        assert put.status_code == 200 and put.json()["rev"] == 1, put.text
        assert ckpt.status_code == 409 and save.status_code == 409 and rollback.status_code == 409, (
            ckpt.text, save.text, rollback.text)
    finally:
        _reset()

COLLECTIONS_READS = ["/api/of/v2/lists/31/posts?limit=10", "/api/of/v2/lists/fans/posts?limit=10",
                     "/api/of/v2/subscribers?type=expired&limit=50", "/api/of/v2/lists/31/users?limit=50&query=bravo"]


def case_collections_alone_reads_list_posts_expired_fans_and_list_search_others_are_refused():
    shared = sorted({p for path in COLLECTIONS_READS for p in permissions.route_pages(path.split("?")[0], "GET")})
    assert "/of-manager/collections" in shared, shared
    try:
        _roles(OWNER_A, True, {EMP_A: "role-coll"}, _role("role-coll", _only("/of-manager/collections")))

        def _granted(fake):
            for path in COLLECTIONS_READS:
                r = CHATTER_A.get(path)
                assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
            assert fake.calls == ["list_posts_in", "list_posts_in", "subscribers", "list_users_in"], fake.calls
        _with_fake_of(_granted)
        _roles(OWNER_A, True, {EMP_A: "role-none"}, _role("role-none", _all_but(*shared)))

        def _refused(fake):
            for path in COLLECTIONS_READS:
                pages = permissions.route_pages(path.split("?")[0], "GET")
                want = {"detail": f"Your role does not allow {permissions.PAGE_MAP[pages[0]][0]}"}
                r = CHATTER_A.get(path)
                assert r.status_code == 403 and r.json() == want, f"{path}: {r.status_code} {r.text}"
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)
    finally:
        _reset()


def case_home_alone_reads_the_pin_to_home_lists_and_a_role_with_no_lists_page_is_refused():
    path = "/api/of/v2/lists?limit=50"
    pages = permissions.route_pages(path.split("?")[0], "GET")
    assert "/of-manager/home" in pages, pages
    try:
        _roles(OWNER_A, True, {EMP_A: "role-home"}, _role("role-home", _only("/of-manager/home")))

        def _granted(fake):
            r = CHATTER_A.get(path)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
            assert fake.calls == ["get_lists"], fake.calls
        _with_fake_of(_granted)
        _roles(OWNER_A, True, {EMP_A: "role-none"}, _role("role-none", _all_but(*pages)))

        def _refused(fake):
            r = CHATTER_A.get(path)
            assert r.status_code == 403 and r.json() == {"detail": f"Your role does not allow {permissions.PAGE_MAP[pages[0]][0]}"}, f"{path}: {r.status_code} {r.text}"
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)
    finally:
        _reset()


def case_home_grants_the_lists_read_only_and_collections_keeps_the_write():
    home, coll = "/of-manager/home", "/of-manager/collections"
    assert home in permissions.route_pages("/api/of/v2/lists", "GET")
    for method, path in (("POST", "/api/of/v2/lists"), ("POST", "/api/of/v2/lists/7/users/9"),
                         ("DELETE", "/api/of/v2/lists/7"), ("PATCH", "/api/of/v2/lists/7")):
        pages = permissions.route_pages(path, method)
        assert home not in pages and coll in pages, (method, path, pages)
    try:
        _roles(OWNER_A, True, {EMP_A: "role-home"}, _role("role-home", _only(home)))

        def _refused(fake):
            r = CHATTER_A.post("/api/of/v2/lists", json={"name": "x"})
            first = permissions.route_pages("/api/of/v2/lists", "POST")[0]
            assert r.status_code == 403 and r.json() == {"detail": f"Your role does not allow {permissions.PAGE_MAP[first][0]}"}, r.text
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)
        _roles(OWNER_A, True, {EMP_A: "role-coll"}, _role("role-coll", _only(coll)))

        def _served(fake):
            r = CHATTER_A.post("/api/of/v2/lists", json={"name": "x"})
            assert r.status_code != 403, f"{r.status_code} {r.text}"
        _with_fake_of(_served)
    finally:
        _reset()


def case_tracking_links_grants_the_lists_read_only():
    page = "/growth/tracking-links"
    assert page in permissions.route_pages("/api/of/v2/lists", "GET")
    for method, path in (("POST", "/api/of/v2/lists"), ("DELETE", "/api/of/v2/lists/7"),
                         ("PATCH", "/api/of/v2/lists/7"), ("DELETE", "/api/of/v2/lists/7/users/9")):
        assert page not in permissions.route_pages(path, method), (method, path)
    try:
        _roles(OWNER_A, True, {EMP_A: "role-tl"}, _role("role-tl", _only(page)))

        def _refused(fake):
            r = CHATTER_A.delete("/api/of/v2/lists/7")
            assert r.status_code == 403, f"{r.status_code} {r.text}"
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)
    finally:
        _reset()


def case_a_read_only_grant_on_every_page_of_a_prefix_fails_the_import():
    import types
    src = Path(permissions.__file__).read_text()
    line = '    "/of-manager/home": frozenset({"/api/of/v2/lists"}),\n'
    assert src.count(line) == 1
    every = permissions.route_pages("/api/of/v2/lists", "GET")
    bad = src.replace(line, "".join(f'    {h!r}: frozenset({{"/api/of/v2/lists"}}),\n' for h in every))
    try:
        exec(compile(bad, permissions.__file__, "exec"), types.ModuleType("permissions_planted").__dict__)
        raise AssertionError("a prefix granted read-only on every page must fail the import")
    except AssertionError as e:
        assert "/api/of/v2/lists" in str(e), e
    exec(compile(src, permissions.__file__, "exec"), types.ModuleType("permissions_as_is").__dict__)


def case_statements_alone_reads_the_creator_start_and_a_role_with_neither_page_is_refused():
    path = "/api/of/v2/users/me/start-date-model"
    pages = permissions.route_pages(path, "GET")
    assert "/of-manager/statements" in pages and "/of-manager/statistics" in pages, pages
    try:
        _roles(OWNER_A, True, {EMP_A: "role-statements"}, _role("role-statements", _only("/of-manager/statements")))

        def _granted(fake):
            r = CHATTER_A.get(path)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
            assert fake.calls == ["my_start_date"], fake.calls
        _with_fake_of(_granted)
        _roles(OWNER_A, True, {EMP_A: "role-none"}, _role("role-none", _all_but(*pages)))

        def _refused(fake):
            r = CHATTER_A.get(path)
            assert r.status_code == 403 and r.json() == {"detail": f"Your role does not allow {permissions.PAGE_MAP[pages[0]][0]}"}, f"{path}: {r.status_code} {r.text}"
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)
    finally:
        _reset()


def case_statements_alone_reads_the_payout_stats_and_a_role_with_neither_page_is_refused():
    path = "/api/of/v2/payouts/stats"
    pages = permissions.route_pages(path, "GET")
    assert "/of-manager/statements" in pages and "/of-manager/statistics" in pages, pages
    try:
        _roles(OWNER_A, True, {EMP_A: "role-statements"}, _role("role-statements", _only("/of-manager/statements")))

        def _granted(fake):
            for q in ("", "?startDate=2026-10-01&endDate=2026-10-31", "?startDate=2026-10-01 00:00:00&endDate=2026-10-31 23:59:59"):
                r = CHATTER_A.get(path + q)
                assert r.status_code == 200, f"{path}{q}: {r.status_code} {r.text}"
            assert fake.calls == ["earning_stats"] * 3, fake.calls
            r = CHATTER_A.get(path + "?startDate=2026-10-01T00:00:00Z&endDate=2026-10-31")
            assert r.status_code == 422, f"ISO start: {r.status_code} {r.text}"
            assert fake.calls == ["earning_stats"] * 3, fake.calls
        _with_fake_of(_granted)
        seen = []

        class _Stats:
            def earning_stats(self, **k):
                seen.append(k)
                return {"ok": True}
        original = server._get_client
        server._get_client = lambda *_a, **_k: _Stats()
        try:
            for q in ("?startDate=2026-09-01&endDate=2026-09-30", "?start=2026-08-01&end=2026-08-31"):
                assert CHATTER_A.get(path + q).status_code == 200, q
        finally:
            server._get_client = original
        assert seen == [{"by": "day", "start_date": "2026-09-01", "end_date": "2026-09-30"},
                        {"by": "day", "start_date": None, "end_date": None}], seen
        _roles(OWNER_A, True, {EMP_A: "role-none"}, _role("role-none", _all_but(*pages)))

        def _refused(fake):
            r = CHATTER_A.get(path + "?startDate=2026-10-01&endDate=2026-10-31")
            assert r.status_code == 403 and r.json() == {"detail": f"Your role does not allow {permissions.PAGE_MAP[pages[0]][0]}"}, f"{path}: {r.status_code} {r.text}"
            assert fake.calls == [], fake.calls
        _with_fake_of(_refused)
    finally:
        _reset()


def case_chats_readable_fails_closed_when_no_page_serves_the_chat_history():
    a = IDS["creator_a"]
    real = permissions.route_pages
    try:
        _reset()
        assert asyncio.run(server._chats_readable(frozenset({a}))) is None, "mapped, enforcement off: every one"
        for unmapped in ((), None):
            permissions.route_pages = lambda _p, _m, _v=unmapped: _v
            assert asyncio.run(server._chats_readable(frozenset({a}))) == frozenset(), f"unmapped {unmapped!r}: none"
    finally:
        permissions.route_pages = real
        _reset()


def case_events_strip_reply_text_for_creators_whose_chats_the_role_does_not_grant():
    import json as _json
    import chatters
    import events

    class _Req:
        headers: dict = {}

        async def is_disconnected(self) -> bool:
            return False

    a, b = IDS["creator_a"], IDS["creator_b"]

    def ident(name: str, owners: tuple[str, ...], accounts: frozenset) -> chatters.ChatterIdentity:
        return chatters.ChatterIdentity(id_=IDS[name], username=name, display_name=None, color=None,
                                        owner_user_ids=frozenset(IDS[o] for o in owners), account_ids=accounts)

    def texts(who: chatters.ChatterIdentity) -> dict[str, bool]:
        async def run():
            tok = chatters._request_chatter.set(who)
            try:
                gen = (await server.sse_events(_Req(), scope="all", last_event_id=None)).body_iterator
            finally:
                chatters._request_chatter.reset(tok)
            await gen.__anext__(), await gen.__anext__()
            for aid in sorted(who.account_ids):
                events.publish({"chat_responded": {"fan_id": 1, "by": "", "at": 1,
                                                   "message": {"id": 2, "text": "t", "price": 9.0}},
                                "__account_id": aid})
            out = {}
            for _ in who.account_ids:
                raw = (await asyncio.wait_for(gen.__anext__(), 3)).decode()
                data = _json.loads(next(ln[6:] for ln in raw.split("\n") if ln.startswith("data: ")))
                for d in (m["data"] for m in data) if isinstance(data, list) else (data,):
                    out[d["__account_id"]] = "message" in d["chat_responded"]
            await gen.aclose()
            return out
        return asyncio.run(run())

    solo = ident("chatter_a", ("agency_a_owner",), frozenset({a}))
    both = ident("chatter_ab", ("agency_a_owner", "agency_b_owner"), frozenset({a, b}))
    try:
        _reset()
        assert texts(solo) == {a: True}, "enforcement off: whole"
        _roles(OWNER_A, True, {EMP_A: "role-msg"}, _role("role-msg", _only("/of-manager/messages")))
        assert texts(solo) == {a: True}, "Messages Basic grants the chat history"
        _roles(OWNER_A, True, {EMP_A: "role-pro"}, _role("role-pro", _only("/messages-pro")))
        assert texts(solo) == {a: True}, "so does Messages Pro"
        _roles(OWNER_A, True, {EMP_A: "role-ap"}, _role("role-ap", _only("/growth/auto-post")))
        assert texts(solo) == {a: False}, "a role without a messages page: no reply text"
        _roles(OWNER_A, True, {EMP_AB_A: "role-ap"}, _role("role-ap", _only("/growth/auto-post")))
        _roles(OWNER_B, True, {EMP_AB_B: "role-msg"}, _role("role-msg", _only("/of-manager/messages")))
        assert texts(both) == {a: False, b: True}, "per Creator: its own Agency's role decides"
    finally:
        _reset()
        events._subs.clear()


_harness.run()
