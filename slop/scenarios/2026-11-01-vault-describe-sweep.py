"""Vault Pro's AI describe sweep over whole vaults (service/vault_ai_vision.py `describe-all`, its plan and status,
then `flags-all`), at volume, on the real relay routes.

World: `agency_inbox` (an Agency and its Creators) plus seed/vault_items_describe.py: `--set items=` (200 small,
2000 medium, 20000 huge) vault rows over the Creators, as a collect leaves them: photos, clips (6/9/12 frames by
duration) and a few audio files, ~15% already described by an earlier sweep (the cache rows), a deterministic set
the 30b model refuses (235b answers) and a set both models answer blank (each at least one per Creator), and per
Creator a few planted re-upload sets (`vault_items_describe.DUPE_SETS`: photo pair, near-copy triple, a cached
photo's re-upload, a near-copy clip pair of one duration) whose thumbs match at threshold 2 while every other
item's thumb is its own. The seeder plans the items, the scenario arms lib/vault_describe_relay.py with their
outcomes (`arm_run`), then the seeder writes rows and stills into the stores the arm answered. The Agency's
DeepInfra key is a dummy set through the real Setup > Keys route (`PUT /admin/my-llm-keys`).

Each phase (`_phase`) runs its presses while `--users` owner tabs poll its status route at the app's 2.5 s
(useVaultSweep POLL_MS), round-robin over the Creators, and ends once every Creator's sweep settled and the fake
stopped answering; it keeps its own calls, statuses, timeouts and rows, and each check reads only its phases.
  pass 1   GET /admin/vault-ai/describe-all/plan per Creator, then POST /admin/vault-ai/describe-all for every
           Creator at once (with UI, the UI Creator's from Vault Pro's Extras drawer, "Describe all (N)",
           screenshots describe-trigger / describe-settled). Each sweep also flags what it described (the
           product's describe-and-flag).
  flags    POST /admin/vault-ai/flags-all {force} for every Creator at once, polled on /flags-all/status.
  pass 2   the plan again, one press per Creator at once: it must retry only the blank ones (no call for a
           described row).
  pass 3   the plan again, describe-all pressed by PRESSES owner tabs at once per Creator (a double click / two
           managers): one sweep each (one 200, the rest 409), each still-blank item called once over.

After the phases the Duplicates route (`GET /admin/vault-ai/duplicates`, threshold 2) is read per Creator: duplicate
reuse must share answers across exactly its sets (owner decision 2026-11-11), so REUSE holds them to the planted ones.
A planted copy (no call of its own, `_copied_from` / `_flags_copied_from` a member of its set, that member's text,
model and flags) passes EXACTLY_ONCE, PLAN, ESCALATE and FLAGS as well as a paid item would, so turning reuse off
reds REUSE alone.

Checks (names in lib/vault_describe_faults.py): EXACTLY_ONCE, PLAN, CACHE, ESCALATE, COST, COST_INCL_FLAGS, FLAGS,
REUSE, ONE_SWEEP, UI_SETTLED (with UI), budgets on the status routes' p95 (`STATUS_P95_MS`) and p95 vs the last green
run, plus the stock no 5xx / no unexpected Traceback.

Bypasses (declared):
  - DeepInfra is lib/vault_describe_relay.py's loopback fake at its OpenAI-compatible wire
    (`llm_providers.PROVIDERS["deepinfra"]` re-pointed; `llm_client.chat` with its key lookup, cap reservation,
    grok_calls rows, retries and cost math is the product's). Answers per item from `deepinfra.json`; usage
    billed per answer at the model's listed price (`llm_models.MODELS`, computed in the fake);
    `--set llm_latency_s=` (0.05 s) per call instead of DeepInfra's ~14 s (time compression: the sweep's
    concurrency 8 and the process-wide gate 8 are real).
  - The frames: `vault_frames.collect` reads the local still stores a collect warms (photo IMAGE_DIR files, a
    clip's storyboard frames), seeded by the seeder into the run's temp dir, which the relay part's arm hook
    points `vault_stills` / `storyboard` at. OnlyFans is never reached. The grid tiles (`/admin/vault-ai/thumb`)
    and `vault_dupes`' hashes read seeded 300px grey-grid stand-ins from the same temp THUMB_DIR.
  - The UI run's browser aborts `/img` / `/img/scrub` (the grid's OF CDN tiles through the account's OF client:
    OF is unreachable, and the relay's 500 on a session-less client is not what this flow is about).
  - Items are told apart by their pictures' pixel sizes (unique per item), the fake's only handle on "which item".
  - The vault rows are SQL (only columns a collect / an earlier sweep writes); the key is a dummy, never a real
    one, and SLOP_LIVE=1 is refused (every check SKIPs).
  - Owner tabs are one owner session's connection pool, not browsers (the UI run has one browser besides).

Break-it-once: `vault-describe-ignores-cache` (the scenario's FAULT: the 'undescribed' selection loses its
`describe_status` filter) turns only CACHE and PLAN red (the plan then counts the cached rows too, != the seeded
undescribed count); `--fault=vault-describe-cost-last-attempt` (`_describe_one` reports only the last attempt's
cost, the pre-W9 under-report) only COST and COST_INCL_FLAGS; `--fault=vault-describe-claim-after-budget` (the
start claims the Creator only after awaiting the budget, so concurrent presses all start a sweep) only ONE_SWEEP;
`--fault=vault-describe-drops-flags-cost` (describe-and-flag drops the flags call's cost) only COST_INCL_FLAGS;
`--fault=vault-describe-no-reuse` (`vault_dupes.reuse_groups` finds no set) only REUSE.
"""
# No `from __future__ import annotations`: lib/cli.py loads a scenario outside sys.modules, and @dataclass resolves
# string annotations through it.
import asyncio
import json
import os
import random
import re
import time
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import NamedTuple
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib.procmon import pct
from slop.lib.vault_describe_faults import (
    CACHE, COST, COST_INCL_FLAGS, ESCALATE, EXACTLY_ONCE, FLAGS, ONE_SWEEP, PLAN, REUSE, UI_SETTLED,
)
from slop.lib.vault_describe_relay import FAKE_KEY, HOSTILE_DESC, HOSTILE_TAG, M30, M235, arm_run, describe_text
from slop.seed import vault_items_describe

PROFILE = "agency_inbox"
UI = True
FAULT = "vault-describe-ignores-cache"
VIEWPORT = (1440, 900)
WAIT_MS = 120_000  # a page's first visit compiles it in next dev
POLL_S = 2.5       # app/hooks/useVaultSweep.ts POLL_MS
SWEEP_TIMEOUT_S = 1200
PRESSES = 3
DESCRIBE = "/admin/vault-ai/describe-all"
STATUS = f"{DESCRIBE}/status"
FLAGS_ALL = "/admin/vault-ai/flags-all"
FLAGS_STATUS = f"{FLAGS_ALL}/status"
# The keys a flags run may write into ai_fields_json (service/vault_ai_brief.py FLAG_KEYS + OVER_KEYS values;
# vault_ai_vision_decide.build_flags_fields), besides its own `_flags_*` stamps. Any other key it changes is a bug.
FLAG_FIELDS = ("underwear_visible", "vulva_vis", "breasts_vis", "anus_vis", "over_breasts", "over_vulva", "over_anus")
COPY_MARK, FLAGS_COPY_MARK = "_copied_from", "_flags_copied_from"  # vault_ai_vision_decide's copy stamps
DUPES = "/admin/vault-ai/duplicates"
WANT_SEQ = {"ok": [M30], "refuse": [M30, M235], "blank": [M30, M235]}
# Budgets on the status routes over the sweep phases (pass 1, flags, pass 2; not pass 3: one sweep of the blank
# retries behind ONE_SWEEP's press race, few samples, kept out so the numbers stay comparable). Guess. Measured
# medium/200 on the shared dev machine: first green 20261101T105606Z-...-d0c3 (host load ~23) describe status p95
# 96.6 ms (n=11575), flags status 337.5 ms (n=8755); runs at host load 30-88 reached 0.5-4.6 s / 1.8-2.3 s,
# tracking pool spills and the relay loop at ~90% of a core (the tail is queueing). Both are the auth gate plus an
# in-memory read; flags adds a parse of every photo's ai_fields_json per poll (vault_scripts.flags_coverage),
# O(vault) on the loop. So these catch a gross regression, not drift.
STATUS_P95_MS = {f"GET {STATUS}": 2500, f"GET {FLAGS_STATUS}": 5000}
BUDGET_STAGES = ("pass1", "flags", "pass2")
P95_VS_LAST = (1.5, 2000)
P95_VS_LAST_MIN_N = 20
IMG = re.compile(r"/img(/scrub)?\?")
TOURS_SEEN = ("localStorage.setItem('vaultProOnboarding', JSON.stringify({batchUploadEntry: '1', "
              "uploadPageStep: '1', batchEdit: '1', uploadBtn: '1'}));")


def _prog(st: dict) -> dict:
    return st.get("progress") or {}


def _undesc(plan: dict) -> int:
    return int(plan.get("undescribed") or 0)


def _label(k: int) -> str:
    """The Extras drawer's button for a plan of k undescribed items."""
    return f"Describe all ({k})" if k else "Describe all"


def _per_creator(items) -> Counter:
    return Counter(i["account_id"] for i in items)


class Pressed(NamedTuple):
    """What a phase's press answers: the counts its sweeps must reach, the presses, the plan they came from, and the
    UI press still running (pass 1 with UI)."""
    want: dict
    presses: dict
    plan: dict | None = None
    ui: asyncio.Task | None = None


@dataclass
class Phase:
    """One phase's presses and what came of them, once every Creator's sweep settled."""
    stage: str
    want: dict      # aid -> the count its sweep must reach (progress total == done)
    presses: dict   # aid -> the press's status (or start body)
    plan: dict | None  # aid -> the describe plan the want came from (None: flags)
    ui: dict | None    # the UI press's record (pass 1 with UI)
    status: dict    # aid -> its last status (`timed_out` when it never settled)
    calls: list     # the fake's calls during the phase, in arrival order
    rows: dict      # vault rows by item key, after
    seconds: float

    @property
    def timed_out(self) -> list:
        return [a for a, s in self.status.items() if s.get("timed_out")]

    @property
    def stray(self) -> list:
        """Calls the fake could not place, or that did not carry the agency's key."""
        return [c for c in self.calls if c["purpose"] == "other" or c["answer"] == "unknown" or not c["auth"]]

    def by_item(self, purpose: str) -> dict:
        out = defaultdict(list)
        for c in self.calls:
            if c["purpose"] == purpose and c["account_id"] is not None:
                out[vault_items_describe.key(c["account_id"], c["media_id"])].append((c["model"], c["answer"]))
        return out

    def billed(self, *purposes: str) -> Counter:
        out = Counter()
        for c in self.calls:
            if c["purpose"] in purposes:
                out[c["account_id"]] += c["billed_mc"]
        return out

    def reported(self, aid: str):
        return _prog(self.status[aid]).get("cost_millicents")


async def _count(ctx) -> int:
    return (await ctx.owner.get("/__slop/vault-describe/count")).json()["n"]


async def _settle(ctx, since: int, still_s: float = 1.5) -> list[dict]:
    """The fake's calls from `since`, once its count stopped moving for still_s (a second sweep would still call)."""
    n, t = await _count(ctx), time.monotonic()
    while time.monotonic() - t < still_s:
        await asyncio.sleep(0.3)
        m = await _count(ctx)
        if m != n:
            n, t = m, time.monotonic()
    return (await ctx.owner.get(f"/__slop/vault-describe/calls?since={since}&until={n}")).json()["calls"]


async def _plans(ctx, aids) -> dict:
    out = {}
    for aid in aids:
        r = await ctx.owner.get(f"{DESCRIBE}/plan?account_id={aid}")
        if r.status_code != 200:  # a 0 'undescribed' would make every count check agree with nothing
            raise RuntimeError(f"slop: {DESCRIBE}/plan for {aid} answered {r.status_code}: {r.text[:200]}")
        out[aid] = r.json()
    return out


async def _dupe_sets(ctx, aids) -> dict:
    """aid -> the Duplicates screen's sets at "2 · recommended" (sorted media ids), or its error."""
    out = {}
    for aid in aids:
        r = await ctx.owner.get(f"{DUPES}?account_id={aid}&threshold=2&limit=100000")
        out[aid] = (sorted(sorted([c["original"]["media_id"], *(d["media_id"] for d in c["dupes"])])
                           for c in r.json()["clusters"]) if r.status_code == 200
                    else f"{r.status_code}: {r.text[:200]}")
    return out


async def _post_all(ctx, path: str, aids, body) -> dict:
    """POST `path` with body(aid) for every Creator at once -> aid -> response."""
    res = await asyncio.gather(*(ctx.owner.post(path, json=body(a)) for a in aids))
    return dict(zip(aids, res))


@asynccontextmanager
async def _polling(ctx, aids, path: str):
    """`--users` owner tabs on one session's pool: each polls its Creator's `path` every POLL_S, start staggered."""
    http = ctx.owner.share(limits=max(10, ctx.users))
    rng = random.Random(ctx.seed)
    stop = asyncio.Event()

    async def tab(i: int) -> None:
        aid = aids[i % len(aids)]
        await asyncio.sleep(rng.random() * POLL_S)
        while not stop.is_set():
            await http.get(f"{path}?account_id={aid}")
            try:
                await asyncio.wait_for(stop.wait(), POLL_S)
            except asyncio.TimeoutError:
                pass

    tabs = asyncio.gather(*(tab(i) for i in range(ctx.users)))
    try:
        yield
    finally:
        stop.set()
        await tabs
        await http.aclose()


async def _wait_done(ctx, path: str, want: dict) -> dict:
    """Each Creator's last status once its sweep is over (not running, done == total == want[aid])."""
    out: dict = {}
    t0 = time.monotonic()
    while len(out) < len(want) and time.monotonic() - t0 < SWEEP_TIMEOUT_S:
        for aid, n in want.items():
            if aid in out:
                continue
            st = (await ctx.owner.get(f"{path}?account_id={aid}")).json()
            p = _prog(st)
            if not st.get("running") and p.get("total") == n and p.get("done") == n:
                out[aid] = st
        await asyncio.sleep(0.5)
    for aid in want:
        if aid not in out:
            out[aid] = {**(await ctx.owner.get(f"{path}?account_id={aid}")).json(), "timed_out": True}
    return out


def _rows(ctx) -> dict:
    con = ctx.world.sql()
    rows = con.execute("SELECT account_id, media_id, kind, describe_status, describe_model, description, "
                       "video_description, tags, explicitness_tier, ai_fields_json, search_text "
                       "FROM vault_items").fetchall()
    con.close()
    return {vault_items_describe.key(r[0], r[1]): {
        "status": r[3], "model": r[4], "description": r[5], "video_description": r[6], "tags": r[7], "tier": r[8],
        "ai_raw": r[9], "ai": json.loads(r[9]) if r[9] else None, "search": r[10],
        "text": r[6] if r[2] == "video" else r[5]} for r in rows}


async def _phase(ctx, stage: str, status_path: str, aids, press) -> Phase:
    """`press()` -> Pressed, while the owner tabs poll `status_path`; over once every Creator's sweep settled (or
    SWEEP_TIMEOUT_S passed), the UI press (if any) finished and the fake stopped answering."""
    since = await _count(ctx)
    ctx.rec.stage = stage
    t = time.time()
    async with _polling(ctx, aids, status_path):
        got = await press()
        status = await _wait_done(ctx, status_path, got.want)
        ui = await got.ui if got.ui else None
        calls = await _settle(ctx, since)
    return Phase(stage, got.want, got.presses, got.plan, ui, status, calls, _rows(ctx), round(time.time() - t, 1))


async def _ui_press(ctx, creator: dict, want_n: int) -> dict:
    """Vault Pro > Extras > "Describe all (N)" for the UI Creator; waits for its sweep and the button's settled
    label. Falls back to the API press when a step fails before the click, so the other checks still run (the UI
    check FAILs)."""
    got: dict = {"posts": []}
    clicked = False
    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        await page.context.add_init_script(TOURS_SEEN)
        await page.route(IMG, lambda r: r.abort())  # the grid's OF CDN tiles: OF is unreachable (declared)
        page.on("response", lambda r: got["posts"].append(r.status) if r.request.method == "POST"
                and urlsplit(r.url).path.endswith(DESCRIBE) else None)
        try:
            await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=WAIT_MS)
            await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
            await page.get_by_role("button", name=re.compile(r" extras$")).first.click(timeout=WAIT_MS)
            want = _label(want_n)
            btn = page.get_by_role("button", name=want, exact=True)
            await btn.wait_for(timeout=WAIT_MS)
            got["trigger_label"] = want
            await page.wait_for_timeout(700)  # the drawer's slide-in
            got["trigger_shot"] = await ui.shot(ctx, page, "describe-trigger")
            await btn.click(timeout=10_000)
            clicked = True
            try:
                await page.get_by_role("button", name=re.compile(r"^Describing ")).first.wait_for(timeout=10_000)
                got["saw_busy"] = True
            except Exception:  # noqa: BLE001 — a fast sweep may end between two polls
                got["saw_busy"] = False
            await _wait_done(ctx, STATUS, {creator["id"]: want_n})
            after = (await ctx.owner.get(f"{DESCRIBE}/plan?account_id={creator['id']}")).json()
            got["want_settled"] = _label(_undesc(after))
            await page.get_by_role("button", name=got["want_settled"], exact=True).wait_for(timeout=60_000)
            await page.wait_for_timeout(500)
            got["settled_label"] = got["want_settled"]
            got["settled_shot"] = await ui.shot(ctx, page, "describe-settled")
        except Exception as e:  # noqa: BLE001 — the UI check reports it
            got["error"] = f"{type(e).__name__}: {e}"[:600]
            try:
                await ui.shot(ctx, page, "failed-describe-ui")
            except Exception:  # noqa: BLE001
                pass
    if not clicked:
        r = await ctx.owner.post(DESCRIBE, json={"account_id": creator["id"]})
        got["fallback_api_press"] = r.status_code
    return got


@dataclass
class Run:
    aids: list
    by_key: dict
    live: list      # photos and clips (audio has no still: never described or flagged)
    targets: list   # the live items not described by the seed
    p1: Phase
    pf: Phase
    p2: Phase
    p3: Phase
    ui_creator: dict | None
    sets: dict      # planted set id -> its items
    dupes: dict     # aid -> the Duplicates route's sets (sorted media ids), or its error

    def of(self, outcome: str) -> list:
        return [i for i in self.targets if i["outcome"] == outcome]

    def copied(self, rows: dict, it: dict, marker: str = COPY_MARK) -> bool:
        """`it` is a planted copy in `rows`: `marker` names another member of its set, whose flags it carries (and,
        for a describe copy, its status, model and text)."""
        if not it["dupe_set"]:
            return False
        members = {m["media_id"]: m for m in self.sets[it["dupe_set"]]}
        row = rows[it["key"]]
        src = (row["ai"] or {}).get(marker)
        if src not in members or src == it["media_id"]:
            return False
        s = rows[members[src]["key"]]
        same = marker != COPY_MARK or (row["status"] == s["status"] == "described" and row["text"] == s["text"]
                                       and row["model"] == s["model"])
        return same and _flags_of(row) == _flags_of(s)


def _flags_of(row: dict) -> dict:
    return {k: (row["ai"] or {}).get(k) for k in FLAG_FIELDS}


def _check_exactly_once(ctx, r: Run) -> None:
    """Pass 1: one answer that described each undescribed item, and its row holds it (a planted copy: its set's)."""
    d1, bad = r.p1.by_item("describe"), {}
    for it in r.targets:
        k, row = it["key"], r.p1.rows[it["key"]]
        oks = [m for m, a in d1.get(k, []) if a == "ok"]
        if it["outcome"] == "blank":
            good = not oks and row["status"] == "refused" and row["text"] is None
        elif k not in d1 and r.copied(r.p1.rows, it):
            good = True
        else:
            good = (len(oks) == 1 and row["status"] == "described" and row["model"] == oks[0]
                    and row["text"] == describe_text(it["account_id"], it["media_id"], oks[0]))
        if not good:
            bad[k] = {"outcome": it["outcome"], "calls": d1.get(k, []), "status": row["status"], "text": row["text"]}
    ctx.check(EXACTLY_ONCE, bool(r.targets) and not bad and not r.p1.stray and not r.p1.timed_out,
              items=len(r.targets), bad=len(bad), sample=dict(list(bad.items())[:5]), stray=r.p1.stray[:5],
              timed_out=r.p1.timed_out)


def _check_plan(ctx, r: Run) -> None:
    """Plan count == items the sweep called + planted copies it made == its progress total (both passes); pass 1's ==
    the seeded count."""
    seeded = _per_creator(r.targets)
    d1 = r.p1.by_item("describe")
    called1, called2 = (_per_creator(r.by_key[k] for k in p.by_item("describe")) for p in (r.p1, r.p2))
    copied1 = _per_creator(it for it in r.targets if it["key"] not in d1 and r.copied(r.p1.rows, it))
    per = {aid: {"seeded_undescribed": seeded[aid], "plan1": r.p1.want[aid], "called1": called1[aid],
                 "copied1": copied1[aid], "total1": _prog(r.p1.status[aid]).get("total"), "plan2": r.p2.want[aid],
                 "called2": called2[aid], "total2": _prog(r.p2.status[aid]).get("total")} for aid in r.aids}
    presses_bad = {f"{p.stage}:{a}": c for p in (r.p1, r.p2) for a, c in p.presses.items() if c != 200}
    timed_out = r.p1.timed_out + r.p2.timed_out
    ctx.check(PLAN, not presses_bad and not timed_out and all(
        p["seeded_undescribed"] == p["plan1"] == p["called1"] + p["copied1"] == p["total1"]
        and p["plan2"] == p["called2"] == p["total2"]
        for p in per.values()), per_creator=per, presses_not_200=presses_bad, timed_out=timed_out)


def _check_cache(ctx, r: Run) -> None:
    """No describe call for a described row; descriptions kept; pass 2 retries exactly the blank ones."""
    d1, d2 = r.p1.by_item("describe"), r.p2.by_item("describe")
    cached_called = [k for k in d1 if r.by_key[k]["cached"]]
    described1 = {k for k, row in r.p1.rows.items() if row["status"] == "described"}
    again = [k for k in d2 if k in described1]
    blank = {i["key"] for i in r.of("blank")}
    changed = [k for k in described1 if r.p2.rows[k]["text"] != r.p1.rows[k]["text"]
               or r.p2.rows[k]["status"] != "described"]
    seeded_lost = [i["key"] for i in r.live if i["cached"] and r.p2.rows[i["key"]]["text"] != i["seeded_description"]]
    ctx.check(CACHE, bool(blank) and not cached_called and not again and set(d2) == blank and not changed
              and not seeded_lost and not r.p2.stray and not r.p2.timed_out,
              cached_rows=sum(1 for i in r.live if i["cached"]), cached_called=len(cached_called),
              pass2_called_described=len(again), pass2_called=len(d2), blank=len(blank),
              pass2_not_blank=sorted(set(d2) - blank)[:5], blank_not_retried=sorted(blank - set(d2))[:5],
              changed=changed[:5], seeded_lost=seeded_lost[:5], sample_called=(cached_called + again)[:5],
              stray=r.p2.stray[:5], timed_out=r.p2.timed_out)


def _check_escalate(ctx, r: Run) -> None:
    """Pass 1: the model sequence per item by its outcome."""
    d1 = r.p1.by_item("describe")
    bad = {i["key"]: d1.get(i["key"]) for i in r.targets
           if [m for m, _ in d1.get(i["key"], [])] != WANT_SEQ[i["outcome"]]
           and not (i["key"] not in d1 and r.copied(r.p1.rows, i))}
    n_ref, n_blank = len(r.of("refuse")), len(r.of("blank"))
    calls_235b = sum(1 for c in r.p1.calls if c["purpose"] == "describe" and c["model"] == M235)
    ctx.check(ESCALATE, n_ref > 0 and n_blank > 0 and not bad and calls_235b == n_ref + n_blank,
              refused=n_ref, blank=n_blank, calls_235b=calls_235b, bad=len(bad), sample=dict(list(bad.items())[:5]))


def _check_cost(ctx, r: Run) -> None:
    """Each sweep's reported cost == the fake's billed sum for the sweep's own calls. COST: flags-all and pass 2
    (describe + any auto-flags; its retries are blank answers, so it makes no auto-flags). COST_INCL_FLAGS: pass 1,
    its describe calls plus the auto-flags it makes, which must be > 0 per Creator (else reported == billed would
    hold with the flags cost dropped). One total cannot say which part went missing, so a describe under-report
    reds both; a dropped flags cost only COST_INCL_FLAGS (pass 2 flags none to drop)."""
    sweeps = (("flags", r.pf, ("flags",)), ("pass2", r.p2, ("describe", "flags")))
    own = {aid: {name: [p.reported(aid), p.billed(*purposes)[aid]] for name, p, purposes in sweeps} for aid in r.aids}
    ok = all(rep == b for c in own.values() for rep, b in c.values())
    ctx.check(COST, ok, per_creator=own, reported_mc=sum(rep or 0 for c in own.values() for rep, _ in c.values()),
              billed_mc=sum(b for c in own.values() for _, b in c.values()))
    both, flags1 = r.p1.billed("describe", "flags"), r.p1.billed("flags")
    incl = {aid: [r.p1.reported(aid), both[aid], flags1[aid]] for aid in r.aids}
    ctx.check(COST_INCL_FLAGS, all(rep == b and f > 0 for rep, b, f in incl.values()),
              per_creator_reported_billed_flags=incl, auto_flags_mc=sum(flags1.values()))


def _non_flag(ai: dict | None) -> dict:
    return {k: v for k, v in (ai or {}).items() if k not in FLAG_FIELDS and not k.startswith("_flags_")}


def _check_flags(ctx, r: Run) -> None:
    """flags-all: one call per photo, 4 per clip (a planted copy: none), every live row flagged, nothing of describe's
    rewritten."""
    ff, before, after = r.pf.by_item("flags"), r.p1.rows, r.pf.rows
    want_calls = {i["key"]: (1 if i["kind"] == "photo" else 4) for i in r.live}
    flag_copies = {i["key"] for i in r.live if i["key"] not in ff and r.copied(after, i, FLAGS_COPY_MARK)}
    count_bad = {k: len(ff.get(k, [])) for k, n in want_calls.items()
                 if len(ff.get(k, [])) != n and k not in flag_copies}
    extra = [k for k in ff if k not in want_calls]
    keep = ("status", "model", "description", "video_description", "tags", "tier")
    rewritten = [k for k in before if any(before[k][c] != after[k][c] for c in keep)]
    ai_rewritten = [k for k in before if _non_flag(before[k]["ai"]) != _non_flag(after[k]["ai"])]
    unflagged = [k for k in want_calls if not ((after[k]["ai"] or {}).get("_flags_v") == 3
                                               and isinstance((after[k]["ai"] or {}).get("underwear_visible"), bool))]
    hostile = [k for k, row in after.items() if any(h in (row[c] or "") for h in (HOSTILE_DESC, HOSTILE_TAG)
                                                    for c in ("description", "video_description", "search", "tags",
                                                              "ai_raw"))]
    live = _per_creator(r.live)
    cands = {aid: [r.pf.want[aid], live[aid]] for aid in r.aids}
    ctx.check(FLAGS, not count_bad and not extra and not rewritten and not ai_rewritten and not unflagged
              and not hostile and all(a == b for a, b in cands.values()) and not r.pf.stray and not r.pf.timed_out,
              calls=sum(len(v) for v in ff.values()), count_bad=dict(list(count_bad.items())[:5]), extra=extra[:5],
              rewritten=rewritten[:5], ai_rewritten=ai_rewritten[:5],
              ai_sample={k: [_non_flag(before[k]["ai"]), _non_flag(after[k]["ai"])] for k in ai_rewritten[:2]},
              unflagged=len(unflagged), hostile=hostile[:5], candidates=cands, stray=r.pf.stray[:5],
              timed_out=r.pf.timed_out)


def _check_reuse(ctx, r: Run) -> None:
    """The Duplicates route's sets == the planted ones; pass 1 pays one member per planted set (none when it holds a
    cached member), the rest copy it; flags-all pays one member per set, the rest copy its flags."""
    planted = defaultdict(list)
    for ms in r.sets.values():
        planted[ms[0]["account_id"]].append(sorted(m["media_id"] for m in ms))
    route_bad = {aid: {"route": r.dupes.get(aid), "planted": sorted(planted[aid])} for aid in r.aids
                 if r.dupes.get(aid) != sorted(planted[aid])}
    d1, ff = r.p1.by_item("describe"), r.pf.by_item("flags")
    n_copies, set_bad = Counter(), {}
    for sid, ms in r.sets.items():
        todo = [m for m in ms if not m["cached"]]
        want_paid = 0 if any(m["cached"] for m in ms) else 1
        n_copies[ms[0]["account_id"]] += len(todo) - want_paid
        paid = [m["media_id"] for m in todo if m["key"] in d1]
        not_copied = [m["media_id"] for m in todo if m["key"] not in d1 and not r.copied(r.p1.rows, m)]
        fpaid = [m["media_id"] for m in ms if m["key"] in ff]
        fnot_copied = [m["media_id"] for m in ms if m["key"] not in ff and not r.copied(r.pf.rows, m, FLAGS_COPY_MARK)]
        if len(paid) != want_paid or not_copied or len(fpaid) != 1 or fnot_copied:
            set_bad[sid] = {"members": [m["media_id"] for m in ms], "describe_paid": paid, "want_paid": want_paid,
                            "not_copied": not_copied, "flags_paid": fpaid, "flags_not_copied": fnot_copied,
                            "marks": {m["media_id"]: [(r.pf.rows[m["key"]]["ai"] or {}).get(x)
                                                      for x in (COPY_MARK, FLAGS_COPY_MARK)] for m in ms}}
    seeded, called1 = _per_creator(r.targets), _per_creator(r.by_key[k] for k in d1)
    calls = {aid: {"called1": called1[aid], "want": seeded[aid] - n_copies[aid], "planted_copies": n_copies[aid]}
             for aid in r.aids}
    ctx.check(REUSE, all(planted[aid] for aid in r.aids) and not route_bad and not set_bad
              and all(c["called1"] == c["want"] for c in calls.values()),
              planted_sets=len(r.sets), per_creator_calls=calls, route_bad=route_bad,
              set_bad=dict(list(set_bad.items())[:5]))


def _check_one_sweep(ctx, r: Run) -> None:
    """Pass 3: PRESSES concurrent presses -> one 200, the rest 409, and each item the plan still counts called once
    over (its outcome's model sequence: one sweep's worth)."""
    d3 = r.p3.by_item("describe")
    dup = {k: v for k, v in d3.items() if [m for m, _ in v] != WANT_SEQ[r.by_key[k]["outcome"]]}
    presses_ok = all(sorted(v) == [200] + [409] * (PRESSES - 1) for v in r.p3.presses.values())
    ctx.check(ONE_SWEEP, presses_ok and not dup and not r.p3.timed_out, presses=r.p3.presses,
              plan3=r.p3.want, called=len(d3), dup=len(dup),
              extra_calls=sum(len(v) for v in d3.values()) - sum(len(WANT_SEQ[r.by_key[k]["outcome"]]) for k in d3),
              sample=dict(list(dup.items())[:3]), timed_out=r.p3.timed_out)


def _check_ui(ctx, r: Run) -> None:
    """With UI: the trigger label, the browser's start, the settled label, the DB side effect."""
    got = r.p1.ui
    if got is None:
        ctx.skip(UI_SETTLED, "--no-ui")
        return
    aid = r.ui_creator["id"]
    mine = [i for i in r.targets if i["account_id"] == aid and i["outcome"] != "blank"]
    not_desc = [i["media_id"] for i in mine if r.p1.rows[i["key"]]["status"] != "described"]
    ctx.check(UI_SETTLED, not got.get("error") and got.get("posts") == [200]
              and got.get("trigger_label") == _label(r.p1.want[aid])
              and got.get("settled_label") == _label(r.p2.want[aid])
              and not not_desc and bool(mine), **got, db_described=len(mine) - len(not_desc),
              db_not_described=not_desc[:5])


def _check_budgets(ctx) -> None:
    """The status routes (polled by --users tabs while the sweeps write) over BUDGET_STAGES, and vs the last green
    run (stock, from the metrics)."""
    p95s, ns = {}, {}
    for rt, budget in STATUS_P95_MS.items():
        name = f"p95 {rt} (sweep phases) < {budget}ms"
        lat = [ms for st in BUDGET_STAGES for _, ms in ctx.rec.by_stage.get(st, {}).get(rt, [])]
        if lat:
            p95s[rt], ns[rt] = pct(lat), len(lat)
            ctx.check(name, p95s[rt] < budget, budget=True, p95=p95s[rt], n=ns[rt])
        else:
            ctx.skip(name, "no samples")
    ctx.metric("p95_vs_last_green", p95s)
    ctx.metric("p95_vs_last_green_n", ns)


async def run(ctx) -> None:
    if os.environ.get("SLOP_LIVE") == "1":
        for c in (EXACTLY_ONCE, PLAN, CACHE, ESCALATE, COST, COST_INCL_FLAGS, FLAGS, REUSE, ONE_SWEEP, UI_SETTLED):
            ctx.skip(c, "SLOP_LIVE=1: this scenario runs on the DeepInfra fake only, never the paid API")
        return
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    aids = [c["id"] for c in creators]
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepinfra": FAKE_KEY})
    ctx.metric("agency_deepinfra_key", {"status": r.status_code})
    t0 = time.time()
    items = vault_items_describe.plan(w, creators, ctx.param("items", w.size["vault_describe_items"]))
    armed = await arm_run(ctx.owner, ctx.stack.tmp, items, ctx.param("llm_latency_s", 0.05))
    await vault_items_describe.seed(w, items, armed)
    ctx.metric("vault_seed", {"seconds": round(time.time() - t0, 2), "items": len(items),
                              "by": dict(Counter(f"{i['kind']}:{'cached' if i['cached'] else i['outcome']}"
                                                 for i in items))})
    by_key = {i["key"]: i for i in items}
    live = [i for i in items if i["kind"] != "audio"]
    ui_creator = creators[0] if ctx.app is not None else None

    async def press_describe(via_ui: dict | None = None) -> Pressed:
        """The plan per Creator, then describe-all for every Creator at once (via_ui's from the browser)."""
        plan = await _plans(ctx, aids)
        want = {aid: _undesc(plan[aid]) for aid in aids}
        task = asyncio.create_task(_ui_press(ctx, via_ui, want[via_ui["id"]])) if via_ui else None
        res = await _post_all(ctx, DESCRIBE, [a for a in aids if not via_ui or a != via_ui["id"]],
                              lambda a: {"account_id": a})
        return Pressed(want, {a: x.status_code for a, x in res.items()}, plan, task)

    async def press_flags() -> Pressed:
        res = await _post_all(ctx, FLAGS_ALL, aids, lambda a: {"account_id": a, "force": True})
        starts = {a: {"status": x.status_code, **(x.json() if x.status_code == 200 else {})} for a, x in res.items()}
        return Pressed({a: int(s.get("candidates") or 0) for a, s in starts.items()}, starts)

    async def press3() -> Pressed:
        plan = await _plans(ctx, aids)
        shares = [ctx.owner.share(limits=len(aids) + 2) for _ in range(PRESSES)]
        order = [(aid, h) for aid in aids for h in shares]
        try:
            res = await asyncio.gather(*(h.post(DESCRIBE, json={"account_id": aid}) for aid, h in order))
        finally:
            for h in shares:
                await h.aclose()
        presses = defaultdict(list)
        for (aid, _), x in zip(order, res):
            presses[aid].append(x.status_code)
        return Pressed({aid: _undesc(plan[aid]) for aid in aids}, dict(presses), plan)

    p1 = await _phase(ctx, "pass1", STATUS, aids, lambda: press_describe(ui_creator))
    pf = await _phase(ctx, "flags", FLAGS_STATUS, aids, press_flags)
    p2 = await _phase(ctx, "pass2", STATUS, aids, press_describe)
    p3 = await _phase(ctx, "pass3", STATUS, aids, press3)
    ctx.rec.stage = None
    phases = (p1, pf, p2, p3)

    for p in phases:
        (ctx.out / f"calls-{p.stage}.json").write_text(json.dumps(p.calls))
    (ctx.out / "sweep-status.json").write_text(json.dumps(
        {"ui": p1.ui, **{p.stage: {"plan": p.plan, "want": p.want, "presses": p.presses, "status": p.status}
                         for p in phases}}, indent=2, default=str))

    sets = defaultdict(list)
    for i in items:
        if i["dupe_set"]:
            sets[i["dupe_set"]].append(i)
    dupes = await _dupe_sets(ctx, aids)
    (ctx.out / "duplicates.json").write_text(json.dumps(
        {"planted": {sid: [m["media_id"] for m in ms] for sid, ms in sets.items()}, "route": dupes}, indent=2))
    run_ = Run(aids, by_key, live, [i for i in live if not i["cached"]], p1, pf, p2, p3, ui_creator, dict(sets), dupes)
    for check in (_check_exactly_once, _check_plan, _check_cache, _check_escalate, _check_cost, _check_flags,
                  _check_reuse, _check_one_sweep, _check_ui):
        check(ctx, run_)
    _check_budgets(ctx)

    ctx.metric("phases", {f"{p.stage}_s": p.seconds for p in phases})
    ctx.metric("status_by_phase", {p.stage: {rt: {k: v[k] for k in ("n", "p50_ms", "p95_ms")}
                                             for rt, v in ctx.rec.summary(p.stage).items() if rt.endswith("/status")}
                                   for p in phases})
    every = [c for p in phases for c in p.calls]
    ctx.metric("vault_describe", {
        "calls": dict(Counter(f"{c['purpose']}:{c['model']}:{c['answer']}" for c in every)),
        **{f"{p.stage}_calls": len(p.calls) for p in phases}, "presses1": p1.presses,
        "billed_mc": sum(c["billed_mc"] for c in every)})
