"""Vault Pro's Jev v8 flags pass (service/vault_jev.py: TypeSafe Jev + NudeNet, per-Creator opt-in) as an operator
meets it: Jev switched on for one Creator, then describe-all and flags-all over every Creator's vault, on the real
relay routes.

World: `agency_inbox` plus seed/vault_items_describe.py (`--set items=`, SCALES `vault_jev_items` 90 / 600 / 2,000),
armed as in 2026-11-01-vault-describe-sweep (DeepInfra fake, still stores, the Agency's dummy key through
`PUT /admin/my-llm-keys`), with two changes made here between the seeder's plan and its write:
  - every photo gets a unique size with both edges in [280, 448], so each Jev pass sends the still at that size
    (lib/vault_jev_relay.py says why) and both fakes tell items apart by it; clips and audio keep the seeder's.
  - every photo gets a Jev profile (lib/vault_jev_relay.py `PROFILES`): what the fake TypeSafe answers about it.
    Per Creator round robin over its photos, a planted re-upload set one profile for all its members (the same
    picture). Creator 0 must hold every profile (raises otherwise: raise `--set items=`).
Toggle (as Vault Pro > Extras' VaultJevToggle does: GET /admin/account-config, PUT it back with only
`vault_jev_enabled` changed): Creator 0 on; Creator 1 on, then off again; the rest never touched. The describe plan
(`GET /admin/vault-ai/describe-all/plan`, its `jev` block) must say Creator 0 is on and ready (NudeNet loaded, key
set) before anything is pressed, else the run stops (INFRA, not a verdict).

Phases (the describe sweep's `_phase`: `--users` owner tabs poll the status route every 2.5 s while it runs):
  pass1  describe-all for every Creator at once: on Creator 0 each photo the sweep visits gets Jev first.
  flags  flags-all {force} for every Creator at once: Creator 0's photos with no `_jev` yet (the seeded earlier
         describes) get Jev there; a re-upload copy gets its set's.

Planned lanes (`WANT`), from what the planted answers say, never from the product's rules. NudeNet is the
product's own (640m.onnx, `NUDENET_640M_PATH`); the seeded stills are flat colour, on which it detects nothing
(measured: no class on 20 flat stills 280-448 px), so every profile is planned with NudeNet at 0.
  none        dressed, nothing bare                              -> free  (pass 1)
  pen         something inserted (.95)                           -> $100  (pass 1)
  vulva       bare vulva (.95)                                   -> $50   (pass 1)
  nipple      topless (.95), crotch dressed                      -> $10   (pass 1)
  lower       topless, crotch hidden; the lower crop: bare vulva -> $50   (pass 1, L)
  p2_clear    nipple a coin flip at 1024 px, plainly at 1568     -> $10   (pass 1, 2)
  unsure      nipple a coin flip at every size, NudeNet nothing  -> free, settled  (pass 1, 2; owner D42: a review
              photo NudeNet sees nothing on settles free)
  pen_unsure  insertion a coin flip at every size                -> $100, settled  (pass 1, 2; D42: an unsure
              insertion settles $100)

Jev-fed describe (service/vault_describe_jev.py, D51), planned from the same answers: the coin flips (unsure,
pen_unsure) stay in review -> the v6 recipe (V2 + facts + hedge, 960 px); every other on-Creator photo -> the prose
recipe (640 px), whose fake answer claims nipples, pussy AND insertion (lib/vault_describe_relay.py `PROSE_CLAIMS`):
its `clothing_items` stored as the fake named them (`PROSE_GARMENTS`), and
the stored description must keep exactly the claims its answers spell (`SAYS`: pen -> inserted, vulva -> pussy,
nipple / p2_clear -> nipples, lower -> nipples + pussy, none -> nothing). Everything else keeps today's V2 describe.

UI (after the sweeps and their checks, so it changes none of them; one owner, Chromium 1440x900): Vault Pro on a
Creator never switched on (Creator 2, else Creator 1), Extras open; screenshot `vault-jev-toggle-off-trigger` (the
"Jev v8 flags" switch off), one click, wait for the switch to settle on; screenshot `vault-jev-toggle-on-settled`.
Side effects read back: the config route's `vault_jev_enabled`, the describe plan's `jev` (enabled + ready, the
readiness the drawer shows: no "Jev is refusing" line), the account_ai_config row. Left on: nothing runs after it.

Checks (names in lib/vault_jev_faults.py): JEV_ONLY_WHEN_ON, JEV_LANES, JEV_BEFORE_DESCRIBE, JEV_COST, JEV_COPY,
JEV_DESCRIBE_PROSE, JEV_DESCRIBE_REVIEW, JEV_DESCRIBE_OFF, JEV_UI_TOGGLE (SKIP with --no-ui), the
status routes' p95 budgets and p95 vs last green (the describe sweep's `STATUS_P95_MS`, `_check_budgets`), plus the
stock no 5xx / no unexpected Traceback. `SLOP_LIVE=1`: every check SKIPs.

Bypasses (declared; the describe sweep's DeepInfra / stills / SQL-vault ones apply unchanged):
  - TypeSafe is lib/vault_jev_relay.py's fake at its System One wire (the product's real `typesafe_sdk` client,
    `TYPESAFE_BASE_URL` → the relay's loopback route; key, cap reservation, grok_calls rows, NudeNet, rules and
    storage are the product's). Answers by item profile and question set; `--set jev_latency_s=` (0.1 s) per call.
  - NudeNet's weights are read from `NUDENET_640M_PATH` (default /tmp/nn-weights/640m.onnx, md5 checked by the
    product); the stills are synthetic, so NudeNet's veto / promote never fire here (blind spot, declared).
  - Photo sizes are the scenario's (above), not the seeder's.
  - The phase helpers are the describe sweep's own, loaded from its file (one copy, not a fork).

Break-it-once: `vault-jev-ignores-setting` (the FAULT: `vault_jev_pass.enabled` always on) turns only JEV_ONLY_WHEN_ON red;
`--fault=vault-jev-no-settle` (settle nn.10 skipped) only JEV_LANES; `--fault=vault-jev-after-describe` (Jev after
describe + flags) only JEV_BEFORE_DESCRIBE; `--fault=vault-jev-describe-ignores-review` (the describe routes a review
photo to the prose recipe) only JEV_DESCRIBE_REVIEW.
"""
# No `from __future__ import annotations` (lib/cli.py loads a scenario outside sys.modules; see the describe sweep).
import importlib.util
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from slop.lib.vault_describe_relay import FAKE_KEY, PROSE_CLAIMS, PROSE_GARMENTS, arm_run, describe_text
from slop.lib.vault_jev_faults import (
    JEV_BEFORE_DESCRIBE, JEV_COPY, JEV_COST, JEV_DESCRIBE_OFF, JEV_DESCRIBE_PROSE, JEV_DESCRIBE_REVIEW, JEV_LANES,
    JEV_ONLY_WHEN_ON, JEV_UI_TOGGLE,
)
from slop.lib.vault_jev_relay import PROFILES, arm_jev
from slop.seed import vault_items_describe


def _load_sweep():
    path = Path(__file__).with_name("2026-11-01-vault-describe-sweep.py")
    spec = importlib.util.spec_from_file_location("slop_vault_describe_sweep_helpers", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load_sweep()

PROFILE = "agency_inbox"
UI = True
FAULT = "vault-jev-ignores-setting"
NUDENET = os.environ.get("NUDENET_640M_PATH") or "/tmp/nn-weights/640m.onnx"
RELAY_ENV = {"NUDENET_640M_PATH": NUDENET}
P95_VS_LAST = S.P95_VS_LAST
P95_VS_LAST_MIN_N = S.P95_VS_LAST_MIN_N
CONFIG = "/admin/account-config"
JEV_COUNT, JEV_CALLS = "/__slop/vault-jev/count", "/__slop/vault-jev/calls"
CHECKS = (JEV_ONLY_WHEN_ON, JEV_LANES, JEV_BEFORE_DESCRIBE, JEV_COST, JEV_COPY, JEV_DESCRIBE_PROSE, JEV_DESCRIBE_REVIEW,
          JEV_DESCRIBE_OFF, JEV_UI_TOGGLE)
# profile -> (lane5, passes the fake must see, settled); the module docstring says why each.
WANT = {"none": ("free", ["1"], False), "pen": ("$100", ["1"], False), "vulva": ("$50", ["1"], False),
        "nipple": ("$10", ["1"], False), "lower": ("$50", ["1", "L"], False),
        "p2_clear": ("$10", ["1", "2"], False), "unsure": ("free", ["1", "2"], "nn.10"),
        "pen_unsure": ("$100", ["1", "2"], "nn.10")}
assert set(WANT) == set(PROFILES)
# Jev-fed describe (D51), from the same planted answers: the coin flips stay in review (v6 recipe); every other
# profile gets the prose recipe and keeps exactly the claims its answers spell (`PROSE_CLAIMS` keys).
REVIEW_PROFILES = {"unsure", "pen_unsure"}
SAYS = {"none": set(), "pen": {"pen"}, "vulva": {"vulva"}, "nipple": {"nipple"}, "lower": {"nipple", "vulva"},
        "p2_clear": {"nipple"}}
assert set(SAYS) | REVIEW_PROFILES == set(WANT)
PX = {"prose": 640, "v6": 960}
# TypeSafe Jev 1.14: $0.042 per million input tokens, output free (docs.typesafe.ai/models, read 11-11), in the
# cap unit (1 cent = 100 millicents): 0.042 * 100 * 100 / 1e6 = 42 / 100,000 per token, rounded up per photo.
MC_PER_TOKEN = (42, 100_000)
PHOTO_EDGE = (280, 448)


def _price(tokens: int) -> int:
    n, d = MC_PER_TOKEN
    return -(-tokens * n // d)


def _sizes(items) -> None:
    """Every photo a unique size, both edges in PHOTO_EDGE (module docstring)."""
    lo, hi = PHOTO_EDGE
    span = hi - lo + 1
    photos = [it for it in items if it["kind"] == "photo"]
    if len(photos) > span * span:
        raise ValueError(f"slop: {len(photos)} photos > {span * span} sizes in {PHOTO_EDGE}")
    for j, it in enumerate(photos):
        it["size"] = (lo + j % span, lo + j // span)


def _profiles(items) -> None:
    """Per Creator, round robin of WANT's profiles over its photo units (a planted set is one unit)."""
    names = list(WANT)
    units: dict = defaultdict(dict)
    for it in items:
        if it["kind"] == "photo":
            units[it["account_id"]].setdefault(it["dupe_set"] or it["key"], []).append(it)
    for us in units.values():
        for k, members in enumerate(us.values()):
            for it in members:
                it["jev"] = names[k % len(names)]


async def _toggle(ctx, aid: str, on: bool) -> dict:
    """VaultJevToggle's save: the stored config back with only `vault_jev_enabled` changed."""
    got = await ctx.owner.get(f"{CONFIG}?account_id={aid}")
    cfg = got.json()["config"] if got.status_code == 200 else {}
    put = await ctx.owner.put(CONFIG, json={"account_id": aid, "config": {**cfg, "vault_jev_enabled": on}})
    back = await ctx.owner.get(f"{CONFIG}?account_id={aid}")
    stored = back.json()["config"].get("vault_jev_enabled") if back.status_code == 200 else None
    return {"want": on, "get": got.status_code, "put": put.status_code, "stored": stored,
            **({"put_body": put.text[:300]} if put.status_code != 200 else {})}


async def _jev_count(ctx) -> int:
    return (await ctx.owner.get(JEV_COUNT)).json()["n"]


async def _jev_calls(ctx, since: int) -> list[dict]:
    return (await ctx.owner.get(f"{JEV_CALLS}?since={since}")).json()["calls"]


def _key(c: dict) -> str | None:
    return vault_items_describe.key(c["account_id"], c["media_id"]) if c["account_id"] is not None else None


def _by_item(calls) -> dict:
    out = defaultdict(list)
    for c in calls:
        if _key(c):
            out[_key(c)].append(c)
    return out


def _jev_of(row: dict) -> dict | None:
    j = (row["ai"] or {}).get("_jev")
    return j if isinstance(j, dict) else None


def _sql(ctx, q: str) -> list:
    con = ctx.world.sql()
    try:
        return con.execute(q).fetchall()
    finally:
        con.close()


async def _ui_toggle(ctx, creator: dict) -> dict:
    """Vault Pro > Extras > "Jev v8 flags" for an off Creator: trigger shot (off), one click, settled shot (on)."""
    aid, ui = creator["id"], S.ui
    got: dict = {"account_id": aid, "puts": []}
    async with ui.owner_browser(ctx, viewport=S.VIEWPORT) as page:
        await page.context.add_init_script(S.TOURS_SEEN)
        await page.route(S.IMG, lambda r: r.abort())  # the grid's OF CDN tiles: OF is unreachable (declared)
        page.on("response", lambda r: got["puts"].append(r.status) if r.request.method == "PUT"
                and r.url.split("?")[0].endswith(CONFIG) else None)
        try:
            await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=S.WAIT_MS)
            await ui.pick_creator(page, creator["nickname"], timeout_ms=S.WAIT_MS)
            await page.get_by_role("button", name=re.compile(r" extras$")).first.click(timeout=S.WAIT_MS)
            sw = page.get_by_role("switch", name="Jev v8 flags")
            await sw.wait_for(timeout=S.WAIT_MS)
            await page.wait_for_timeout(700)  # the drawer's slide-in
            got["trigger_checked"] = await sw.get_attribute("aria-checked")
            got["trigger_shot"] = await ui.shot(ctx, page, "vault-jev-toggle-off-trigger")
            await sw.click(timeout=10_000)
            await page.locator("[role='switch'][aria-label='Jev v8 flags'][aria-checked='true']:not([aria-busy])"
                               ).wait_for(timeout=30_000)
            await page.wait_for_timeout(1000)  # the plan refetch (readiness) after the save
            got["settled_checked"] = await sw.get_attribute("aria-checked")
            got["settled_text"] = (await page.get_by_test_id("vault-jev-toggle").inner_text()).strip()
            got["settled_shot"] = await ui.shot(ctx, page, "vault-jev-toggle-on-settled")
        except Exception as e:  # noqa: BLE001 — the check reports it
            got["error"] = f"{type(e).__name__}: {e}"[:600]
            try:
                got["failed_shot"] = await ui.shot(ctx, page, "failed-vault-jev-toggle")
            except Exception:  # noqa: BLE001
                pass
    cfg = await ctx.owner.get(f"{CONFIG}?account_id={aid}")
    got["config_stored"] = cfg.json()["config"].get("vault_jev_enabled") if cfg.status_code == 200 else None
    got["plan_jev"] = (await S._plans(ctx, [aid]))[aid].get("jev")
    got["db_row"] = [None if v is None else bool(v) for (v,) in _sql(
        ctx, f"SELECT vault_jev_enabled FROM account_ai_config WHERE account_id = '{aid}'")]
    return got


def _check_ui(ctx, got: dict | None, pre: dict | None) -> None:
    if got is None:
        ctx.skip(JEV_UI_TOGGLE, "--no-ui")
        return
    jev = got.get("plan_jev") or {}
    ctx.check(JEV_UI_TOGGLE, not got.get("error") and (pre or {}).get("stored") in (None, False)
              and got.get("trigger_checked") == "false" and got.get("settled_checked") == "true"
              and got.get("puts") == [200] and "Jev is refusing" not in got.get("settled_text", "")
              and got.get("config_stored") is True and jev.get("enabled") is True and jev.get("ready") is True
              and got.get("db_row") == [True], **got, config_before=pre)


async def run(ctx) -> None:
    if os.environ.get("SLOP_LIVE") == "1":
        for c in CHECKS:
            ctx.skip(c, "SLOP_LIVE=1: this scenario runs on the TypeSafe / DeepInfra fakes only")
        return
    if not Path(NUDENET).is_file():
        raise RuntimeError(f"slop: NudeNet weights not at {NUDENET} (set NUDENET_640M_PATH): Jev refuses without them")
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    aids = [c["id"] for c in creators]
    on_aid, flip_aid = aids[0], aids[1]
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepinfra": FAKE_KEY})
    ctx.metric("agency_deepinfra_key", {"status": r.status_code})

    t0 = time.time()
    items = vault_items_describe.plan(w, creators, ctx.param("items", w.size["vault_jev_items"]))
    _sizes(items)
    _profiles(items)
    missing = set(WANT) - {it["jev"] for it in items if it["account_id"] == on_aid and it.get("jev")}
    if missing:
        raise ValueError(f"slop: Creator 0 got no photo for profiles {sorted(missing)}; raise --set items=")
    armed = await arm_run(ctx.owner, ctx.stack.tmp, items, ctx.param("llm_latency_s", 0.05))
    await arm_jev(ctx.owner, ctx.stack.tmp, items, ctx.param("jev_latency_s", 0.1))
    await vault_items_describe.seed(w, items, armed)
    by_key = {i["key"]: i for i in items}
    ctx.metric("vault_seed", {"seconds": round(time.time() - t0, 2), "items": len(items),
                              "on_photos": dict(Counter(it["jev"] for it in items
                                                        if it["account_id"] == on_aid and it.get("jev")))})

    toggles = {"on": await _toggle(ctx, on_aid, True), "flip_on": await _toggle(ctx, flip_aid, True),
               "flip_off": await _toggle(ctx, flip_aid, False)}
    plans0 = await S._plans(ctx, aids)
    jev_plan = {aid: plans0[aid].get("jev") for aid in aids}
    if not (jev_plan[on_aid] or {}).get("ready"):
        raise RuntimeError(f"slop: Jev not ready on the relay for Creator 0: {jev_plan[on_aid]} (toggles {toggles})")

    async def press_describe() -> "S.Pressed":
        plan = await S._plans(ctx, aids)
        res = await S._post_all(ctx, S.DESCRIBE, aids, lambda a: {"account_id": a})
        return S.Pressed({aid: S._undesc(plan[aid]) for aid in aids}, {a: x.status_code for a, x in res.items()},
                         plan)

    async def press_flags() -> "S.Pressed":
        res = await S._post_all(ctx, S.FLAGS_ALL, aids, lambda a: {"account_id": a, "force": True})
        starts = {a: {**(x.json() if x.status_code == 200 else {}), "http": x.status_code} for a, x in res.items()}
        return S.Pressed({a: int(s.get("candidates") or 0) for a, s in starts.items()}, starts)

    n0 = await _jev_count(ctx)
    p1 = await S._phase(ctx, "pass1", S.STATUS, aids, press_describe)
    j1 = await _jev_calls(ctx, n0)
    pf = await S._phase(ctx, "flags", S.FLAGS_STATUS, aids, press_flags)
    jf = await _jev_calls(ctx, n0 + len(j1))
    ctx.rec.stage = None
    phases = ((p1, j1), (pf, jf))
    every = j1 + jf
    for p, jc in phases:
        (ctx.out / f"calls-{p.stage}.json").write_text(json.dumps(p.calls))
        (ctx.out / f"calls-jev-{p.stage}.json").write_text(json.dumps(jc))
    on_photos = [it for it in items if it["account_id"] == on_aid and it["kind"] == "photo"]
    (ctx.out / "jev-rows.json").write_text(json.dumps(
        {it["key"]: {"profile": it["jev"], "want": WANT[it["jev"]], "dupe_set": it["dupe_set"],
                     "cached": it["cached"], "_jev": _jev_of(pf.rows[it["key"]])} for it in on_photos},
        indent=1, default=str))
    (ctx.out / "sweep-status.json").write_text(json.dumps(
        {"toggles": toggles, "jev_plan": jev_plan, **{p.stage: {"want": p.want, "presses": p.presses,
                                                                "status": p.status} for p, _ in phases}},
        indent=2, default=str))
    timed_out = p1.timed_out + pf.timed_out
    presses_bad = {f"{p.stage}:{a}": s for p, _ in phases for a, s in p.presses.items()
                   if (s if isinstance(s, int) else s.get("http")) != 200}

    # JEV_ONLY_WHEN_ON
    wrong_calls = [c for c in every if c["account_id"] != on_aid
                   or (by_key.get(_key(c)) or {}).get("kind") != "photo"]
    wrong_rows = [k for k, row in pf.rows.items() if _jev_of(row) is not None
                  and (by_key[k]["account_id"] != on_aid or by_key[k]["kind"] != "photo")]
    plan_bad = {aid: jev_plan[aid] for aid in aids if bool((jev_plan[aid] or {}).get("enabled")) != (aid == on_aid)}
    toggle_bad = {k: t for k, t in toggles.items() if t["put"] != 200 or t["stored"] is not t["want"]}
    ctx.check(JEV_ONLY_WHEN_ON, bool(every) and not wrong_calls and not wrong_rows and not plan_bad and not toggle_bad,
              calls=len(every), wrong_calls=len(wrong_calls),
              wrong_by_creator=dict(Counter(str(c["account_id"]) for c in wrong_calls)),
              sample=wrong_calls[:3], wrong_rows=wrong_rows[:5], n_wrong_rows=len(wrong_rows), plan_bad=plan_bad,
              toggles=toggles)

    # JEV_LANES
    own = _by_item(every)
    stray = [c for c in every if c["status"] != 200 or not c["auth"] or not c["danger"]]
    bad, paid_profiles = {}, Counter()
    for it in on_photos:
        lane, passes, settled = WANT[it["jev"]]
        j, seen = _jev_of(pf.rows[it["key"]]), [c["pass"] for c in own.get(it["key"], [])]
        if seen:
            paid_profiles[it["jev"]] += 1
        good = (j is not None and j.get("status") == "ok" and j.get("lane5") == lane
                and j.get("settled") == settled and (seen == passes and j.get("passes") == passes
                                                     or (not seen and it["dupe_set"] is not None)))
        if not good:
            bad[it["key"]] = {"profile": it["jev"], "want": [lane, passes, settled], "seen": seen,
                              "jev": {k: (j or {}).get(k) for k in ("status", "lane5", "lane", "settled", "passes",
                                                                    "error")}}
    pass_n = Counter(c["pass"] for c in every)
    ctx.check(JEV_LANES, bool(on_photos) and not bad and not stray and set(paid_profiles) == set(WANT)
              and pass_n["2"] > 0 and pass_n["L"] > 0 and not timed_out and not presses_bad,
              photos=len(on_photos), bad=len(bad), sample=dict(list(bad.items())[:5]), stray=stray[:5],
              paid_by_profile=dict(paid_profiles), passes=dict(pass_n), timed_out=timed_out,
              presses_not_200=presses_bad)

    # JEV_BEFORE_DESCRIBE
    d1, o1 = p1.by_item("describe"), _by_item(j1)
    describe_t = defaultdict(list)
    for c in p1.calls:
        if c["purpose"] == "describe" and c["account_id"] is not None:
            describe_t[vault_items_describe.key(c["account_id"], c["media_id"])].append(c["t"])
    order_bad = {}
    for it in on_photos:
        if it["key"] in d1:
            jt = [c["t"] for c in o1.get(it["key"], [])]
            if not jt or max(jt) >= min(describe_t[it["key"]]):
                order_bad[it["key"]] = {"jev_t": jt, "describe_t": describe_t[it["key"]]}
    n_described = sum(1 for it in on_photos if it["key"] in d1)
    ctx.check(JEV_BEFORE_DESCRIBE, n_described > 0 and not order_bad, described_photos=n_described,
              bad=len(order_bad), sample=dict(list(order_bad.items())[:5]))

    # JEV_COST
    def priced(calls) -> Counter:
        tok, out = Counter(), Counter()
        for c in calls:
            if _key(c):
                tok[(c["account_id"], _key(c))] += c["tokens_in"]
        for (aid, _), t in tok.items():
            out[aid] += _price(t)
        return out

    sweeps = {}
    for p, jc in phases:
        want_jev, di = priced(jc), p.billed("describe", "flags")
        sweeps[p.stage] = {aid: {"jev_reported": S._prog(p.status[aid]).get("jev_cost_millicents", 0),
                                 "jev_billed": want_jev[aid], "total_reported": p.reported(aid),
                                 "total_billed": di[aid] + want_jev[aid]} for aid in aids}
    rows = {a: [int(c or 0), int(n or 0)] for a, c, n in _sql(
        ctx, "SELECT account_id, SUM(cost_cents), SUM(call_count) FROM grok_daily_cost WHERE provider = 'typesafe' "
             "GROUP BY account_id")}
    audit = {a: [int(c or 0), int(t or 0), int(n)] for a, c, t, n in _sql(
        ctx, "SELECT account_id, SUM(cost_cents), SUM(tokens_in), COUNT(*) FROM grok_calls WHERE provider = "
             "'typesafe' AND purpose = 'vault_jev_flags' AND status = 'done' GROUP BY account_id")}
    total, tokens = priced(every), Counter()
    for c in every:
        if _key(c):
            tokens[c["account_id"]] += c["tokens_in"]
    paid_items = Counter(by_key[k]["account_id"] for k in own)
    spend = {aid: {"billed": total[aid], "daily_row": rows.get(aid, [0, 0])[0],
                   "audit": audit.get(aid, [0, 0, 0]), "tokens": tokens[aid], "photos_paid": paid_items[aid]}
             for aid in aids}
    ok_sweeps = all(v["jev_reported"] == v["jev_billed"] and v["total_reported"] == v["total_billed"]
                    for s in sweeps.values() for v in s.values())
    ok_spend = all(s["daily_row"] == s["billed"] and s["audit"] == [s["billed"], s["tokens"], s["photos_paid"]]
                   for s in spend.values())
    ctx.check(JEV_COST, total[on_aid] > 0 and ok_sweeps and ok_spend, sweeps=sweeps, spend=spend,
              billed_mc=sum(total.values()))

    # JEV_COPY
    sets = defaultdict(list)
    for it in on_photos:
        if it["dupe_set"]:
            sets[it["dupe_set"]].append(it)
    copy_bad, n_copies = {}, 0
    for sid, ms in sets.items():
        paid = [m for m in ms if m["key"] in own]
        ids = {m["media_id"] for m in ms}
        src = _jev_of(pf.rows[paid[0]["key"]]) if len(paid) == 1 else None
        wrong = []
        for m in ms:
            if m in paid:
                continue
            ai = pf.rows[m["key"]]["ai"] or {}
            marks = {ai.get(S.COPY_MARK), ai.get(S.FLAGS_COPY_MARK)} & ids
            if src is None or _jev_of(pf.rows[m["key"]]) != src or not marks:
                wrong.append({"media_id": m["media_id"], "marks": [ai.get(S.COPY_MARK), ai.get(S.FLAGS_COPY_MARK)],
                              "lane5": (_jev_of(pf.rows[m["key"]]) or {}).get("lane5")})
            else:
                n_copies += 1
        if len(paid) != 1 or wrong:
            copy_bad[sid] = {"members": sorted(ids), "paid": [m["media_id"] for m in paid], "wrong": wrong}
    ctx.check(JEV_COPY, n_copies > 0 and not copy_bad, sets=len(sets), copies=n_copies,
              bad=dict(list(copy_bad.items())[:5]))

    # JEV_DESCRIBE_PROSE / _REVIEW / _OFF: pass 1's own describe calls (copies and blanks have none / no row)
    dcalls = defaultdict(list)
    for c in p1.calls:
        if c["purpose"] == "describe" and _key(c):
            dcalls[_key(c)].append(c)
    groups = {"prose": {}, "v6": {}, "v2": {}}
    for k, cs in dcalls.items():
        it, row = by_key[k], p1.rows[k]
        if row["status"] != "described":
            continue
        on = it["account_id"] == on_aid and it["kind"] == "photo"
        path = ("v6" if it["jev"] in REVIEW_PROFILES else "prose") if on else "v2"
        ai, model = row["ai"] or {}, cs[-1]["model"]
        marker = describe_text(it["account_id"], it["media_id"], model)
        if path == "prose":
            text = " ".join([marker + ".", *(s for c, s in PROSE_CLAIMS.items() if c in SAYS[it["jev"]])])
        else:
            text = marker
        jv = (_jev_of(row) or {}).get("v") if on else None
        want = {"path": path, "jev_v": jv, "model": model, "px": PX.get(path)}
        d = ai.get("_describe") if isinstance(ai.get("_describe"), dict) else {}
        got = {"recipes": [c.get("recipe") for c in cs], "hedge": [c.get("hedge") for c in cs],
               "describe": {x: d.get(x) for x in want}, "description": ai.get("description"),
               "garments": ai.get("clothing_items")}
        good = (got["recipes"] == [path] * len(cs) and got["hedge"] == [path == "v6"] * len(cs)
                and (path != "prose" or got["garments"] == PROSE_GARMENTS)
                and got["describe"] == want and got["description"] == text and (jv is not None or not on)
                and (it["kind"] == "video" or row["description"] == text))
        groups[path][k] = (good, {"profile": it.get("jev"), "kind": it["kind"], "want": {**want, "text": text},
                                  **got})
    # Coverage: a seeded (cached) or copied photo has no pass-1 describe, so not every profile need show up; the
    # prose rows must still keep AND drop each claim at least once, and both coin flips must reach v6.
    for name, path in ((JEV_DESCRIBE_PROSE, "prose"), (JEV_DESCRIBE_REVIEW, "v6")):
        g = groups[path]
        bad = {k: v for k, (ok, v) in g.items() if not ok}
        covered = {v["profile"] for _, v in g.values()}
        if path == "prose":
            kept = set().union(*(SAYS[p] for p in covered)) if covered else set()
            dropped = set().union(*(set(PROSE_CLAIMS) - SAYS[p] for p in covered)) if covered else set()
            enough = kept == dropped == set(PROSE_CLAIMS)
        else:
            enough = covered == REVIEW_PROFILES
        ctx.check(name, enough and not bad and not timed_out, rows=len(g), bad=len(bad),
                  covered=sorted(covered), sample=dict(list(bad.items())[:4]))
    g = groups["v2"]
    bad = {k: v for k, (ok, v) in g.items() if not ok}
    off_kinds = Counter((by_key[k]["account_id"] == flip_aid, by_key[k]["kind"]) for k in g)
    ctx.check(JEV_DESCRIBE_OFF, bool(g) and not bad and any(f for f, _ in off_kinds)
              and any(kd == "video" for _, kd in off_kinds) and not timed_out,
              rows=len(g), bad=len(bad), kinds={f"{'flip' if f else 'other'}:{kd}": n for (f, kd), n in off_kinds.items()},
              sample=dict(list(bad.items())[:4]))

    # JEV_UI_TOGGLE (last: the switch it flips changes nothing above)
    ui_creator = creators[2] if len(creators) > 2 else creators[1]
    if ctx.app is not None:
        before = await ctx.owner.get(f"{CONFIG}?account_id={ui_creator['id']}")
        pre = {"http": before.status_code, "stored": before.json()["config"].get("vault_jev_enabled")
               if before.status_code == 200 else None}
        got = await _ui_toggle(ctx, ui_creator)
        (ctx.out / "ui-toggle.json").write_text(json.dumps({"before": pre, **got}, indent=2, default=str))
        _check_ui(ctx, got, pre)
    else:
        _check_ui(ctx, None, None)

    S._check_budgets(ctx)
    ctx.metric("phases", {f"{p.stage}_s": p.seconds for p, _ in phases})
    ctx.metric("vault_jev", {"calls": dict(Counter(f"{c['pass']}:{c['profile']}" for c in every)),
                             "pass1_calls": len(j1), "flags_calls": len(jf), "billed_mc": sum(total.values()),
                             "jev_plan": jev_plan})
