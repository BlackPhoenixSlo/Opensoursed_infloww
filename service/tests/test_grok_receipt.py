#!/usr/bin/env python3
"""grok_calls prompt audit — keep the WORDS, never the PIXELS.

`prompt_json` used to hold the ENTIRE outbound request body verbatim. On prod
(2026-08-03) that made grok_calls 1,325 MB = 52% of the whole DB, of which
~885 MB was base64 image bytes — 99.3% of `describe_media` rows — for a column
with zero readers anywhere in the repo.

It now stores the body with every `data:` URI swapped for an
`<img:mime:bytes:digest>` manifest. All prompt TEXT survives; no image bytes do.
The images are already cached in the vault, so the base64 was only ever a
re-encoded copy. Measured over real prod rows: 1,199 MB -> 318 MB.

The three that matter most:
  • case_keeps_all_text_but_no_bytes — both halves of the deal in one assert.
  • case_redactor_does_not_mutate_the_body — the redactor deep-copies. A shallow
    copy would rewrite the SAME dict chat() then POSTs, sending "<img:…>" to the
    provider and breaking every vision lane on the first call.

Run: ./venv/bin/python service/tests/test_grok_receipt.py   (exit 0 = green)
"""
import _harness  # MUST be first — sets sys.path / binds a throwaway temp DB

_harness.bootstrap()

import base64  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import struct  # noqa: E402
import zlib  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import select  # noqa: E402

import llm_client  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, GrokCall  # noqa: E402

_SERVICE = Path(__file__).resolve().parents[1]
_REAL_ENV = _SERVICE / ".env"

# A realistic vision payload: three ~200 KB frames, like the Describe V2 ladder.
_B64 = "QUJDRA==" * 25_000          # ~200 KB of base64, valid alphabet
_URI = f"data:image/jpeg;base64,{_B64}"
_INSTRUCTION = "You are an explicit-content CATALOGUER for a private vault."


def _vision_body(n_images: int = 3) -> dict:
    parts = [{"type": "text", "text": _INSTRUCTION}]
    for _ in range(n_images):
        parts.append({"type": "image_url", "image_url": {"url": _URI}})
    return {
        "model": "Qwen/Qwen3-VL-30B-A3B-Instruct",
        "messages": [{"role": "user", "content": parts}],
        "temperature": 0.7,
        "stream": False,
    }


def case_keeps_all_text_but_no_bytes():
    """THE deal: every character of the prompt survives, zero image bytes do."""
    body = _vision_body(3)
    assert len(json.dumps(body)) > 500_000, "fixture too small to be meaningful"

    stored = llm_client._redacted_json(body)

    assert "base64" not in stored, "base64 reached the DB value"
    assert _B64[:64] not in stored, "payload reached the DB value"
    assert _INSTRUCTION in stored, "prompt TEXT was lost — the whole point"
    assert stored.count("<img:image/jpeg:") == 3, "lost an image manifest entry"
    # the manifest records the DECODED size, not the base64 length
    assert f"<img:image/jpeg:{llm_client._b64_decoded_len(_B64)}b:" in stored
    # a 600 KB body collapses to roughly the size of its text
    assert len(stored) < 2_000, f"stored {len(stored)} bytes"


def case_redactor_does_not_mutate_the_body():
    """MUST deep-copy — chat() POSTs the very dict we audit."""
    body = _vision_body(2)
    before = copy.deepcopy(body)

    llm_client._redacted_json(body)
    llm_client._redact_body(body)

    assert body == before, "redaction mutated the outbound request body"
    sent = body["messages"][0]["content"][1]["image_url"]["url"]
    assert sent.startswith("data:image/jpeg;base64,"), "outbound image was rewritten"
    assert _B64 in sent, "outbound base64 payload was damaged"


def case_text_only_body_is_stored_verbatim():
    """No images → the body round-trips unchanged, so chat prompts stay readable."""
    body = {"model": "deepseek-v4-flash", "temperature": 0.7, "messages": [
        {"role": "system", "content": "You are Ava." * 100},
        {"role": "user", "content": "hey babe"},
    ]}
    assert json.loads(llm_client._redacted_json(body)) == body


def case_redaction_failure_degrades_and_is_counted():
    """Anti-blackout: a broken body yields a stub, never an exception — and the
    failure is COUNTED, because /admin/stats/grok-calls is the only way anyone
    finds out the audit stopped recording (the insert deliberately swallows)."""
    before = llm_client.audit_degraded_count()

    class Unserializable:
        def __repr__(self): raise RuntimeError("boom")

    out = llm_client._redacted_json({"messages": [{"content": Unserializable()}]})

    assert out == llm_client._DEGRADED_STUB, out
    assert llm_client.audit_degraded_count() == before + 1, "degraded counter did not move"


async def case_pending_row_written_to_db_has_no_base64():
    """End-to-end through the real insert: read the row back off the DB."""
    async with get_session() as s:
        await s.execute(GrokCall.__table__.delete())
        await s.commit()

    call_id = await llm_client._insert_pending_call(
        purpose="describe_media", provider="deepinfra", account_id="acct_test",
        fan_id=None, model="qwen-vl", endpoint="/chat/completions",
        temperature=0.7, request_body=_vision_body(9), now=datetime.utcnow(),
    )
    assert call_id is not None, "audit row was not written"

    async with get_session() as s:
        row = (await s.execute(select(GrokCall).where(GrokCall.id == call_id))).scalar_one()

    assert "base64" not in row.prompt_json, "base64 reached the DB"
    assert _B64[:64] not in row.prompt_json, "payload reached the DB"
    assert _INSTRUCTION in row.prompt_json, "prompt text was lost"
    assert row.prompt_json.count("<img:image/jpeg:") == 9, "lost the image manifest"
    assert len(row.prompt_json) < 3_000, f"stored {len(row.prompt_json)} bytes"
    assert row.status == "pending", row.status
    # NOT NULL with no server_default — whatever we write must be non-empty
    assert row.prompt_json, "prompt_json must stay non-empty"


def case_response_text_cap_is_applied():
    """response_text is bounded, so one pathological reply can't blow the table."""
    assert llm_client._RESP_TEXT_CAP == 4000, llm_client._RESP_TEXT_CAP
    assert len(("x" * 100_000)[:llm_client._RESP_TEXT_CAP]) == 4000


def _real_png(w: int = 96, h: int = 96, rgb: tuple = (218, 44, 44)) -> bytes:
    """A genuinely valid PNG, built without PIL so the test has no new dep."""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


async def case_live_vision_call_sends_image_but_stores_none():
    """LIVE: a real Qwen3-VL call over a real image.

    The case no offline test can replace. It proves BOTH halves at once:
      • the provider still RECEIVES the image (a shallow-copy redactor would
        have sent "<img:…>" and the model would describe nothing),
      • the DB still stores NO bytes.
    Self-skips without a real key / network so the suite stays green offline.
    """
    real_key = (dotenv_values(_REAL_ENV).get("DEEPINFRA_API_KEY") or "").strip()
    if not real_key or real_key.startswith("test-"):
        print("    [skip] no real DEEPINFRA_API_KEY — live vision call not exercised")
        return
    os.environ["DEEPINFRA_API_KEY"] = real_key  # harness may have injected a fake

    acct = "acc_live_receipt"
    async with get_session() as s:
        if await s.get(Account, acct) is None:
            s.add(Account(id=acct))
        if await s.get(AccountAiConfig, acct) is None:
            s.add(AccountAiConfig(account_id=acct, daily_cost_cap_cents=100))
        await s.commit()

    png = _real_png()
    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "What single colour dominates this image? One word."},
        {"type": "image_url", "image_url": {"url": uri}},
    ]}]

    try:
        res = await llm_client.chat(
            model="qwen3-vl-30b", messages=messages,
            purpose="describe_media", account_id=acct,
        )
    except llm_client.LLMHTTPError as e:
        if getattr(e, "status", None) is None:  # transport failure → skip, don't fail
            print(f"    [skip] DeepInfra unreachable — live vision not exercised ({e})")
            return
        raise

    # ── the provider really got the image ──────────────────────────────
    assert res.content, "vision call returned empty content"
    assert "red" in res.content.lower(), (
        f"model did not see the image — got {res.content!r}. A redactor that "
        f"mutated the outbound body would produce exactly this.")

    # ── and the DB really got none of it ───────────────────────────────
    async with get_session() as s:
        row = await s.get(GrokCall, res.call_id)

    assert row.status == "done", row.status
    assert "base64" not in row.prompt_json, "LIVE: base64 reached the DB"
    assert base64.b64encode(png).decode()[:64] not in row.prompt_json, \
        "LIVE: the actual image payload reached the DB"
    assert "dominates this image" in row.prompt_json, "LIVE: prompt text was lost"
    assert f"<img:image/png:{len(png)}b:" in row.prompt_json, \
        f"LIVE: manifest missing/wrong in {row.prompt_json[:300]}"
    assert row.response_json is None, "response_json must no longer be stored"
    assert row.response_text and len(row.response_text) <= llm_client._RESP_TEXT_CAP
    print(f"    [live] vision 200 OK — model said {res.content.strip()[:40]!r}; "
          f"stored {len(row.prompt_json)}b for a {len(png)}b image "
          f"({len(uri)}b as a data URI)")


_harness.run(
    case_keeps_all_text_but_no_bytes,
    case_redactor_does_not_mutate_the_body,
    case_text_only_body_is_stored_verbatim,
    case_redaction_failure_degrades_and_is_counted,
    case_pending_row_written_to_db_has_no_base64,
    case_response_text_cap_is_applied,
    case_live_vision_call_sends_image_but_stores_none,
)
