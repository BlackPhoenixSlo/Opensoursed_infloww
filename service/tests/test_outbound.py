#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import pathlib  # noqa: E402

import llm_client  # noqa: E402
from db.models import Fan  # noqa: E402
from automations import _outbound  # noqa: E402
from automations._outbound import ConsistencyCtx, finalize_draft  # noqa: E402

_PERSONA = "Ella, 20, Argentine.\n\nTHESE ARE THE FACTS ABOUT YOU.\n- Lives in: Buenos Aires"


class _Res:
    def __init__(self, content):
        self.content = content
        self.parsed = None


def _fan() -> Fan:
    f = Fan(account_id="acc", fan_id=1)
    f.persona_claims_json = '[{"topic":"hometown","claim":"soy de buenos aires","at":"1"}]'
    return f


def _ctx(**kw) -> ConsistencyCtx:
    return ConsistencyCtx(fan=_fan(), persona=_PERSONA, model="deepseek-v4-flash", **kw)


def _run(text, **kw):
    return asyncio.run(finalize_draft(text, account_id="acc", fan_id=1,
                                      purpose="autoreply", **kw))



# Off-platform guard must see the model's own words before any later pass can disguise them.
def case_order_is_guard_then_consistency_then_strip():
    seen = {}

    async def _chat(**kw):
        seen["draft"] = kw["messages"][-1]["content"]
        return _Res(json.dumps({"contradicts": False, "which": "", "fix": ""}))

    real = llm_client.chat
    llm_client.chat = _chat
    try:
        out, leak = _run("add me on snapchat babe",
                         consistency=_ctx(last_inbound="where are you from?"))
        assert leak, f"an off-platform channel must be guarded: {leak}"
        assert "snapchat" not in seen.get("draft", "").lower(), \
            "the verifier saw the UNGUARDED draft — guard must run first"

        seen.clear()
        out2, leak2 = _run("im 20 and i live in cordoba 😏",
                           consistency=_ctx(), strip_emoji=True)
    finally:
        llm_client.chat = real

    assert not leak2, leak2
    assert "😏" in seen["draft"], "the strip ran BEFORE the verifier, not after"
    assert "😏" not in out2, f"emoji survived the strip: {out2!r}"


def case_leak_reasons_are_returned_not_just_logged():
    out, leak = _run("add me on snapchat")
    assert leak, "a leaked channel must come back as a reason, not only a log line"
    assert "snapchat" not in out.lower()
    clean, no_leak = _run("hey you 🙂")
    assert no_leak == [] or not no_leak, f"clean draft reported a leak: {no_leak}"
    assert clean == "hey you 🙂", "a clean draft must pass through byte-identical"


def case_a_rewrite_is_guarded_too():
    async def _chat(**kw):
        return _Res(json.dumps({"contradicts": True, "which": "wrong city",
                                "fix": "im in cordoba, add me on snapchat babe"}))

    real = llm_client.chat
    llm_client.chat = _chat
    try:
        out, leak = _run("im 20 and i live in chile", consistency=_ctx())
    finally:
        llm_client.chat = real

    assert "snapchat" not in out.lower(), \
        f"a model-written fix reached the wire unguarded: {out!r}"
    assert leak, "the rewrite's leak must be reported even though the draft was clean"


def case_an_unchanged_draft_is_not_guarded_twice():
    calls = []
    real_guard = _outbound.guard_offplatform

    def _counting(text, rng, *a, **kw):
        calls.append(text)
        return real_guard(text, rng, *a, **kw)

    async def _chat(**kw):
        return _Res(json.dumps({"contradicts": False, "which": "", "fix": ""}))

    real_chat = llm_client.chat
    llm_client.chat, _outbound.guard_offplatform = _chat, _counting
    try:
        out, leak = _run("im 20 and i live in cordoba", consistency=_ctx())
    finally:
        llm_client.chat, _outbound.guard_offplatform = real_chat, real_guard

    assert len(calls) == 1, f"a clean pass guarded twice: {calls}"
    assert out == "im 20 and i live in cordoba" and not leak


def case_consistency_is_opt_in_per_call():
    calls = []

    async def _chat(**kw):
        calls.append(kw)
        return _Res("{}")

    real = llm_client.chat
    llm_client.chat = _chat
    try:
        out, _ = _run("im 20 and i live in cordoba")
    finally:
        llm_client.chat = real
    assert calls == [], "the verifier ran without a ConsistencyCtx"
    assert out == "im 20 and i live in cordoba"


def case_strip_emoji_is_a_declared_argument():
    kept, _ = _run("hey 😏", strip_emoji=False)
    assert "😏" in kept, kept
    gone, _ = _run("hey 😏", strip_emoji=True)
    assert "😏" not in gone, gone
    default, _ = _run("hey 😏")
    assert "😏" in default, "strip_emoji defaulted ON"



def _declared_guards(engine: str) -> tuple[bool, str]:
    import ast

    path = pathlib.Path(__file__).resolve().parent.parent / "automations" / f"{engine}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "finalize_draft"]
    assert len(calls) == 1, \
        f"{engine}: expected exactly one chokepoint call, found {len(calls)}"
    kw = {k.arg: k.value for k in calls[0].keywords if k.arg}

    consistency = kw.get("consistency")
    wires = consistency is not None and any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "ConsistencyCtx" for n in ast.walk(consistency))

    strip = kw.get("strip_emoji")
    if strip is None:
        mode = "never"
    elif isinstance(strip, ast.Constant) and strip.value is True:
        mode = "always"
    elif isinstance(strip, ast.Name):
        mode = "flag"
    else:
        mode = ast.dump(strip)
    return (wires, mode)




def case_every_engine_declares_its_guard_set():
    expected = {
        "welcome_chatter_for_info":  (True,        "flag"),
        "autoreply":   (False,       "flag"),
        "full_ai_turn":  (False,     "flag"),
    }
    for name, want in expected.items():
        assert _declared_guards(name) == want, (
            f"{name}: its declared guard set changed", "got", _declared_guards(name),
            "want", want)

    import ast

    engines = pathlib.Path(__file__).resolve().parent.parent / "automations"
    for name in expected:
        tree = ast.parse((engines / f"{name}.py").read_text(encoding="utf-8"))
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        forked = called & {"guard_offplatform", "verify_self_consistency", "strip_emojis"}
        assert not forked, \
            f"{name} calls {sorted(forked)} directly — the chain forked again"


def case_chokepoint_owns_the_guards_not_the_engines():
    import ast

    path = pathlib.Path(_outbound.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    wanted = {"guard_offplatform", "verify_self_consistency", "strip_emojis"}

    seen: dict[str, list[str]] = {g: [] for g in wanted}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in wanted):
                seen[node.func.id].append(fn.name)

    for guard, callers in seen.items():
        assert callers, f"{guard} left the chokepoint entirely"
        assert len(callers) == 1, (
            f"{guard} is invoked from {sorted(set(callers))} — more than one call "
            "site means the guard chain has forked inside the chokepoint itself")


def case_a_rewrite_is_stripped_of_narration_too():
    async def _chat(**kw):
        return _Res(json.dumps({"contradicts": True, "which": "wrong city",
                                "fix": "*giggles* im in cordoba babe"}))

    real = llm_client.chat
    llm_client.chat = _chat
    try:
        out, _leak = _run("im 20 and i live in chile", consistency=_ctx())
    finally:
        llm_client.chat = real

    assert out == "im in cordoba babe", \
        f"a narrated fix reached the wire: {out!r}"


CASES = [
    case_order_is_guard_then_consistency_then_strip,
    case_a_rewrite_is_guarded_too,
    case_a_rewrite_is_stripped_of_narration_too,
    case_an_unchanged_draft_is_not_guarded_twice,
    case_leak_reasons_are_returned_not_just_logged,
    case_consistency_is_opt_in_per_call,
    case_strip_emoji_is_a_declared_argument,
    case_every_engine_declares_its_guard_set,
    case_chokepoint_owns_the_guards_not_the_engines,
]

if __name__ == "__main__":
    _real = llm_client.chat
    try:
        for c in CASES:
            c()
            print(f"  ok  {c.__name__}")
    finally:
        llm_client.chat = _real
    print("all cases passed")
