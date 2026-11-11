"""Anthropic's native Messages API, as a request/response adapter for llm_client.

Why native and not the OpenAI-compat layer: the compat layer does not prompt-
cache ("Prompt caching is not supported") and reports no cached tokens, so the
help bot's ~39k-token stable system prompt billed in full on every answer
(~1620 millicents on Opus 5.5, measured 2026-11-07). Here the system prompt
travels as a content block with `cache_control: ephemeral` (5-min TTL): the
first call writes the cache at 1.25x input, repeats read it at the hit rate.

The seam is two pure functions. `chat()` still builds its one OpenAI-shape body
(so `sends_temperature`, `reasoning_body`, `json_object_ok` keep their meaning)
and hands it to `to_native_body`; the reply goes through `to_openai_response`
so the shared parse / cost / audit path reads it unchanged. Key resolution,
the cap hold, retries and error mapping (`_fire`) stay shared.

Wire facts (measured 2026-11-07 against POST /v1/messages):
  - Opus/Sonnet/Haiku 5.5 all 400 on `thinking: enabled` ("Use
    thinking.type.adaptive"); Opus 5.5 also 400s on `disabled`, Sonnet 5.5
    wants `between_tools`; Haiku 5.5 takes `disabled`.
  - usage splits the prompt into `input_tokens` (uncached remainder),
    `cache_creation_input_tokens` and `cache_read_input_tokens`.
"""
from __future__ import annotations

from typing import Any

ANTHROPIC_VERSION = "2023-06-01"

# Required on the native API (the compat layer defaulted it). No other lane
# caps output today; 4096 matches DeepSeek's own default and leaves adaptive
# thinking room on top of a help answer (thinking counts toward it).
MAX_TOKENS = 4096

_CACHE = {"type": "ephemeral"}

# Native stop_reason → the OpenAI finish_reason the rest of the code knows.
_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
           "tool_use": "tool_calls", "refusal": "content_filter"}


class NativeShapeError(ValueError):
    """The OpenAI body holds something this adapter does not translate."""


def headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json", "Accept": "application/json"}


def _text(content: Any) -> str:
    """OpenAI message content (str or text parts) → plain text. Claude rows are
    not vision_ok, so an image part here is a routing bug: refuse it."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                out.append(part.get("text") or "")
            else:
                raise NativeShapeError(f"unsupported content part: {part!r:.80}")
        return "".join(out)
    raise NativeShapeError(f"unsupported content: {type(content).__name__}")


def to_native_body(body: dict[str, Any], max_tokens: int = MAX_TOKENS) -> dict[str, Any]:
    """OpenAI chat body → Messages API body.

    System messages become `system` blocks; the LAST carries the cache
    breakpoint, so everything up to it (tools none, system all) is one cached
    prefix. Other body keys that both shapes share (`temperature`, `thinking`)
    pass through as-is; `stream` and OpenAI-only keys are dropped
    (`response_format`: llm_client.chat refuses it for this wire first)."""
    system: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    for m in body.get("messages") or []:
        role = m.get("role")
        if role == "system":
            system.append({"type": "text", "text": _text(m.get("content"))})
        elif role in ("user", "assistant"):
            messages.append({"role": role, "content": _text(m.get("content"))})
        else:
            raise NativeShapeError(f"unsupported role: {role!r}")
    if system:
        system[-1]["cache_control"] = dict(_CACHE)
    out: dict[str, Any] = {"model": body["model"], "max_tokens": max_tokens,
                           "messages": messages}
    if system:
        out["system"] = system
    for k in ("temperature", "thinking", "output_config"):
        if k in body:
            out[k] = body[k]
    return out


def to_openai_response(data: dict[str, Any]) -> dict[str, Any]:
    """Messages API reply → the OpenAI chat-completion shape `_finalize_ok` reads.

    `prompt_tokens` is the WHOLE prompt (remainder + cache write + cache read),
    matching what OpenAI-shape providers report, with the read slice in
    `prompt_tokens_details.cached_tokens` and the write slice in
    `cache_creation_input_tokens` (priced at the write rate).

    `stop_reason: max_tokens` (adaptive thinking shares MAX_TOKENS with the
    answer) leaves a fragment, not an answer: content comes back "" so the
    caller takes its empty-answer path; finish_reason still says "length" and
    the usage (billed) is kept."""
    blocks = data.get("content") or []
    stop = data.get("stop_reason")
    text = "" if stop == "max_tokens" else "".join(
        b.get("text") or "" for b in blocks if b.get("type") == "text")
    thinking = "".join(b.get("thinking") or "" for b in blocks
                       if b.get("type") == "thinking")
    u = data.get("usage") or {}
    rest = int(u.get("input_tokens") or 0)
    write = int(u.get("cache_creation_input_tokens") or 0)
    read = int(u.get("cache_read_input_tokens") or 0)
    out_tok = u.get("output_tokens")
    details = u.get("output_tokens_details")
    usage: dict[str, Any] = {
        "prompt_tokens": rest + write + read,
        "completion_tokens": out_tok,
        "total_tokens": rest + write + read + int(out_tok or 0),
        "prompt_tokens_details": {"cached_tokens": read},
        "cache_creation_input_tokens": write,
    }
    if isinstance(details, dict) and details.get("thinking_tokens") is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": details["thinking_tokens"]}
    return {
        "id": data.get("id"),
        "model": data.get("model"),
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": text,
                                 "reasoning_content": thinking or None},
                     "finish_reason": _FINISH.get(stop, stop)}],
        "usage": usage,
    }
