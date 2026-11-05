"""Manage creators: each Creator row shows its own OF profile picture, never another Creator's.

The bug (AE, 2026-11-04): /creators showed Wren's (the default Creator's) OF avatar on all 13 rows, while the
dashboard cards were right. Measured on AE: one `/users/me` (Wren's) answered, then 13 `/img` fetches of Wren's
thumbnail, one per row's account id. What put Wren's body into the other rows' queries was not reproduced
locally (dev + prod build, real Chrome, back/forward, reload: all rows distinct). The fix makes the symptom
impossible: a `/users/me` body counts for a row only when its `id` (OF user id = our account id) is the row's
own (useAccountAvatar `fetchOwnProfile`), and the table shares the dashboard cards' `["of-profile", id]` entry.

Flow: the owner opens /creators on the agency_inbox stack. The fake OF (`lib/relay.py` `_OfflineOF.me`, via
`$DEMO_SHOTS_TMP/of-me.json`) answers each Creator with its own picture (`avatars`), except half the non-default
Creators, which it answers with the default Creator's body (`answer_as`): the AE symptom injected at the wire.
Bypass, declared: that cross-wiring is faked at the OF boundary, not reproduced from its (unknown) cause.

Checks:
  OWN_ONLY  — no row's picture names another Creator (the data URL's `#<account id>` fragment == the row's id).
  OWN_SHOWN — every row answered as itself shows its own picture, so the guard does not just blank rows.
  The table's rows are /admin/accounts' Creators (the side-effect read).

FAULT `avatar-keeps-other-creators-body` reverts the guard in the served JS: OWN_ONLY goes red.
UI only (`--no-ui` skips): not a volume path, proven once on the real page.
"""
from __future__ import annotations

import json
import time

from slop.actors import ui
from slop.lib.creator_avatars_faults import OWN_ONLY, OWN_SHOWN

PROFILE = "agency_inbox"
UI = True
FAULT = "avatar-keeps-other-creators-body"

# Each Creators table row: the Creator cell's div whose title is "<extras label>\n<account id>\n…" and its avatar.
_ROWS = """() => [...document.querySelectorAll('div[title]')].filter((d) => d.title.includes('\\n'))
  .map((d) => ({id: d.title.split('\\n')[1], src: (d.querySelector('img') || {}).src || null}))"""


async def run(ctx) -> None:
    await ctx.build(PROFILE)
    if not ctx.app:
        for n in (OWN_ONLY, OWN_SHOWN, "creators table rows == /admin/accounts Creators"):
            ctx.skip(n, "--no-ui")
        return
    r = await ctx.owner.get("/admin/accounts")
    body = r.json()
    accounts = [a for a in body["accounts"] if (a.get("platform") or "onlyfans") == "onlyfans"
                and a.get("role") != "watcher"]
    ids = [str(a["id"]) for a in accounts]
    default = str(body.get("active_account_id") or ids[0])
    others = [i for i in ids if i != default]
    crossed = set(others[::2])
    (ctx.stack.tmp / "of-me.json").write_text(json.dumps(
        {"latency_s": 0.3, "avatars": True, "answer_as": {i: default for i in crossed}}))
    ctx.note(f"default Creator {default}; answered as it: {sorted(crossed)}; as themselves: "
             f"{sorted(set(ids) - crossed)}")

    async with ui.owner_browser(ctx, viewport=(1440, 900), through=("/api/of/v2/users/me",)) as page:
        await page.goto(f"{ctx.app}/creators", wait_until="domcontentloaded")
        await ui.shot(ctx, page, "creators-trigger")
        own = set(ids) - crossed
        rows: list[dict] = []
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            rows = await page.evaluate(_ROWS)
            if len(rows) >= len(ids) and sum(1 for x in rows if x["src"]) >= len(own):
                break
            await page.wait_for_timeout(500)
        await page.wait_for_timeout(2000)  # any late answer lands before the read
        rows = await page.evaluate(_ROWS)
        await ui.shot(ctx, page, "creators-settled")

    by_id = {x["id"]: x["src"] for x in rows}
    frag = {i: (s.rsplit("#", 1)[-1] if s and "#" in s else None) for i, s in by_id.items()}
    ctx.check("creators table rows == /admin/accounts Creators", set(by_id) >= set(ids),
              missing=sorted(set(ids) - set(by_id)))
    wrong = {i: f for i, f in frag.items() if by_id[i] and f != i}
    ctx.check(OWN_ONLY, not wrong, wrong=wrong, rows=len(rows))
    srcs = [by_id.get(i) for i in own]
    ctx.check(OWN_SHOWN, all(frag.get(i) == i for i in own) and len(set(srcs)) == len(own),
              own=len(own), shown={i: frag.get(i) for i in own})
