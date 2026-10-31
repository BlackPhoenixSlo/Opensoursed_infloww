#!/usr/bin/env python3
"""S10 edit-and-lock demo/regression — PATCH /admin/vault-ai/items/{media_id}.

Proves the operator edit path of the vault-AI layer, per
plans/VAULT_AI_ACTIONS_CONTRACT.md §3 (write rule) + §6c (edit endpoint):

  * PATCH writes each supplied field into operator_overrides_json, adds its name
    to locked_fields_json, AND projects into the same-named legacy compat column.
  * The response `{item, locked}` reads every field back through effective_value()
    (never the raw column), so the operator sees the override that just won.
  * A later FORCED describe rerun refreshes ai_fields_json but locked_fields() leaves
    every edited field untouched — the AI can never clobber an operator edit.
  * Un-edited fields stay AI-driven: a rerun DOES update a field the operator
    didn't lock.

Run:
  cd service/tests && \
    PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python _demo_s10.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import vault_ai_api as api  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_frames  # noqa: E402 — module under test (the PATCH route)
import llm_client  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402
from vault_ai_effective import effective_value, locked_fields  # noqa: E402

_NOW = datetime(2026, 7, 21, 10, 0, 0)
_AID_N = 0


def _fresh_account() -> str:
    global _AID_N
    _AID_N += 1
    return f"acc_s10_{_AID_N}"


async def _seed(aid: str, media_id: int, *, kind: str = "photo") -> None:
    """Seed an account + a described photo mirror row with AI (not operator)
    fields, exactly as a describe pass would leave it."""
    ai = {
        "description": "AI: a woman on a beach",
        "tags": ["beach", "bikini"],
        "explicitness": "suggestive",
    }
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(VaultItem(
            account_id=aid, media_id=media_id, kind=kind, created_at=_NOW,
            describe_status="described",
            description="AI: a woman on a beach",
            tags=json.dumps(["beach", "bikini"]),
            explicitness_tier="suggestive",
            suggested_caption="ai caption",
            ai_fields_json=json.dumps(ai),
            search_text="ai: a woman on a beach beach bikini",
        ))
        await s.commit()


async def _item(aid: str, media_id: int) -> VaultItem:
    async with get_session() as s:
        return await s.get(VaultItem, (aid, media_id))


class _FakeResult:
    """Stand-in for llm_client.LLMResult (only the attrs _describe_one reads)."""
    def __init__(self, content: str) -> None:
        self.content = content
        self.call_id = 4242
        self.cost_cents = 3
        self.parsed = None
        self.reasoning_content = None


# ── Case 1: PATCH overrides + locks + projects; effective_value returns the edit ──

async def case_edit_overrides_locks_projects() -> None:
    aid = _fresh_account()
    await _seed(aid, 1)

    resp = await api.edit_item(1, {
        "account_id": aid,
        "fields": {
            "description": "hand-written: sunset bikini set 🌅",
            "tags": "Sunset, Beach, BIKINI, sunset",   # comma string, dupes+case
            "explicitness_tier": "explicit",
        },
    })

    # Response shape (§6c): {item, locked}.
    assert set(resp.keys()) == {"item", "locked"}, resp.keys()
    view = resp["item"]
    assert set(resp["locked"]) == {"description", "tags", "explicitness_tier"}, resp["locked"]
    # Response read back via effective_value → shows the operator edit.
    assert view["description"] == "hand-written: sunset bikini set 🌅", view
    assert view["tags"] == ["sunset", "beach", "bikini"], view   # normalized, deduped
    assert view["explicitness_tier"] == "explicit", view
    # An un-edited field stays AI-driven in the view.
    assert view["suggested_caption"] == "ai caption", view

    # Persistence: overrides map, locked set, AND the compat columns.
    item = await _item(aid, 1)
    ov = json.loads(item.operator_overrides_json)
    assert ov["description"] == "hand-written: sunset bikini set 🌅", ov
    assert ov["tags"] == ["sunset", "beach", "bikini"], ov
    assert ov["explicitness_tier"] == "explicit", ov
    locked = set(json.loads(item.locked_fields_json))
    assert locked == {"description", "tags", "explicitness_tier"}, locked
    # Compat columns projected (so effective_value's legacy tier still agrees).
    assert item.description == "hand-written: sunset bikini set 🌅", item.description
    assert json.loads(item.tags) == ["sunset", "beach", "bikini"], item.tags
    assert item.explicitness_tier == "explicit", item.explicitness_tier

    # effective_value + locked_fields agree with the edit.
    assert effective_value(item, "description") == "hand-written: sunset bikini set 🌅"
    assert effective_value(item, "tags") == ["sunset", "beach", "bikini"]
    assert effective_value(item, "explicitness_tier") == "explicit"
    for f in ("description", "tags", "explicitness_tier"):
        assert f in locked_fields(item), f"{f} must be locked"
    assert "suggested_caption" not in locked_fields(item), "un-edited field must NOT be locked"


# ── Case 2: a forced describe rerun leaves locked fields untouched ──

async def case_rerun_respects_lock() -> None:
    aid = _fresh_account()
    await _seed(aid, 2)

    # Operator locks description + tier (but NOT suggested_caption).
    await api.edit_item(2, {
        "account_id": aid,
        "fields": {
            "description": "operator words, keep these",
            "explicitness_tier": "graphic",
        },
    })

    # Simulate a FORCED describe rerun: the vision model returns DIFFERENT values
    # for every field. Patch the two IO seams so _describe_one runs its real
    # locked-skip logic against fresh AI output (no network, no OF).
    fresh = {
        "description": "AI RERUN: totally different scene",
        "tags": ["gym", "workout"],
        "explicitness": "sfw",
        "nsfw": False, "sellable": True,
    }

    # **kw so the fake survives the frame-count arg (`want`) that _describe_one
    # passes from the duration ladder — the lock behaviour under test does not
    # depend on how many stills were sampled.
    async def _fake_images(account_id, item, raw, **kw):
        return vault_frames.Collected(["data:image/jpeg;base64,AAAA"], "ok")

    async def _fake_chat(*a, **k):
        return _FakeResult(json.dumps(fresh))

    orig_images = vault_frames.collect
    orig_chat = llm_client.chat
    vault_frames.collect = _fake_images        # type: ignore[assignment]
    llm_client.chat = _fake_chat              # type: ignore[assignment]
    try:
        res = await vault_ai_vision._describe_one(aid, 2)
    finally:
        vault_frames.collect = orig_images     # type: ignore[assignment]
        llm_client.chat = orig_chat           # type: ignore[assignment]

    assert res.get("ok") is True and res.get("status") == "described", res

    item = await _item(aid, 2)
    # ai_fields_json WAS refreshed — proving the rerun actually ran and WOULD
    # have changed the fields had they not been locked.
    ai = json.loads(item.ai_fields_json)
    assert ai["description"] == "AI RERUN: totally different scene", ai

    # …yet the LOCKED fields are untouched: effective_value still returns the edit.
    assert "description" in locked_fields(item) and "explicitness_tier" in locked_fields(item)
    assert effective_value(item, "description") == "operator words, keep these", (
        "locked description must survive the rerun"
    )
    assert effective_value(item, "explicitness_tier") == "graphic", (
        "locked tier must survive the rerun"
    )
    # Compat columns for the locked fields were NOT overwritten by the rerun.
    assert item.description == "operator words, keep these", item.description
    assert item.explicitness_tier == "graphic", item.explicitness_tier

    # The UN-locked field (tags) DID get the fresh AI value — the rerun still
    # updates everything the operator didn't lock.
    assert "tags" not in locked_fields(item), "tags was never locked here"
    assert effective_value(item, "tags") == ["gym", "workout"], (
        "un-locked tags should follow the AI rerun"
    )


# ── Case 3: operator price — cents round-trip, override+lock+compat, clear ──
# The AI never writes suggested_price_cents (PLAN correction #3 — vision reads
# content, not willingness-to-pay), so this field is purely an operator choice.
# The Composer prices an attachment set at the MAX price across the selection,
# which only works if the value survives the override+lock+compat write path.

async def case_price_edit_roundtrip() -> None:
    aid = _fresh_account()
    await _seed(aid, 3)

    resp = await api.edit_item(3, {
        "account_id": aid,
        "fields": {"suggested_price_cents": 1250},
    })
    assert resp["item"]["suggested_price_cents"] == 1250, resp["item"]
    assert "suggested_price_cents" in resp["locked"], resp["locked"]

    item = await _item(aid, 3)
    assert item.suggested_price_cents == 1250, item.suggested_price_cents  # compat column
    ov = json.loads(item.operator_overrides_json)
    assert ov["suggested_price_cents"] == 1250, ov
    assert "suggested_price_cents" in locked_fields(item), "price must lock like any edit"
    assert effective_value(item, "suggested_price_cents") == 1250

    # Blank clears it back to "no price" (so the Composer stops auto-pricing).
    resp = await api.edit_item(3, {
        "account_id": aid,
        "fields": {"suggested_price_cents": ""},
    })
    assert resp["item"]["suggested_price_cents"] is None, resp["item"]
    item = await _item(aid, 3)
    assert item.suggested_price_cents is None, item.suggested_price_cents


_harness.run(
    case_edit_overrides_locks_projects,
    case_rerun_respects_lock,
    case_price_edit_roundtrip,
)
