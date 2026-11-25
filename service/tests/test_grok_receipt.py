#!/usr/bin/env python3
import _harness

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

_B64 = "QUJDRA==" * 25_000
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
    body = _vision_body(3)
    assert len(json.dumps(body)) > 500_000, "fixture too small to be meaningful"

    stored = llm_client._redacted_json(body)

    assert "base64" not in stored, "base64 reached the DB value"
    assert _B64[:64] not in stored, "payload reached the DB value"
    assert _INSTRUCTION in stored, "prompt TEXT was lost — the whole point"
    assert stored.count("<img:image/jpeg:") == 3, "lost an image manifest entry"
    assert f"<img:image/jpeg:{llm_client._b64_decoded_len(_B64)}b:" in stored
    assert len(stored) < 2_000, f"stored {len(stored)} bytes"


def case_redactor_does_not_mutate_the_body():
    body = _vision_body(2)
    before = copy.deepcopy(body)

    llm_client._redacted_json(body)
    llm_client._redact_body(body)

    assert body == before, "redaction mutated the outbound request body"
    sent = body["messages"][0]["content"][1]["image_url"]["url"]
    assert sent.startswith("data:image/jpeg;base64,"), "outbound image was rewritten"
    assert _B64 in sent, "outbound base64 payload was damaged"


def case_text_only_body_is_stored_verbatim():
    body = {"model": "deepseek-v4-flash", "temperature": 0.7, "messages": [
        {"role": "system", "content": "You are Ava." * 100},
        {"role": "user", "content": "hey babe"},
    ]}
    assert json.loads(llm_client._redacted_json(body)) == body


def case_redaction_failure_degrades_and_is_counted():
    before = llm_client.audit_degraded_count()

    class Unserializable:
        def __repr__(self): raise RuntimeError("boom")

    out = llm_client._redacted_json({"messages": [{"content": Unserializable()}]})

    assert out == llm_client._DEGRADED_STUB, out
    assert llm_client.audit_degraded_count() == before + 1, "degraded counter did not move"


async def case_pending_row_written_to_db_has_no_base64():
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
    assert row.prompt_json, "prompt_json must stay non-empty"


def case_response_text_cap_is_applied():
    assert llm_client._RESP_TEXT_CAP == 4000, llm_client._RESP_TEXT_CAP
    assert len(("x" * 100_000)[:llm_client._RESP_TEXT_CAP]) == 4000


def _real_png(w: int = 96, h: int = 96, rgb: tuple = (218, 44, 44)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


async def case_live_vision_call_sends_image_but_stores_none():
    real_key = (dotenv_values(_REAL_ENV).get("DEEPINFRA_API_KEY") or "").strip()
    if not real_key or real_key.startswith("test-"):
        print("    [skip] no real DEEPINFRA_API_KEY — live vision call not exercised")
        return
    os.environ["DEEPINFRA_API_KEY"] = real_key

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
        if getattr(e, "status", None) is None:
            print(f"    [skip] DeepInfra unreachable — live vision not exercised ({e})")
            return
        raise

    assert res.content, "vision call returned empty content"
    assert "red" in res.content.lower(), (
        f"model did not see the image — got {res.content!r}. A redactor that "
        f"mutated the outbound body would produce exactly this.")

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
