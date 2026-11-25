from __future__ import annotations

import json
from collections import Counter
import time

from slop.actors import ui
from slop.lib.creator_avatars_faults import OWN_ONLY, OWN_SHOWN

PROFILE = "agency_inbox"
UI = True
FAULT = "avatar-keeps-other-creators-body"

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
        profile_reads = []
        page.on("request", lambda r: profile_reads.append(r.headers.get("x-account-id"))
                if "/api/of/v2/users/me" in r.url else None)
        async with page.expect_response(lambda r: "/health?all_accounts=1" in r.url) as health_response:
            await page.goto(f"{ctx.app}/creators", wait_until="domcontentloaded")
        health = await health_response.value
        health_body = await health.json()
        (ctx.out / "creator-health.json").write_text(json.dumps(health_body, indent=2))
        await ui.shot(ctx, page, "creators-trigger")
        own = set(ids) - crossed
        rows: list[dict] = []
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            rows = await page.evaluate(_ROWS)
            if len(rows) >= len(ids) and sum(1 for x in rows if x["src"]) >= len(own):
                break
            await page.wait_for_timeout(500)
        await page.wait_for_timeout(2000)
        rows = await page.evaluate(_ROWS)
        await ui.shot(ctx, page, "creators-settled")
        images = await page.locator("table img").evaluate_all(
            "imgs => imgs.map(i => ({src:i.src, complete:i.complete, width:i.naturalWidth}))")
        ctx.metric("creator_images", images)
        ctx.metric("profile_reads", dict(Counter(profile_reads)))

    by_id = {x["id"]: x["src"] for x in rows}
    frag = {i: (s.rsplit("#", 1)[-1] if s and "#" in s else None) for i, s in by_id.items()}
    ctx.check("creators table rows == /admin/accounts Creators", set(by_id) >= set(ids),
              missing=sorted(set(ids) - set(by_id)))
    wrong = {i: f for i, f in frag.items() if by_id[i] and f != i}
    ctx.check(OWN_ONLY, not wrong, wrong=wrong, rows=len(rows))
    srcs = [by_id.get(i) for i in own]
    ctx.check(OWN_SHOWN, all(frag.get(i) == i for i in own) and len(set(srcs)) == len(own),
              own=len(own), shown={i: frag.get(i) for i in own})

    health_rows = {str(row["account_id"]): row for row in health_body.get("accounts", [])}
    ctx.check("creators health reuses only matching identities", health.status == 200
              and all(str(health_rows.get(i, {}).get("profile", {}).get("id")) == i for i in own)
              and all("profile" not in health_rows.get(i, {}) for i in crossed),
              own=sorted(own), crossed=sorted(crossed))
    ctx.check("creators only mismatched health identities need fallback profile reads",
              Counter(profile_reads) == Counter({i: 1 for i in crossed}), reads=dict(Counter(profile_reads)))
    ctx.check("creators own avatar images finish decoding", bool(images)
              and all(i["complete"] and i["width"] > 0 for i in images), images=len(images))
