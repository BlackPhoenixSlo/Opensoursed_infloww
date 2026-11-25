# Native, not OpenAI-compat: compat does not prompt-cache, so the help bot's ~39k-token system prompt billed in full on every answer.
# Opus/Sonnet/Haiku 5.5 all 400 on thinking:enabled; Opus 5.5 also 400s on disabled, Sonnet 5.5 wants between_tools, Haiku 5.5 takes disabled.
from __future__ import annotations

from typing import Any

ANTHROPIC_VERSION = "2023-06-01"

# Required on the native API; 4096 matches DeepSeek's default and leaves adaptive thinking room (thinking counts toward it).
MAX_TOKENS = 4096

_CACHE = {"type": "ephemeral"}

_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
           "tool_use": "tool_calls", "refusal": "content_filter"}


class NativeShapeError(ValueError):
    pass


def headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json", "Accept": "application/json"}


def _text(content: Any) -> str:
    # Claude rows are not vision_ok, so an image part here is a routing bug: refuse it.
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
    # The LAST system block carries the cache breakpoint, so everything up to it is one cached prefix.
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
    # prompt_tokens is the WHOLE prompt (remainder + cache write + read), matching OpenAI-shape providers.
    # max_tokens (thinking shares it) leaves a fragment: content "" so the caller takes its empty-answer path; usage is kept.
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
