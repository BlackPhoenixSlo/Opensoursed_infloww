#!/usr/bin/env python3
"""Toolbox write tools (step 3; docs/plans/ultra-mode/issues/04-toolbox.md, 05-mcp-server.md) on the two-Agency
bench, through the real app in-process: MCP tools/call with an owner token, a fake OnlyFans client, the bio files
dir and vault stills in temp dirs.

Cases:
  case_listed_as_writes          — tools/list: the six write tools, readOnlyHint false; destructiveHint true only
                                   for the two that replace (and delete) an image file.
  case_folder_tools              — of_folder_create / of_folder_add over MCP: OF called for Creator A only, the
                                   echo in the result, open_url; audit rows carry Creator A, "token mcp" and
                                   A's owner Employee; no /admin/mcp row.
  case_bio_tools                 — bio_page_create / bio_link_add / bio_avatar_from_vault / bio_link_bg_from_vault /
                                   bio_page_background
                                   over MCP: the page changes as asked, open_url = the page; the bound writes are
                                   audited as the page's stored Creator; a page with no Creator still takes a link.
  case_page_without_of_link_is_error — bio_page_create for a Creator whose OnlyFans profile is unreadable: the page
                                   is made with no OnlyFans link → an error result naming the page id.
  case_resource_tools_audit_its_creator — drift over TOOLS: each write tool with no account_id is audited as the
                                   resource's stored Creator.
  case_new_link_past_row_cap     — bio_link_add on a page past the 50-row cut: `link` names the new link (cut from
                                   `links`); its id takes a background.
  case_echo_lost_args_is_error   — OF drops the media of a new folder (route still 200): an error result, not
                                   success; every check's mismatch table (pure).
  case_args_refused_no_request   — bad args: 422 per field, no OF call, no row written.
  case_cross_agency_refused      — A's token: Creator B (of_folder_create / of_folder_add / bio_page_create) and
                                   B's page (bio_page_get, each page tool) are refused before any write; B unchanged.
  case_bearer_raw_route_gated    — a bearer on the raw write routes must send exactly what the tool sends: an extra
                                   body key, a wrong type, a body nested past the JSON decoder's depth, an extra
                                   query param, a missing or mismatched Creator, unsent defaults, a path key in the
                                   body, any X-Account-Id / ?account_id= on a
                                   bio page route (foreign, own other, even the page's) → 403 before the route; the
                                   tool's own request passes, the bio write audited as the page's stored Creator; a
                                   cookie caller is not gated, its bio write audited as the page's Creator too.
  case_revoked_token_cannot_write — a revoked token: 401 on the raw route and on MCP, no OF call.

Seeded straight into the temp DB; no network, no real OnlyFans.

Run: ./venv/bin/python service/tests/test_toolbox_writes.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

os.environ["BIO_FILES_DIR"] = tempfile.mkdtemp(prefix="toolbox_writes_bio_")
os.environ["BIO_PUBLIC_URL"] = "https://bio.test/"
os.environ.pop("BIO_HEALTH_URL", None)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402
from io import BytesIO  # noqa: E402

from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402
import mcp_api  # noqa: E402
import token_auth  # noqa: E402
import toolbox_decide as td  # noqa: E402
import toolbox_writes as tw  # noqa: E402
import vault_stills  # noqa: E402
from bio_pages import admin as bio_admin  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, BioLink, BioProfile, Employee, UserAccount, VaultItem  # noqa: E402

IDS = fx.seed_two_agencies()
CA, CB = IDS["creator_a"], IDS["creator_b"]
CA2 = "1000003"  # a second Creator of Agency A
OWNER_A = IDS["agency_a_owner"]
for _aid, _nick in ((CA, "creator_a"), (CB, "creator_b"), (CA2, "creator_a2")):
    account_registry.save_meta(_aid, {"id": _aid, "nickname": _nick})

A = fx.login_owner("agency_a_owner")
B = fx.login_owner("agency_b_owner")
ANON = _harness.make_client()
WRITES = ("of_folder_create", "of_folder_add", "bio_page_create", "bio_avatar_from_vault", "bio_link_add",
          "bio_link_bg_from_vault", "bio_page_background")
BY_NAME = {t.name: t for t in td.TOOLS}
PHOTO_A, PHOTO_A2, PHOTO_B = 9001, 9002, 9101


def _mint(client, name="mcp") -> dict:
    r = client.post("/admin/owner-tokens", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


TOK_A, TOK_B = _mint(A)["token"], _mint(B)["token"]
HA = {"Authorization": f"Bearer {TOK_A}"}
HB = {"Authorization": f"Bearer {TOK_B}"}


class _FakeOF:
    """The OnlyFans client the folder routes build (`ax._make_client`): every call recorded."""

    def __init__(self):
        self.timeout_s = 5.0
        self.built_for: list[str] = []
        self.calls: list[tuple] = []
        self.next_list_id = 7000
        self.fail_add = False

    def reset(self) -> None:
        self.built_for.clear()
        self.calls.clear()
        self.fail_add = False

    def make_client(self, account_id, *_a, **_k):
        self.built_for.append(str(account_id))
        return self

    def create_vault_list(self, name):
        self.calls.append(("create_vault_list", name))
        self.next_list_id += 1
        return {"id": self.next_list_id, "name": name}

    def add_media_to_vault_list(self, list_id, media_ids):
        self.calls.append(("add_media_to_vault_list", int(list_id), list(media_ids)))
        if self.fail_add:
            raise RuntimeError("OnlyFans said no")
        return {"success": True}


OF = _FakeOF()
ax._make_client = OF.make_client  # type: ignore[assignment]


async def _fake_me(account_id):
    return {"name": "Ava", "username": "ava.of"}
bio_admin._of_me = _fake_me  # type: ignore[assignment]

vault_stills.IMAGE_DIR = Path(tempfile.mkdtemp(prefix="toolbox_writes_stills_"))


def _jpeg() -> bytes:
    out = BytesIO()
    Image.new("RGB", (1200, 900), (200, 80, 40)).save(out, "JPEG")
    return out.getvalue()


async def _seed() -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Account(id=CA2, nickname="creator_a2", color="#aaaaaa"))
        s.add(UserAccount(user_id=OWNER_A, account_id=CA2))
        for aid, mid in ((CA, PHOTO_A), (CA, PHOTO_A2), (CB, PHOTO_B)):
            s.add(VaultItem(account_id=aid, media_id=mid, kind="photo", raw_json=json.dumps({"id": mid}),
                            created_at=now, updated_at=now, last_seen_run_id=1, search_text="photo",
                            tags="[]", of_folder_ids="[]"))
            path = vault_stills.image_path(aid, mid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_jpeg())
asyncio.run(_seed())

_ids = iter(range(1, 10_000))


def _rpc(method, params=None, headers=HA):
    msg = {"jsonrpc": "2.0", "id": next(_ids), "method": method, **({"params": params} if params is not None else {})}
    r = ANON.post(mcp_api.PATH, content=json.dumps(msg).encode(),
                  headers={"Content-Type": "application/json", **headers})
    assert r.status_code == 200, (method, r.status_code, r.text)
    return r.json()


def _tool(name, args, headers=HA) -> dict:
    """tools/call → (isError, structuredContent)."""
    res = _rpc("tools/call", {"name": name, "arguments": args}, headers)["result"]
    assert json.loads(res["content"][0]["text"]) == res["structuredContent"], res
    return {"isError": res["isError"], **res["structuredContent"]}


async def _actions_async(since: int = 0) -> list[tuple]:
    async with get_session() as s:
        rows = (await s.execute(
            select(Action.id, Action.action, Action.account_id, Action.via, Employee.user_id)
            .outerjoin(Employee, Employee.id == Action.employee_id).where(Action.id > since)
            .order_by(Action.id))).all()
    return [tuple(r) for r in rows]


def _actions(since: int = 0) -> list[tuple]:
    return asyncio.run(_actions_async(since))


def _last_action_id() -> int:
    rows = _actions()
    return rows[-1][0] if rows else 0


async def _pages_async(owner_user_id: str | None = None) -> list[tuple]:
    async with get_session() as s:
        q = select(BioProfile.id, BioProfile.username, BioProfile.avatar, BioProfile.account_id)
        if owner_user_id:
            q = q.where(BioProfile.owner_user_id == owner_user_id)
        pages = [tuple(r) for r in (await s.execute(q.order_by(BioProfile.id))).all()]
        links = [tuple(r) for r in (await s.execute(
            select(BioLink.id, BioLink.profile_id, BioLink.title, BioLink.background_image)
            .order_by(BioLink.id))).all()]
    return pages + links


def _bio_rows(owner_user_id: str | None = None) -> list[tuple]:
    return asyncio.run(_pages_async(owner_user_id))


def _b_page() -> tuple[str, str]:
    """Agency B's page (with Creator B) and one link on it, made by B's own cookie."""
    r = B.post("/admin/bio-pages", json={"username": f"bpage{next(_ids)}", "display_name": "B", "account_id": CB})
    assert r.status_code == 201, r.text
    pid = r.json()["profile"]["id"]
    r = B.post(f"/admin/bio-pages/{pid}/links", json={"title": "B link", "destination": "https://b.test/"})
    assert r.status_code == 201, r.text
    return pid, r.json()["links"][-1]["id"]


# ── cases ────────────────────────────────────────────────────────────

def case_listed_as_writes() -> None:
    listed = {t["name"]: t for t in _rpc("tools/list")["result"]["tools"]}
    for name in WRITES:
        assert name in listed, (name, sorted(listed))
        ann = listed[name]["annotations"]
        assert ann["readOnlyHint"] is False, (name, ann)
        assert ann["destructiveHint"] is (name in ("bio_avatar_from_vault", "bio_link_bg_from_vault",
                                                   "bio_page_background")), (name, ann)
        assert BY_NAME[name].effect == "write", name
    assert listed["creators_list"]["annotations"]["readOnlyHint"] is True


def case_folder_tools() -> None:
    OF.reset()
    since = _last_action_id()
    fwd = {**HA, "X-Forwarded-Host": "app.example.com", "X-Forwarded-Proto": "https"}
    res = _tool("of_folder_create", {"account_id": CA, "name": "  Promo  ", "media_ids": [PHOTO_A]}, fwd)
    assert res["isError"] is False, res
    fid = res["id"]
    assert (res["name"], res["added"], res["account_id"]) == ("Promo", 1, CA), res
    assert res["open_url"] == "https://app.example.com/growth/vault-pro", res
    res = _tool("of_folder_add", {"account_id": CA, "list_id": fid, "media_ids": [PHOTO_A2]})
    assert res["isError"] is False and (res["list_id"], res["added"]) == (fid, 1), res
    assert res["open_url"] == "/growth/vault-pro", res
    assert set(OF.built_for) == {CA}, OF.built_for
    assert OF.calls == [("create_vault_list", "Promo"), ("add_media_to_vault_list", fid, [PHOTO_A]),
                        ("add_media_to_vault_list", fid, [PHOTO_A2])], OF.calls
    new = [(a, aid, via, uid) for _, a, aid, via, uid in _actions(since)]
    assert ("POST /admin/vault-ai/of-folders", CA, "token mcp", OWNER_A) in new, new
    assert (f"POST /admin/vault-ai/of-folders/{fid}/add", CA, "token mcp", OWNER_A) in new, new
    assert not any("/admin/mcp" in a for a, *_ in new), new


def case_bio_tools() -> None:
    since = _last_action_id()
    res = _tool("bio_page_create", {"username": "tool_page", "account_id": CA})
    assert res["isError"] is False, res
    pid = res["profile"]["id"]
    assert (res["profile"]["display_name"], res["profile"]["account_id"]) == ("Ava", CA), res
    assert res["open_url"] == f"/growth/bio-pages/{pid}", res
    assert [lk["title"] for lk in res["links"]] == ["OnlyFans"], res
    res = _tool("bio_link_add", {"pid": pid, "title": " Shop ", "destination": "https://shop.test/x",
                                 "icon": "linkicon", "is_adult": True})
    assert res["isError"] is False, res
    lk = res["link"]
    assert res["links"][-1] == lk, res
    assert (lk["title"], lk["destination"], lk["icon_stock"], lk["is_adult"], lk["tracking"]) == (
        "Shop", "https://shop.test/x", "linkicon", True, False), lk
    assert res["open_url"] == f"/growth/bio-pages/{pid}", res
    res = _tool("bio_avatar_from_vault", {"pid": pid, "media_id": PHOTO_A})
    assert res["isError"] is False and res["profile"]["avatar"].startswith("avatar_"), res
    res = _tool("bio_link_bg_from_vault", {"pid": pid, "lid": lk["id"], "media_id": PHOTO_A})
    assert res["isError"] is False, res
    assert next(x for x in res["links"] if x["id"] == lk["id"])["background_image"].startswith("backgroundImage_")
    res = _tool("bio_page_background", {"pid": pid, "media_id": PHOTO_A})
    assert res["isError"] is False and f"/profiles/{pid}/background_" in res["profile"]["background_url"], res
    new = [(a, aid, via, uid) for _, a, aid, via, uid in _actions(since)]
    for action in ("POST /admin/bio-pages", f"POST /admin/bio-pages/{pid}/links",
                   f"POST /admin/bio-pages/{pid}/avatar/vault", f"POST /admin/bio-pages/{pid}/background/vault",
                   f"POST /admin/bio-pages/{pid}/links/{lk['id']}/background/vault"):
        assert (action, CA, "token mcp", OWNER_A) in new, (action, new)  # the page's stored Creator
    # A page with no Creator: no Creator to bind, the link still lands; audit says no Creator.
    bare = _tool("bio_page_create", {"username": "tool_bare", "display_name": "Bare"})
    assert bare["isError"] is False and bare["profile"]["account_id"] is None and bare["links"] == [], bare
    since = _last_action_id()
    res = _tool("bio_link_add", {"pid": bare["profile"]["id"], "title": "Hi", "destination": "https://hi.test/"})
    assert res["isError"] is False, res
    assert [(aid, via) for _, _, aid, via, _ in _actions(since)] == [(None, "token mcp")], _actions(since)
    # A vault photo needs a Creator: the route's 409 comes back as an error result.
    res = _tool("bio_avatar_from_vault", {"pid": bare["profile"]["id"], "media_id": PHOTO_A})
    assert res["isError"] is True and res["error"]["status"] == 409, res


def case_page_without_of_link_is_error() -> None:
    """The Creator's OnlyFans profile unreadable + an explicit name: the route still creates the page, with no
    OnlyFans link (bio_pages.admin._of_me swallows it) → an error naming the page, not success."""
    async def _no_me(account_id):
        return None
    bio_admin._of_me = _no_me  # type: ignore[assignment]
    try:
        res = _tool("bio_page_create", {"username": "no_of_link", "display_name": "Ava", "account_id": CA})
    finally:
        bio_admin._of_me = _fake_me  # type: ignore[assignment]
    pid = next(r[0] for r in _bio_rows() if r[1] == "no_of_link")  # the page was made
    assert res["isError"] is True and res["error"]["status"] == 502, res
    assert res["error"]["detail"]["detail"] == (f"page {pid} was created without the OnlyFans link; do not retry "
                                                "create; add it with bio_link_add"), res
    assert res["open_url"] == f"/growth/bio-pages/{pid}", res


def case_resource_tools_audit_its_creator() -> None:
    """Drift, over TOOLS: the gate refuses any Creator to a write tool with no account_id, so each such tool's
    route must audit the resource's stored Creator (bio_pages.admin._audit_as). A new one needs a row here."""
    page = _tool("bio_page_create", {"username": f"drift_page{next(_ids)}", "account_id": CA})
    pid, lid = page["profile"]["id"], page["links"][0]["id"]
    sample = {"bio_avatar_from_vault": {"pid": pid, "media_id": PHOTO_A},
              "bio_link_add": {"pid": pid, "title": "Drift", "destination": "https://drift.test/"},
              "bio_link_bg_from_vault": {"pid": pid, "lid": lid, "media_id": PHOTO_A},
              "bio_page_background": {"pid": pid, "media_id": PHOTO_A}}
    tools = [t.name for t in td.TOOLS if t.effect == "write" and "account_id" not in t.args.model_fields]
    assert sorted(tools) == sorted(sample), tools
    for name in tools:
        since = _last_action_id()
        res = _tool(name, sample[name])
        assert res["isError"] is False, (name, res)
        assert [(aid, via) for _, _, aid, via, _ in _actions(since)] == [(CA, "token mcp")], (name, _actions(since))


async def _add_links(pid: str, n: int) -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        s.add_all(BioLink(id=f"fill{pid[:4]}{i:07d}", profile_id=pid, link_id=f"f{i:011d}", title=f"Fill {i}",
                          destination="https://fill.test/", sort_order=i, created_at=now, updated_at=now)
                  for i in range(n))


def case_new_link_past_row_cap() -> None:
    """A page past the result's 50-row cut: the new link (last) is cut from `links`, `link` still names it."""
    pid = _tool("bio_page_create", {"username": f"full_page{next(_ids)}", "account_id": CA})["profile"]["id"]
    asyncio.run(_add_links(pid, td.MAX_ROWS + 5))
    res = _tool("bio_link_add", {"pid": pid, "title": "Last", "destination": "https://last.test/"})
    assert res["isError"] is False and res["truncated"] is True and res["row_count"] == td.MAX_ROWS + 7, res
    lk = res["link"]
    assert lk["title"] == "Last" and lk["id"] not in {x["id"] for x in res["links"]}, res
    res = _tool("bio_link_bg_from_vault", {"pid": pid, "lid": lk["id"], "media_id": PHOTO_A})
    assert res["isError"] is False, res


def case_echo_lost_args_is_error() -> None:
    OF.reset()
    OF.fail_add = True  # the route swallows this and still answers 200 with added=0
    res = _tool("of_folder_create", {"account_id": CA, "name": "Lost", "media_ids": [PHOTO_A]})
    assert res["isError"] is True and res["error"]["status"] == 502, res
    assert "0 of 1 media added" in res["error"]["detail"]["detail"], res
    assert res["open_url"] == "/growth/vault-pro", res
    OF.reset()
    a = {"account_id": CA, "name": "N", "media_ids": [1, 2]}
    page = {"profile": {"id": "p" * 15}, "links": [
        {"id": "l1", "title": "T", "destination": "https://d/", "icon_stock": None, "is_adult": False,
         "tracking": False, "background_image": ""}]}
    link = {"pid": "p" * 15, "title": "New", "destination": "https://n/", "icon": "igicon", "is_adult": False,
            "tracking": True}
    new_link = {**link, "id": "l2", "icon_stock": "igicon"}
    theirs = {**new_link, "id": "l3", "title": "Theirs"}
    of_link = {"id": "l0", "title": "OnlyFans", "destination": "https://onlyfans.com/ava.of"}
    ok = (
        (tw.check_folder_create, a, {"account_id": CA, "id": 5, "name": "N", "added": 2}),
        (tw.check_bio_page_create, {"username": "u_1", "display_name": None, "account_id": CA},
         {"profile": {"id": "x", "username": "u_1", "display_name": "OF name", "account_id": CA}, "links": [of_link]}),
        (tw.check_bio_page_create, {"username": "u_1", "display_name": "Mine", "account_id": None},
         {"profile": {"id": "x", "username": "u_1", "display_name": "Mine", "account_id": None}, "links": []}),
        (tw.check_bio_link_add, link, {**page, "links": [*page["links"], new_link], "link": new_link}),
        # The route names the created link: a concurrent add beside it is not a failed write.
        (tw.check_bio_link_add, link, {**page, "links": [*page["links"], theirs, new_link], "link": new_link}),
    )
    for check, args, body in ok:
        assert check(args, body) is None, (check.__name__, check(args, body))
    bad = (
        (tw.check_folder_create, a, {"account_id": CA, "id": None, "name": "N", "added": 2}),
        (tw.check_folder_create, a, {"account_id": CA, "id": 5, "name": "N", "added": 1}),
        (tw.check_folder_create, a, {"account_id": CA, "id": 5, "name": "Other", "added": 2}),
        (tw.check_bio_page_create, {"username": "u_1", "display_name": "Mine", "account_id": CA},
         {"profile": {"id": "x", "username": "u_1", "display_name": "OF name", "account_id": CA}}),
        (tw.check_bio_page_create, {"username": "u_1", "display_name": None, "account_id": CA},
         {"profile": {"id": "x", "username": "u_1", "display_name": "N", "account_id": None}}),
        (tw.check_bio_page_create, {"username": "u_1", "display_name": None, "account_id": None}, {}),
        # A Creator asked, her OnlyFans profile unreadable: the page has no OnlyFans link.
        (tw.check_bio_page_create, {"username": "u_1", "display_name": "Mine", "account_id": CA},
         {"profile": {"id": "x", "username": "u_1", "display_name": "Mine", "account_id": CA},
          "links": [{**of_link, "destination": "https://other.test/onlyfans.com/"}]}),
        (tw.check_bio_link_add, link, {**page, "links": [*page["links"], new_link]}),  # no `link`
        (tw.check_bio_link_add, link, {**page, "link": {**new_link, "tracking": False}}),
        (tw.check_bio_link_add, link, {**page, "link": {**new_link, "icon_stock": None}}),
        (tw.check_bio_link_add, link, {**page, "links": [*page["links"], new_link], "link": theirs}),
    )
    for check, args, body in bad:
        assert isinstance(check(args, body), str), (check.__name__, args, body)
    # No id back: of_folders_list hides empty folders, so the text must stop a duplicating retry.
    why = tw.check_folder_create(a, {"account_id": CA, "id": None, "name": "N", "added": 0})
    assert "do not retry" in why and "of_folders_list" not in why, why


def case_args_refused_no_request() -> None:
    OF.reset()
    since, rows = _last_action_id(), _bio_rows()
    pid = _tool("bio_pages_list", {})["profiles"][0]["id"]
    for name, args, field in (
        ("of_folder_create", {"account_id": CA, "name": "X", "media_ids": ["9001"]}, "media_ids.0"),
        ("of_folder_create", {"account_id": CA, "name": "   "}, "name"),
        ("of_folder_create", {"account_id": CA, "name": "X", "extra": 1}, "extra"),
        ("of_folder_add", {"account_id": CA, "list_id": 5, "media_ids": []}, "media_ids"),
        ("bio_page_create", {"username": "Bad Name"}, "username"),
        ("bio_page_create", {"username": "fine_name", "mode": "direct"}, "mode"),
        ("bio_link_add", {"pid": pid, "title": "T", "destination": "https://x/", "geo": {}}, "geo"),
        ("bio_link_add", {"pid": pid, "title": "T", "destination": "https://x/", "is_adult": "yes"}, "is_adult"),
        ("bio_avatar_from_vault", {"pid": "../x", "media_id": PHOTO_A}, "pid"),
        ("bio_link_bg_from_vault", {"pid": pid, "lid": "short", "media_id": True}, "lid"),
    ):
        res = _tool(name, args)
        assert res["isError"] is True and res["error"]["status"] == 422, (name, res)
        assert field in res["error"]["detail"]["errors"], (name, field, res)
    assert OF.built_for == [] and OF.calls == [], OF.calls
    assert _actions(since) == [] and _bio_rows() == rows


def case_cross_agency_refused() -> None:
    OF.reset()
    b_pid, b_lid = _b_page()
    since, b_rows = _last_action_id(), _bio_rows(IDS["agency_b_owner"])
    for name, args in (
        ("bio_page_get", {"pid": b_pid}),
        ("of_folder_create", {"account_id": CB, "name": "Theirs", "media_ids": [PHOTO_B]}),
        ("of_folder_add", {"account_id": CB, "list_id": 7001, "media_ids": [PHOTO_B]}),
        ("bio_page_create", {"username": "steal_b", "account_id": CB}),
        ("bio_link_add", {"pid": b_pid, "title": "Mine now", "destination": "https://a.test/"}),
        ("bio_avatar_from_vault", {"pid": b_pid, "media_id": PHOTO_B}),
        ("bio_link_bg_from_vault", {"pid": b_pid, "lid": b_lid, "media_id": PHOTO_B}),
        ("bio_page_background", {"pid": b_pid, "media_id": PHOTO_B}),
    ):
        res = _tool(name, args)
        assert res["isError"] is True and res["error"]["status"] in (403, 404), (name, res)
    assert OF.built_for == [] and OF.calls == [], (OF.built_for, OF.calls)
    assert _actions(since) == [], _actions(since)
    assert _bio_rows(IDS["agency_b_owner"]) == b_rows
    assert not any(r[1] == "steal_b" for r in _bio_rows())
    # The other way round: B's token on A's Creator and A's page.
    a_pid = _tool("bio_pages_list", {})["profiles"][0]["id"]
    assert _tool("of_folder_create", {"account_id": CA, "name": "x"}, HB)["error"]["status"] in (403, 404)
    assert _tool("bio_link_add", {"pid": a_pid, "title": "x", "destination": "https://x/"}, HB)["error"]["status"] == 404
    assert OF.calls == [] and _actions(since) == []


def case_bearer_raw_route_gated() -> None:
    OF.reset()
    pid = _tool("bio_page_create", {"username": f"raw_page{next(_ids)}", "account_id": CA})["profile"]["id"]
    since = _last_action_id()
    folder = "/admin/vault-ai/of-folders"
    ok_body = {"account_id": CA, "name": "Raw", "media_ids": [PHOTO_A]}
    as_tool = ({"account_id": CA}, {"X-Account-Id": CA})
    link = f"/admin/bio-pages/{pid}/links"
    ok_link = {"title": "Raw", "destination": "https://raw.test/", "is_adult": False, "tracking": False}
    refused = (
        ("POST", folder, {**ok_body, "x": 1}, *as_tool),                                  # unknown body key
        ("POST", folder, {**ok_body, "media_ids": ["9001"]}, *as_tool),                   # a type the tool refuses
        ("POST", folder, ok_body, {"account_id": CA, "debug": "1"}, as_tool[1]),          # unknown query param
        ("POST", folder, ok_body, {"account_id": CA}, {"X-Account-Id": CB}),              # header ≠ body Creator
        ("POST", folder, ok_body, {"account_id": CB}, as_tool[1]),                        # query ≠ body Creator
        ("POST", folder, ok_body, {}, {}),                                                # no header/query Creator
        ("POST", folder, {**ok_body, "name": " Raw "}, *as_tool),                         # not as the tool sends it
        ("POST", f"{folder}/7001/add", {"account_id": CA, "list_id": 7002, "media_ids": [PHOTO_A]}, *as_tool),
        ("POST", link, {**ok_link, "geo": {"US": "1"}}, {}, {}),
        ("POST", link, {"title": "Raw", "destination": "https://raw.test/"}, {}, {}),     # defaults not sent
        ("POST", link, {**ok_link, "is_adult": 0}, {}, {}),                               # 0 is not false
        # A page tool takes no Creator: its route audits the page's stored one, so none may be named.
        ("POST", link, ok_link, {}, {"X-Account-Id": CB}),                                # another Agency's
        ("POST", link, ok_link, {}, {"X-Account-Id": CA2}),                               # own Agency, not the page's
        ("POST", link, ok_link, {}, {"X-Account-Id": CA}),                                # even the page's own
        ("POST", link, ok_link, {"account_id": CA2}, {}),
        ("POST", f"/admin/bio-pages/{pid}/avatar/vault", {"media_id": PHOTO_A}, {}, {"X-Account-Id": CA2}),
        ("POST", f"/admin/bio-pages/{pid}/avatar/vault", {"media_id": PHOTO_A, "type": "photo"}, {}, {}),
        ("POST", "/admin/bio-pages", {"username": "raw_mode", "display_name": "R", "mode": "direct"}, {}, {}),
        ("POST", "/admin/bio-pages", [1, 2], {}, {}),                                     # not an object
    )
    for method, path, body, query, headers in refused:
        r = ANON.request(method, path, json=body, params=query, headers={**HA, **headers})
        assert r.status_code == 403, (path, body, query, headers, r.status_code, r.text)
        assert r.json()["detail"].startswith(token_auth.WRITE_REFUSED), r.text
    r = ANON.post(folder, content=b"{not json", headers={**HA, "Content-Type": "application/json"})
    assert r.status_code == 403, r.text
    deep = b'{"name":' + b"[" * 100_000 + b"]" * 100_000 + b"}"  # json.loads → RecursionError, not ValueError
    r = ANON.post(folder, content=deep, headers={**HA, "Content-Type": "application/json"})
    assert r.status_code == 403 and r.json()["detail"].startswith(token_auth.WRITE_REFUSED), (r.status_code, r.text)
    assert OF.calls == [] and _actions(since) == [], (OF.calls, _actions(since))
    # Exactly what the tool would send: through, and audited as the token — the bio write as the page's Creator.
    r = ANON.post(folder, json=ok_body, params=as_tool[0], headers={**HA, **as_tool[1]})
    assert r.status_code == 200 and r.json()["added"] == 1, r.text
    r = ANON.post(link, json=ok_link, headers=HA)
    assert r.status_code == 201, r.text
    assert [(a, aid, via) for _, a, aid, via, _ in _actions(since)] == [
        ("POST /admin/vault-ai/of-folders", CA, "token mcp"), (f"POST {link}", CA, "token mcp")], _actions(since)
    # A cookie caller is not gated: the same extra keys reach the route as before; a bio write it labels with
    # another Creator is still audited as the page's own.
    since = _last_action_id()
    r = A.post(folder, json={**ok_body, "x": 1})
    assert r.status_code == 200, r.text
    r = A.post(link, json={"title": "Geo", "destination": "https://x/", "geo": {"US": "1"}}, headers={"X-Account-Id": CA2})
    assert r.status_code == 201, r.text
    assert [aid for _, _, aid, _, _ in _actions(since)] == [None, CA], _actions(since)  # folder: no header sent


def case_revoked_token_cannot_write() -> None:
    OF.reset()
    minted = _mint(A, "revoke-me")
    h = {"Authorization": f"Bearer {minted['token']}"}
    assert _tool("creators_list", {}, h)["isError"] is False
    r = A.delete(f"/admin/owner-tokens/{minted['id']}")
    assert r.status_code == 200, r.text
    since = _last_action_id()
    r = ANON.post("/admin/vault-ai/of-folders", json={"account_id": CA, "name": "Gone"}, headers=h)
    assert r.status_code == 401, r.text
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "of_folder_create", "arguments": {"account_id": CA, "name": "Gone"}}}
    r = ANON.post(mcp_api.PATH, json=msg, headers=h)
    assert r.status_code == 401, r.text
    assert OF.built_for == [] and OF.calls == [] and _actions(since) == []


if __name__ == "__main__":
    _harness.run()
