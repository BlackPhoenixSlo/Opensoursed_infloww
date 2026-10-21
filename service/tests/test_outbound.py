#!/usr/bin/env python3
"""test_outbound.py — the shared send chokepoint every chat engine funnels through.

Four engines (all but two since retired) used to hand-copy the same whole-draft
guard sequence, and it drifted. Measured on the tree before `_outbound` existed,
for the two engines that remain:

  guard                    welcome_chatter_for_info  autoreply
  guard_offplatform                ✓                    ✓
  verify_self_consistency          ✓                    ✗
  strip_emojis                   gated                gated

`strip_emojis` is an ACCOUNT-WIDE operator setting that meant different
things depending on which engine answered (the retired selling engine ignored it). Nothing caught that, because "did
someone remember to paste this line" has no failure mode a test can see.

These cases give it one.

  case_order_is_guard_then_consistency_then_strip:
      the sequence is load-bearing — the off-platform scan must see the model's
      own words before any later pass can disguise them.
  case_a_rewrite_is_guarded_too:
      the hole this module shipped with: the consistency check returns MODEL-
      WRITTEN text, and it went out without passing the deterministic floor that
      exists because model output is not trusted.
  case_an_unchanged_draft_is_not_guarded_twice:
      …and the common path (no contradiction) still guards exactly once.
  case_leak_reasons_are_returned_not_just_logged:
      an engine may act on a guarded reply, so the flag has to come back out;
      swallowing it here would push that engine back to calling
      guard_offplatform itself.
  case_consistency_is_opt_in_per_call:
      no ctx ⇒ the verifier is never invoked (an engine that does not implement
      it, or an account opted out).
  case_strip_emoji_is_a_declared_argument:
      both directions, at the call site rather than by line-presence.
  case_every_engine_declares_its_guard_set:
      THE POINT. Pins the table above so a guard can never again be silently
      absent from an engine — including the known divergence, which is now
      declared rather than accidental.

Run: ./venv/bin/python service/tests/test_outbound.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

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


# ── the sequence ──────────────────────────────────────────────────────

def case_order_is_guard_then_consistency_then_strip():
    """Guard FIRST — the verifier must never be handed a draft still carrying the
    leak. Strip LAST — the verifier must see the text the engine actually
    generated, emoji included, or its read of her voice is not the real one.

    On a leak `guard_offplatform` replaces the whole draft with a deflection, so
    the check below is that the deflection (not the leak) is what reached the
    model. `last_inbound` is a biographical question so the verifier still fires
    on a deflection that makes no first-person claim of its own."""
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

        # …and the strip runs after the verifier, on a draft that does NOT leak.
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
    """The verifier returns MODEL-WRITTEN text, and guard_offplatform exists
    precisely because model output is not trusted. A fix that smuggles in an
    off-platform channel must be caught by the same floor as the original draft.

    This was the hole: the guard ran once, on the draft, and a rewrite went out
    unguarded — and because `leak` was computed before the rewrite, the engine was
    also told nothing had been guarded."""
    async def _chat(**kw):
        return _Res(json.dumps({"contradicts": True, "which": "wrong city",
                                "fix": "im in cordoba, add me on snapchat babe"}))

    real = llm_client.chat
    llm_client.chat = _chat
    try:
        # The DRAFT is clean — only the model's "fix" leaks.
        out, leak = _run("im 20 and i live in chile", consistency=_ctx())
    finally:
        llm_client.chat = real

    assert "snapchat" not in out.lower(), \
        f"a model-written fix reached the wire unguarded: {out!r}"
    assert leak, "the rewrite's leak must be reported even though the draft was clean"


def case_an_unchanged_draft_is_not_guarded_twice():
    """No contradiction ⇒ the verifier hands the draft back verbatim ⇒ no second
    guard pass. That is the common case and it must stay free."""
    calls = []
    real_guard = _outbound.guard_offplatform

    def _counting(text, rng, *a, **kw):
        # *a/**kw so this double tracks the real signature rather than pinning it:
        # `guard_offplatform` grew a `voice` argument for the male lane, and a stub
        # that hard-codes an arity turns any future addition into a test failure
        # that says nothing about the behaviour under test (how many times the
        # guard runs).
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
    """No ctx ⇒ the verifier is never reached. This is what autoreply
    does permanently and what an opted-out account does on every reply."""
    calls = []

    async def _chat(**kw):
        calls.append(kw)
        return _Res("{}")

    real = llm_client.chat
    llm_client.chat = _chat
    try:
        out, _ = _run("im 20 and i live in cordoba")   # a loud self-claim
    finally:
        llm_client.chat = real
    assert calls == [], "the verifier ran without a ConsistencyCtx"
    assert out == "im 20 and i live in cordoba"


def case_strip_emoji_is_a_declared_argument():
    kept, _ = _run("hey 😏", strip_emoji=False)
    assert "😏" in kept, kept
    gone, _ = _run("hey 😏", strip_emoji=True)
    assert "😏" not in gone, gone
    # Default is OFF: an engine that says nothing does not silently start stripping.
    default, _ = _run("hey 😏")
    assert "😏" in default, "strip_emoji defaulted ON"


# ── the point of the module ───────────────────────────────────────────

def _declared_guards(engine: str) -> tuple[bool, str]:
    """Read an engine's `finalize_draft(...)` call out of its AST and report the
    guard set it declares: `(wires_consistency, strip_mode)` where strip_mode is
    "never" (kwarg absent) / "always" (literal True) / "flag" (a name, i.e. the
    account setting).

    Parsed rather than grepped. The first version of this case string-matched the
    source, which is too weak for the one test whose whole job is to stop guard
    drift returning: `strip_emoji = False` with spaces would have slipped past the
    negative check, a mention inside a comment would have satisfied the positive
    one, and reformatting the call across lines would have broken both. Reading
    the actual call node means only a real change to the call can move it."""
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
        mode = ast.dump(strip)          # anything else must fail loudly
    return (wires, mode)




def case_every_engine_declares_its_guard_set():
    """Every chat engine must reach the chokepoint, and its guard set must be
    DECLARED at the call site rather than inferred from which lines got copied.

    The divergence below is real and deliberate, and this is where it is
    recorded: autoreply does not run the consistency check. Changing it is a
    behaviour change for live accounts and must come with its own decision —
    but it may not drift silently again."""
    expected = {
        # engine        consistency  strip_emoji
        "welcome_chatter_for_info":  (True,        "flag"),
        "autoreply":   (False,       "flag"),
    }
    for name, want in expected.items():
        assert _declared_guards(name) == want, (
            f"{name}: its declared guard set changed", "got", _declared_guards(name),
            "want", want)

    # And nobody guards outside the chokepoint any more. All THREE guards, not just
    # the off-platform one: an engine re-adding its own strip_emojis() or
    # verify_self_consistency() forks the chain exactly as thoroughly, and checking
    # one of three left the other two free to drift back.
    #
    # By AST, for the reason `_declared_guards` gives — and this one is not
    # hypothetical. A substring check for "strip_emojis(" matches
    # `load_strip_emojis(...)`, the CONFIG LOADER every engine legitimately calls,
    # so the naive version failed every engine the moment it was widened.
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
    """finalize_draft is the only place the three guards are invoked — and it
    invokes each exactly once.

    This used to assert `guard in src` against the module's source TEXT, which is
    satisfied by a mention in a comment, by a definition, or by a call sitting in
    some other function entirely. The claim is about WHERE the guards are called
    and HOW MANY times, so it is read off the AST the same way `_declared_guards`
    reads the engines — and for the same stated reason."""
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

    # ONE call site each. Not "one caller": `guard_offplatform` is invoked inside
    # the private `_guard`, which `finalize_draft` deliberately calls twice — the
    # draft, then the rewrite a consistency fix produced. That is the re-guard the
    # module exists to guarantee, so counting invocations would forbid the correct
    # design. What must never happen is a SECOND place that runs a guard, which is
    # what "the chokepoint owns them" actually means.
    for guard, callers in seen.items():
        assert callers, f"{guard} left the chokepoint entirely"
        assert len(callers) == 1, (
            f"{guard} is invoked from {sorted(set(callers))} — more than one call "
            "site means the guard chain has forked inside the chokepoint itself")


def case_a_rewrite_is_stripped_of_narration_too():
    """The same hole as case_a_rewrite_is_guarded_too, one rule down.

    The verifier's fix is model output, and the model narrates — six of the
    corpus's stage directions came out of one lane alone. So the narration strip
    has to be part of the SAME floor the guard is, which is why it lives inside
    `_guard` rather than running once at the top of finalize_draft. Stripping the
    draft only would leave the rewrite a hole exactly the width of the strip."""
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
