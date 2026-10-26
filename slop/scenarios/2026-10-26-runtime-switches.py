"""Settings > System > Runtime switches: the master flips the relay's env kill
switches and caps from the UI (GET /admin/system/switches, PUT
/admin/system/switches/{env}), and the consumer acts on it at once, no restart.

Flow, one master (the run's owner, `users.is_admin` set by SQL as an operator
does; there is no API for it):
1. Storm: `--users` concurrent saves at once (each with the founder admin
   password, as the panel sends it), half on W7_WEBHOOK_DISPATCH_DISABLED
   (true / false mixed), half on SMART_LIST_MAX_ACTIVE (1..50).
   Invariants: every PUT 200; the relay's cache (GET's override and effective
   value) equals the stored runtime_switches row; one `actions` audit row per 200
   (nothing dropped); the cap's override reaches its consumer: GET
   /admin/smart-lists `max_active` matches, and with the cap set to (active + 2)
   two more activations pass and the third is refused 409. Then both are
   cleared: no row left, source back to default.
2. W7 from the UI (or the same PUTs with --no-ui): type the admin password,
   toggle the W7 row on, fans of
   one Creator DM it (POST /__slop/of-ws-frame, the pump's shape) and no W7
   dispatch job is queued; toggle it back off, which CLEARS the override (no
   stored `false` that would outrank a later env change), other fans DM and
   each gets exactly one. Creator 0 has the per-account webhook config on and an enabled
   welcome_chatter_for_info rule (SQL), so a dispatch is a pending
   `scheduled_jobs` row for that fan (the supervisor does not run in a slop
   stack, so it stays pending and is countable). Every DM lands in its thread.
   Screenshots: switches-before, switch-w7-on (the trigger, settled),
   switch-w7-cleared.

Fault `runtime-switch-env-bypass`: `_global_kill_switch` reads the env var
directly, as before this change, so the UI's override never reaches the
consumer. Only the "no dispatch while on" check goes red.
Budget: PUT p95 under the storm.
"""
from __future__ import annotations

import asyncio
import json

from slop.actors import fan_dm, manager, ui

PROFILE = "agency_inbox"
UI = True
FAULT = "runtime-switch-env-bypass"
SAVE_P95_MS = 1500   # PUT /admin/system/switches/{env}, --users of them at once
P95_VS_LAST = (2.0, 100)
W7, CAP = "W7_WEBHOOK_DISPATCH_DISABLED", "SMART_LIST_MAX_ACTIVE"
KIND = "welcome_chatter_for_info"
ADMIN_PW = "slop-admin-not-for-prod"   # slop/lib/stack.py's ADMIN_PASSWORD for the relay

CK_STORM_200 = "concurrent saves: every PUT /admin/system/switches answered 200"
CK_STORM_ROW = "concurrent saves: the relay's cache (GET override and effective value) equals the stored row"
CK_AUDIT = "concurrent saves: one actions audit row per 200 (nothing dropped)"
CK_CAP = ("the SMART_LIST_MAX_ACTIVE override reaches its consumer: GET /admin/smart-lists max_active"
          " matches, and activation past the cap is refused 409")
CK_CLEAR = "clear override: no runtime_switches row left, GET source back to default"
CK_OFF = "W7 switch on from Settings > System: no dispatch job for any DM sent while it is on"
CK_ON = "W7 override cleared: exactly one dispatch job per DM sent after"
CK_THREAD = "every DM of both phases landed in its thread (messages rows)"
CK_UI_ON = "UI: after the toggle the W7 row shows source override, effective on, the toggle on"
CK_UI_CLEAR = ("UI: toggling W7 back off clears the override: the row shows source default, effective off,"
               " the toggle off, and no runtime_switches row is left")
UI_CHECKS = (CK_UI_ON, CK_UI_CLEAR, "no 5xx in the browser session")


def _seed(w, aid: str) -> None:
    """The master role and W7's own gates for Creator `aid`: the per-account
    webhook config on (no delay) and an enabled welcome_chatter_for_info rule."""
    con = w.sql()
    with con:
        con.execute("UPDATE users SET is_admin=1 WHERE id=?", (w.user_id,))
        # The ORM's own defaults for the NOT NULL columns (no server default to lean on).
        con.execute("INSERT OR IGNORE INTO account_ai_config (account_id, utc_offset, daily_cost_cap_cents)"
                    " VALUES (?, 0, 100)", (aid,))
        con.execute("UPDATE account_ai_config SET webhook_config_json=? WHERE account_id=?",
                    (json.dumps({"enabled": True, "delay_seconds": 0, "jitter_seconds": 0}), aid))
        con.execute("INSERT INTO automation_rules (account_id, name, kind, trigger_json, steps_json, is_enabled,"
                    " created_at) VALUES (?, ?, ?, '{}', '{}', 1, CURRENT_TIMESTAMP)", (aid, KIND, KIND))
    con.close()


def _free_fans(w, aid: str) -> list[dict]:
    """Creator `aid`'s fans W7 would wake an automation for: not skip-listed, not mid-funnel."""
    con = w.sql()
    skip = {r[0] for r in con.execute("SELECT fan_id FROM skip_list WHERE account_id=?", (aid,))}
    skip |= {r[0] for r in con.execute("SELECT fan_id FROM funnel_state")}   # any funnel (no account column)
    con.close()
    return [f for f in w.data["fans"][aid] if f["id"] not in skip]


def _jobs(w, aid: str, fan_ids: set[int]) -> dict[int, int]:
    """Pending W7 dispatch jobs per fan (payload only_fan_ids)."""
    con = w.sql()
    out: dict[int, int] = {}
    for (payload,) in con.execute("SELECT payload_json FROM scheduled_jobs WHERE account_id=? AND kind=?",
                                  (aid, KIND)):
        for f in (json.loads(payload or "{}").get("only_fan_ids") or []):
            if f in fan_ids:
                out[f] = out.get(f, 0) + 1
    con.close()
    return out


def _rows(w) -> dict[str, list]:
    con = w.sql()
    out: dict[str, list] = {}
    for name, v in con.execute("SELECT name, value_json FROM runtime_switches"):
        out.setdefault(name, []).append(json.loads(v))
    con.close()
    return out


def _audit_rows(w, name: str) -> int:
    con = w.sql()
    n = con.execute("SELECT COUNT(*) FROM actions WHERE action=?", (f"PUT /admin/system/switches/{name}",)).fetchone()[0]
    con.close()
    return n


def _body(v) -> dict:
    return {"value": v, "admin_password": ADMIN_PW}


async def _cap_holds(ctx, aid: str, stormed: int) -> None:
    """GET max_active follows the storm's override; then cap = active + 2 lets two
    activations through and refuses the third (smart_lists_api's quota UPDATE)."""
    lists = (await ctx.owner.get(f"/admin/smart-lists?account_id={aid}")).json()
    active = sum(1 for x in lists.get("lists", []) if x.get("is_active"))
    cap = active + 2
    r = await ctx.owner.request("PUT", f"/admin/system/switches/{CAP}", json=_body(cap))
    r.raise_for_status()
    codes = []
    for i in range(3):
        made = await ctx.owner.request("POST", "/admin/smart-lists",
                                       json={"account_id": aid, "name": f"slop cap {cap} #{i}"})
        made.raise_for_status()
        codes.append((await ctx.owner.request("POST", f"/admin/smart-lists/{made.json()['id']}/activate")).status_code)
    ctx.check(CK_CAP, lists.get("max_active") == stormed and codes == [200, 200, 409],
              max_active=lists.get("max_active"), override=stormed, active_before=active, cap=cap,
              activate=codes)


async def _get(ctx, name: str) -> dict:
    body = (await ctx.owner.get("/admin/system/switches")).json()
    return next(k for k in body["switches"] if k["env"] == name)


async def _storm(ctx, w, aid: str) -> None:
    rng = w.rng("scenario:runtime-switches")
    n = ctx.users
    sends = [(W7, rng.random() < 0.5) if i % 2 == 0 else (CAP, 1 + (i // 2) % 50) for i in range(n)]
    pool = ctx.owner.share(limits=n)
    before = {W7: _audit_rows(w, W7), CAP: _audit_rows(w, CAP)}

    async def put(name, v):
        try:
            r = await pool.request("PUT", f"/admin/system/switches/{name}", json=_body(v))
            return r.status_code
        except Exception as e:   # transport error: recorded by the stock invariants too
            return repr(e)

    statuses = await asyncio.gather(*(put(name, v) for name, v in sends))
    await pool.aclose()
    ok = [s for s in statuses if s == 200]
    ctx.metric("storm", {"saves": n, "ok": len(ok), "w7": sum(1 for s in sends if s[0] == W7),
                         "cap": sum(1 for s in sends if s[0] == CAP)})
    ctx.check(CK_STORM_200, len(ok) == n, answered_200=len(ok), n=n,
              other=sorted({str(s) for s in statuses if s != 200})[:5])

    rows = _rows(w)
    got = {name: await _get(ctx, name) for name in (W7, CAP)}
    bad = {}
    for name in (W7, CAP):
        db = rows.get(name, [None])[0]
        g = got[name]
        if not (db is not None and db == g["override"] == g["effective"] and g["source"] == "override"):
            bad[name] = {"db": db, "override": g["override"], "effective": g["effective"], "source": g["source"]}
    ctx.check(CK_STORM_ROW, not bad, bad=bad, rows={k: v for k, v in rows.items()})

    audit = {name: _audit_rows(w, name) - before[name] for name in (W7, CAP)}
    want = {name: sum(1 for (nm, _), s in zip(sends, statuses) if nm == name and s == 200) for name in (W7, CAP)}
    ctx.check(CK_AUDIT, audit == want, audit=audit, want=want)

    await _cap_holds(ctx, aid, got[CAP]["effective"])

    for name in (W7, CAP):
        r = await ctx.owner.request("PUT", f"/admin/system/switches/{name}", json=_body(None))
        r.raise_for_status()
    rows = _rows(w)
    after = {name: (await _get(ctx, name))["source"] for name in (W7, CAP)}
    ctx.check(CK_CLEAR, not rows.get(W7) and not rows.get(CAP) and set(after.values()) == {"default"},
              rows=rows, source=after)


async def _dms(ctx, fans: list[dict], ids, text: str) -> list[dict]:
    recs = await fan_dm.serial(ctx.owner, fans, 1, ids=ids, text=text)
    await manager.quiesce(ctx.owner)
    return [r for r in recs if r["status"] < 300]


async def _wait_jobs(w, aid: str, fan_ids: set[int], want: int | None, timeout: float) -> dict[int, int]:
    """Poll until `want` fans have a job (None: wait the whole `timeout`, for a negative check)."""
    t0 = asyncio.get_running_loop().time()
    while True:
        got = _jobs(w, aid, fan_ids)
        if want is not None and len(got) >= want:
            await asyncio.sleep(0.5)   # a second job per fan would land now
            return _jobs(w, aid, fan_ids)
        if asyncio.get_running_loop().time() - t0 > timeout:
            return got
        await asyncio.sleep(0.25)


async def _source_shows(row, text: str) -> None:
    """Wait for the row's Source cell to read `text`; a timeout is left to the UI check to judge."""
    try:
        await row.get_by_test_id("switch-source").filter(has_text=text).wait_for(timeout=15_000)
    except Exception:
        pass


async def _row_state(page, checked: str) -> dict:
    """The W7 row once its toggle reads `checked` and its 150 ms slide has ended (a settled screenshot)."""
    row = page.get_by_test_id(f"switch-{W7}")
    toggle = row.get_by_role("switch", name=W7)
    try:
        await row.locator(f"[role='switch'][aria-checked='{checked}']").wait_for(timeout=10_000)
    except Exception:
        pass
    await page.wait_for_timeout(400)
    return {"source": (await row.get_by_test_id("switch-source").inner_text()).strip(),
            "effective": (await row.get_by_test_id("switch-effective").inner_text()).strip(),
            "toggle": await toggle.get_attribute("aria-checked")}


async def _section_to_top(page) -> None:
    await page.get_by_text("Runtime switches", exact=True).evaluate("e => e.scrollIntoView({block: 'start'})")
    await page.wait_for_timeout(300)


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    aid = w.data["creators"][0]["id"]
    _seed(w, aid)
    k = ctx.param("dm_fans", {"small": 5, "medium": 20, "huge": 40}[ctx.scale])
    fans = _free_fans(w, aid)
    off_fans, on_fans = fans[:k], fans[k:2 * k]
    ctx.metric("w7_phase", {"account": aid, "fans_off": len(off_fans), "fans_on": len(on_fans)})

    await _storm(ctx, w, aid)

    ids = iter(range(fan_dm.INJECT_ID_BASE + 7_000_000, fan_dm.INJECT_ID_BASE + 8_000_000))
    sent: list[dict] = []
    page_cm = ui.owner_browser(ctx, viewport=(1440, 1000)) if ctx.app else None
    page = await page_cm.__aenter__() if page_cm else None
    try:
        if page:
            await page.goto(f"{ctx.app}/settings/system", wait_until="domcontentloaded")
            row = page.get_by_test_id(f"switch-{W7}")
            await row.wait_for(timeout=120_000)
            await page.get_by_label("Admin password").fill(ADMIN_PW)
            await _section_to_top(page)
            await ui.shot(ctx, page, "switches-before")
            async with page.expect_response(lambda r: r.request.method == "PUT" and f"/admin/system/switches/{W7}" in r.url):
                await row.get_by_role("switch", name=W7).click()
            await _source_shows(row, "override")
            st = await _row_state(page, "true")
            await _section_to_top(page)
            await ui.shot(ctx, page, "switch-w7-on")
            ctx.check(CK_UI_ON, st["source"].startswith("override") and st["effective"].startswith("on")
                      and st["toggle"] == "true", **st)
        else:
            r = await ctx.owner.request("PUT", f"/admin/system/switches/{W7}", json=_body(True))
            r.raise_for_status()

        sent += await _dms(ctx, off_fans, ids, "w7 off phase")
        off_jobs = await _wait_jobs(w, aid, {f["id"] for f in off_fans}, None, timeout=3.0)

        if page:
            row = page.get_by_test_id(f"switch-{W7}")
            async with page.expect_response(lambda r: r.request.method == "PUT" and f"/admin/system/switches/{W7}" in r.url):
                await row.get_by_role("switch", name=W7).click()
            await _source_shows(row, "default")
            st = await _row_state(page, "false")
            await _section_to_top(page)
            await ui.shot(ctx, page, "switch-w7-cleared")
            stored = _rows(w).get(W7)
            ctx.check(CK_UI_CLEAR, st["source"] == "default" and st["effective"].startswith("off")
                      and st["toggle"] == "false" and not stored, stored=stored, **st)
            relay_5xx = [u for s, u in page.slop["statuses"] if s >= 500 and "/api/of/" not in u]
            ctx.check(UI_CHECKS[2], not relay_5xx, count=len(relay_5xx), sample=relay_5xx[:5])
        else:
            for c in UI_CHECKS:
                ctx.skip(c, "--no-ui")
            r = await ctx.owner.request("PUT", f"/admin/system/switches/{W7}", json=_body(None))
            r.raise_for_status()

        sent += await _dms(ctx, on_fans, ids, "w7 on phase")
        on_jobs = await _wait_jobs(w, aid, {f["id"] for f in on_fans}, len(on_fans), timeout=15.0)
    finally:
        if page_cm:
            await page_cm.__aexit__(None, None, None)

    ctx.metric("w7_jobs", {"off_phase": off_jobs, "on_phase": on_jobs})
    ctx.check(CK_OFF, len(off_fans) > 0 and not off_jobs, fans=len(off_fans), jobs=off_jobs)
    ctx.check(CK_ON, len(on_fans) > 0 and len(on_jobs) == len(on_fans) and set(on_jobs.values()) == {1},
              fans=len(on_fans), with_job=len(on_jobs), counts=sorted(set(on_jobs.values())))

    con = w.sql()
    have = {r[0] for r in con.execute(
        f"SELECT message_id FROM messages WHERE account_id=? AND message_id IN ({','.join('?' * len(sent))})",
        (aid, *[s["message_id"] for s in sent]))} if sent else set()
    con.close()
    want = 2 * k
    ctx.check(CK_THREAD, len(sent) == want and len(have) == want, sent=len(sent), stored=len(have), want=want)

    routes = ctx.rec.summary()
    puts = [v for r, v in routes.items() if r.startswith("PUT /admin/system/switches/")]
    name = f"p95 PUT /admin/system/switches/{{env}} under {ctx.users} concurrent saves < {SAVE_P95_MS}ms"
    if puts:
        p95 = max(v["p95_ms"] for v in puts)
        ctx.check(name, p95 < SAVE_P95_MS, budget=True, p95=p95, n=sum(v["n"] for v in puts))
        ctx.metric("p95_vs_last_green", {"PUT /admin/system/switches": p95})
    else:
        ctx.skip(name, "no samples")
