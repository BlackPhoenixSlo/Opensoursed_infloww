from __future__ import annotations

import asyncio
from contextlib import nullcontext
import io
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import patch

from _send_kill import Driver, Wire, db_row, seed_account


def _req(aid: str):
    return types.SimpleNamespace(method="POST", headers={"x-account-id": aid}, query_params={},
                                 state=types.SimpleNamespace())


async def _call_route(ctx, fn):
    import accounts
    import server
    tok = server._request_ctx.set(ctx["req"])
    try:
        platform = patch.object(accounts, "get_platform", return_value=ctx["platform"]) if "platform" in ctx else nullcontext()
        with platform, patch.object(server, "_load_client", return_value=ctx["client"]):
            return await fn(server)
    finally:
        server._request_ctx.reset(tok)


async def _composer_setup(aid: str, wire: Wire):
    await seed_account(aid)
    return {"aid": aid, "fan": 71001, "req": _req(aid), "client": wire.of_client(aid)}


async def _composer_send(ctx):
    import server
    await _call_route(ctx, lambda srv: srv.send_message(
        ctx["req"], ctx["fan"], server.SendMessageBody(text="hey from the composer")))


async def _composer_shim_setup(aid: str, wire: Wire):
    from fansly_client import FanslySession
    from fansly_shim import FanslyShimClient

    await seed_account(aid)
    fan, creator = 71001, "71000"
    client = FanslyShimClient(FanslySession({
        "accountId": creator, "token": "fixture", "check_key": "fixture",
        "device_id": "fixture", "user_agent": "fixture",
    }))
    client._known_group_ids.add(str(fan))

    def request(method, path, *, json_body):
        assert (method, path) == ("POST", "/message"), (method, path)
        accepted = wire.hit("POST /message", json_body["groupId"])
        return {"id": str(accepted["id"]), "groupId": str(fan), "senderId": creator,
                "content": json_body["content"], "createdAt": time.time()}

    client._request = request
    return {"aid": aid, "fan": fan, "req": _req(aid), "client": client, "platform": "fansly"}


async def _restrict_ack(ctx):
    await _call_route(ctx, lambda srv: srv.of_restrict_user(
        ctx["fan"], ctx["req"], ack=True, hide=False))


def _recorded(ctx):
    return bool(db_row("SELECT 1 FROM messages WHERE account_id=? AND fan_id=?", (ctx["aid"], ctx["fan"])))


async def _nothing(ctx):
    return None


async def _plain_setup(aid: str, wire: Wire):
    await seed_account(aid)
    return {"aid": aid, "fan": 71002, "sid": 4242, "req": _req(aid), "client": wire.of_client(aid)}


async def _native_schedule(ctx):
    import server
    await _call_route(ctx, lambda srv: srv.of_schedule_message(
        ctx["fan"], ctx["req"], server._ScheduleMessageBody(
            text="see you later", scheduled_date="2099-01-01T10:00:00+00:00")))


async def _publish_now(ctx):
    await _call_route(ctx, lambda srv: asyncio.to_thread(srv.of_publish_schedule, ctx["sid"]))


def _mass(later: bool):
    async def send(ctx):
        import mass_queue_api as mq
        body = mq._MassScheduleBody(
            text="hello all", user_ids=[ctx["fan"]],
            scheduled_date="2099-01-01T10:00:00+00:00" if later else None)
        await _call_route(ctx, lambda srv: mq.of_send_or_schedule_mass(ctx["req"], body))
    return send


def _mass_status(ctx, want: str) -> bool:
    row = db_row("SELECT status FROM mass_runs WHERE account_id=? ORDER BY id DESC LIMIT 1",
                 (ctx["aid"],))
    return bool(row) and row[0] == want


def _vault_spool() -> None:
    import vault_upload
    if vault_upload.SPOOL_ROOT.name.startswith("send_kill_vault_"):
        return
    root = Path(tempfile.mkdtemp(prefix="send_kill_vault_"))
    vault_upload.SPOOL_ROOT = root
    vault_upload.LOCK_DIR = root / "locks"
    vault_upload.STAGE_ROOT = root / "incoming"
    vault_upload._MEMO_PATH = root / "drive_memo.json"


async def _vault_setup(aid: str, wire: Wire):
    import of_client
    _vault_spool()
    await seed_account(aid)
    fan = 71003

    def reads(method, path):
        if method == "GET" and path.rstrip("/").endswith("/users/vaultfan"):
            return {"id": fan, "username": "vaultfan", "name": "Vault Fan"}
        return {}
    c = wire.of_client(aid, reads=reads)
    c.upload_claim = lambda path: of_client.UploadClaim(
        media={"processId": f"p-{Path(path).name}"}, dedupe_key=Path(path).name, size=16)
    c.get_messages = lambda chat_id, *, before_id=None, **_: {
        "list": [{"id": int(before_id) - 1, "media": [{"id": 901, "isReady": True}]}]}
    return {"aid": aid, "fan": fan, "req": _req(aid), "client": c}


def _vault_item(ctx) -> dict:
    import vault_upload
    run = vault_upload.latest_run(ctx["aid"]) or {}
    return ((run.get("items") or [None])[0]) or {}


async def _vault_send(ctx):
    import auth
    import server
    import vault_import_api
    from starlette.datastructures import Headers, UploadFile
    import of_write
    of_write._write_gates.pop(ctx["aid"], None)
    spawned: list = []
    f = UploadFile(file=io.BytesIO(b"x" * 16), filename="a.jpg",
                   headers=Headers({"content-type": "image/jpeg"}))
    tok = auth._request_user.set(auth.AuthedUser("u_kill", "kill_owner", frozenset({ctx["aid"]})))
    try:
        with patch.object(server, "_spawn_bg", lambda coro, name: spawned.append(coro)):
            await _call_route(ctx, lambda srv: vault_import_api.of_vault_upload_batch(
                ctx["req"], files=[f], drive_links="", list_id="", meta="",
                fan_username="vaultfan", fan_id=str(ctx["fan"]), keep_open=False))
            for coro in spawned:
                await _call_route(ctx, lambda srv: coro)
    finally:
        auth._request_user.reset(tok)


async def _vault_sweep(ctx):
    import vault_upload
    await asyncio.to_thread(vault_upload.sweep, lambda aid: ctx["client"])


DRIVERS = [
    Driver(
        kind="composer",
        setup=_composer_setup,
        first=_composer_send,
        tick=_nothing,
        resend=_composer_send,
        pre_write="no local write before the POST (sends_inflight is memory only)",
        post_update=_recorded,
    ),
    Driver(
        kind="composer_shim", setup=_composer_shim_setup, first=_composer_send,
        tick=_nothing, resend=_composer_send, pre_write="the shim sends before recording locally",
        post_update=_recorded,
    ),
    Driver(
        kind="restrict_ack", setup=_plain_setup, first=_restrict_ack,
        tick=_nothing, resend=_restrict_ack, pre_write="restrict acknowledgement precedes the durable skip row",
        post_update=_recorded,
    ),
    Driver(
        kind="native_schedule",
        setup=_plain_setup,
        first=_native_schedule,
        tick=_nothing,
        resend=_native_schedule,
        pre_write="OF path is one _proxy POST /messages/queue, no local write",
        post_update="OF path returns OF's answer, writes no local row",
    ),
    Driver(
        kind="publish_now",
        setup=_plain_setup,
        first=_publish_now,
        tick=_nothing,
        resend=_publish_now,
        pre_write="one _proxy PUT /schedules/{id}/publish, no local write",
        post_update="returns OF's answer, writes no local row",
    ),
    Driver(
        kind="manual_mass_send",
        setup=_plain_setup,
        first=_mass(False),
        tick=_nothing,
        resend=_mass(False),
        pre_write=lambda ctx: _mass_status(ctx, "running"),
        post_update=lambda ctx: _mass_status(ctx, "ok"),
    ),
    Driver(
        kind="manual_mass_schedule",
        setup=_plain_setup,
        first=_mass(True),
        tick=_nothing,
        resend=_mass(True),
        pre_write=lambda ctx: _mass_status(ctx, "running"),
        post_update=("scheduled path skips _close_mass_run: the "
                     "mass_runs row stays 'running' after OF accepts, restart marks it "
                     "interrupted"),
    ),
    Driver(
        kind="vault_send",
        setup=_vault_setup,
        first=_vault_send,
        tick=_vault_sweep,
        resend=_vault_send,
        pre_write=lambda ctx: _vault_item(ctx).get("status") == "uploading",
        post_update=lambda ctx: _vault_item(ctx).get("message_id") is not None,
    ),
]
