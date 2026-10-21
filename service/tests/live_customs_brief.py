#!/usr/bin/env python3
"""live_customs_brief — the customs work order against the REAL model. OPT-IN.

Replays a captured Blake1 thread (scratchpad JSON: fan_id, direction,
created_at, is_tip, price_cents, body) into the harness DB and calls
`customs_brief` unpatched, then prints the handoff exactly as CustomsTab
copies it. Spends one DeepSeek call per fan.

Run: ./venv/bin/python service/tests/live_customs_brief.py <fixture.json> [fan_id ...]
"""
from __future__ import annotations

import os, pathlib, sys
from dotenv import dotenv_values

_SERVICE = pathlib.Path(__file__).resolve().parents[1]
_key = (dotenv_values(_SERVICE / ".env").get("DEEPSEEK_API_KEY") or "").strip()
if not _key:
    sys.exit("no DEEPSEEK_API_KEY in service/.env")
os.environ["DEEPSEEK_API_KEY"] = _key
os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import _harness  # noqa: E402
_harness.bootstrap()

import asyncio, json, re  # noqa: E402
from datetime import datetime  # noqa: E402

import customs_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Message, Transaction  # noqa: E402

AID = "8000186"
NAMES = {80000815: ("bitchboi1099", "BitchBoi99"), 370246851: ("bdenver85", "Bradley")}


async def seed(rows):
    async with get_session() as s:
        s.add(Account(id=AID, nickname="Blake1"))
        for fid, (u, d) in NAMES.items():
            s.add(Fan(account_id=AID, fan_id=fid, of_username=u, of_display_name=d))
        for i, r in enumerate(rows):
            at = datetime.fromisoformat(r["created_at"].split(".")[0])
            s.add(Message(account_id=AID, fan_id=r["fan_id"], message_id=10_000 + i,
                          direction=r["direction"], sender_name="", body=r["body"] or "",
                          media_ids="[]", media_count=0, price_cents=r["price_cents"] or 0,
                          is_tip=bool(r["is_tip"]), is_unsent=False, created_at=at))
            if r["is_tip"] and r["direction"] == "in":
                m = re.search(r"\$([\d,]+(?:\.\d+)?)", r["body"] or "")
                if m:
                    s.add(Transaction(account_id=AID, fan_id=r["fan_id"], kind="tip",
                                      amount_cents=int(round(float(m.group(1).replace(",", "")) * 100)),
                                      occurred_at=at, status="cleared", message_id=10_000 + i))
        await s.commit()


def handoff(row, brief):
    out = [f"-username: @{row['of_username']}", f"-account: {row['account_name']}"]
    if row.get("tip_cents") is not None:
        out.append(f"-total: ${row['tip_cents']/100:.2f}")
    if brief.get("call_him"):
        out.append(f"-call him: {brief['call_him']}")
    out.append("-request:")
    if brief.get("ok") and brief.get("found_request", True):
        out.append(f"  {brief['summary']}")
        if brief.get("his_words"):
            out.append("  His words:")
            out += [f'  "{w}"' for w in brief["his_words"]]
    else:
        out.append(f"  (brief failed: {brief.get('reason')} / {brief.get('summary')})")
    return "\n".join(out)


async def main():
    rows = json.load(open(sys.argv[1]))
    fans = [int(x) for x in sys.argv[2:]] or sorted({r["fan_id"] for r in rows})
    await seed(rows)
    # Mark them owed so the queue row (and its DB total) exists.
    async with get_session() as s:
        for fid in fans:
            f = await s.get(Fan, (AID, fid))
            f.customs_owed_at = max(datetime.fromisoformat(r["created_at"].split(".")[0])
                                    for r in rows if r["fan_id"] == fid and r["is_tip"])
        await s.commit()
    queue = {r["fan_id"]: r for r in (await customs_api.list_customs(account_id=AID))["customs"]}
    for fid in fans:
        row = queue[fid]
        brief = await customs_api.customs_brief(
            customs_api._BriefBody(account_id=AID, fan_id=fid, at=row.get("tipped_at")))
        print("=" * 72); print(handoff(row, brief)); print()

asyncio.run(main())
