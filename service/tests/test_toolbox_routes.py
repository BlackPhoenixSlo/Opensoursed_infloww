#!/usr/bin/env python3
"""Toolbox drift test (docs/plans/ultra-mode/issues/04-toolbox.md, 05-mcp-server.md, 13-send-chain.md):
the registry (`toolbox_decide.TOOLS`) against the real app.

Cases:
  case_routes_exist        — every Tool's method + path is a route in `server.app`.
  case_args_match_route    — every arg (by alias) and every `fixed` key is a param of that route (query /
                             path for a GET, body field for a write); every required route param is a
                             required arg or fixed. An untyped body (dict / Request) is allowed for a
                             write tool only, which then must carry a `check` (its echo test).
                             `account_id` may be no body field: build_request binds it as X-Account-Id +
                             `?account_id=`, which the isolation middleware and `_resolve_account_id` read.
                             A tool with a `body` builder is checked on the body it builds from BODY_SAMPLES.
  case_paths_full_match    — a sample request to each tool's path is dispatched to exactly that route +
                             method by the token gate's own first-FULL-match walk, and is on the token
                             allowlist.
  case_no_token_tool_on_a_send_route — `route_clashes` (also raised at import): no token tool on a send
                             tool's route (the allowlist would open it), no two write tools on one route.
  case_checks_on_writes    — only a write or send tool carries a `check`; every send tool has one.
  case_schema_rules        — names unique + [a-z0-9_]{1,64}; descriptions set; args forbid unknown keys;
                             each client schema is a closed object with no $ref / $defs and no top-level
                             oneOf / anyOf / allOf; GET implies effect "read".
  case_send_text_declared  — send tools exist (mass_send, post_create, auto_mass, auto_story); each declares a
                             `text_kind` and `model_text` (each a str arg; none only for auto_story), and its
                             required string args are all model_text.
  case_open_pages_exist    — each Open path (and per-value path) is an `app/app/**/page.tsx` (a `[x]` segment
                             takes any one segment, a trailing `[[...x]]` zero or more: /of-manager/home).

Run: ./venv/bin/python service/tests/test_toolbox_routes.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

import re  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi.routing import APIRoute  # noqa: E402

import server  # noqa: E402
import token_auth  # noqa: E402
import toolbox_decide as td  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app" / "app"


def _route(tool: td.Tool) -> APIRoute:
    hits = [r for r in server.app.routes
            if isinstance(r, APIRoute) and r.path == tool.path and tool.method in r.methods]
    assert len(hits) == 1, f"{tool.name}: {tool.method} {tool.path} matches {len(hits)} routes"
    return hits[0]


def _route_params(tool: td.Tool, route: APIRoute) -> dict[str, bool]:
    """name (alias) → required, for what the tool can send: query + path for a GET, body fields for a write."""
    d = route.dependant
    out = {p.alias: p.field_info.is_required() for p in d.path_params}
    if tool.method in ("GET", "DELETE"):
        out.update({p.alias: p.field_info.is_required() for p in d.query_params})
        return out
    out.update({p.alias: False for p in d.query_params})  # e.g. ?account_id= beside a body
    body = d.body_params
    assert len(body) <= 1, f"{tool.name}: expected one body, got {[b.name for b in body]}"
    model = body[0].field_info.annotation if body else None
    if not hasattr(model, "model_fields"):
        # An untyped body (`payload: dict` or the raw Request): only a write tool, whose raw bearer
        # requests token_auth.write_refusal holds to the schema. That the route reads each arg is
        # test_toolbox_writes' job (every write tool runs there and its effect is asserted).
        assert tool.effect == "write", f"{tool.name}: untyped body needs a write tool"
        out.update({a: False for a in _args(tool) if a not in out})
        return out
    out.update({f.alias or n: f.is_required() for n, f in model.model_fields.items()})
    return out


def _args(tool: td.Tool) -> dict[str, bool]:
    return {f.alias or n: f.is_required() for n, f in tool.args.model_fields.items()}


BODY_SAMPLES = {"auto_mass": {"account_id": "1", "every_hours": 24, "text": "hi", "media_folder_id": 7,
                              "user_lists": ["fans"]},
                "auto_story": {"account_id": "1", "every_hours": 24, "folder_id": 7}}


def case_routes_exist() -> None:
    for t in td.TOOLS:
        _route(t)


def case_args_match_route() -> None:
    for t in td.TOOLS:
        params = _route_params(t, _route(t))
        args, fixed = _args(t), dict(t.fixed)
        if t.body is not None:
            args = {k: True for k in td.build_request(t, td.validate_args(t, BODY_SAMPLES[t.name])).json}
        for name in (*(a for a in args if a != "account_id" or "account_id" in params), *fixed):
            assert name in params, f"{t.name}: arg {name!r} is not a param of {t.method} {t.path} ({sorted(params)})"
        for name, required in params.items():
            if required:
                assert args.get(name) or name in fixed, f"{t.name}: route param {name!r} required, tool does not require it"


def _sample(tool: td.Tool, template: str) -> str:
    fields = tool.args.model_fields
    return re.sub(r"\{([a-z_]+)\}", lambda m: "4242" if fields[m.group(1)].annotation is int else "abcde12345abcde",
                  template)


def case_paths_full_match() -> None:
    allow = token_auth.allowlist()
    for t in td.TOOLS:
        scope = {"type": "http", "method": t.method, "path": _sample(t, t.path), "root_path": ""}
        got, _ = token_auth.matched(scope, server.app.routes)
        assert got == t.path, f"{t.name}: {t.method} {scope['path']} dispatches to {got}, not {t.path}"
        if t.effect != "send":
            assert (t.method, t.path) in allow, f"{t.name}: {t.method} {t.path} not on the token allowlist"


def case_no_token_tool_on_a_send_route() -> None:
    assert td.route_clashes(td.TOOLS) == []
    rules = next(t for t in td.TOOLS if t.name == "auto_mass")  # POST /admin/automation-rules: a send route
    read = td.Tool("zz_rules_read", "x", rules.method, rules.path, td.NoArgs, "read")
    write = td.Tool("zz_folder_write", "x", "POST", "/admin/vault-ai/of-folders", td.NoArgs, "write")
    assert any("zz_rules_read" in c for c in td.route_clashes(td.TOOLS + (read,)))  # would join the allowlist
    assert any("two write tools" in c for c in td.route_clashes(td.TOOLS + (write,)))  # write_tool ambiguous


def case_checks_on_writes() -> None:
    for t in td.TOOLS:
        assert t.effect in ("write", "send") or t.check is None, f"{t.name}: a check is for write/send tools"
        assert t.effect != "send" or t.check is not None, f"{t.name}: a send needs its echo check"


def case_schema_rules() -> None:
    names = [t.name for t in td.TOOLS]
    assert len(names) == len(set(names)), names
    for t in td.TOOLS:
        assert td.NAME_RE.fullmatch(t.name), t.name
        assert t.description.strip() and t.method in td.METHODS, t.name
        assert t.effect in ("read", "write", "send"), t.name
        if t.method == "GET":
            assert t.effect == "read", f"{t.name}: GET must be read"
        assert t.args.model_config.get("extra") == "forbid", t.name
        for schema in (td.as_mcp(t)["inputSchema"], td.as_openai(t)["function"]["parameters"],
                       td.as_anthropic(t)["input_schema"]):
            assert schema["type"] == "object" and schema["additionalProperties"] is False, (t.name, schema)
            assert "title" not in str(list(schema)), (t.name, schema)
            assert "$ref" not in str(schema) and "$defs" not in schema, (t.name, schema)
            assert not {"oneOf", "anyOf", "allOf"} & set(schema), (t.name, schema)
            assert set(schema.get("required", ())) <= set(schema["properties"]), (t.name, schema)
            for prop in schema["properties"]:
                assert re.fullmatch(r"[a-z_]{1,64}", prop), (t.name, prop)


def case_send_text_declared() -> None:
    sends = {t.name for t in td.TOOLS if t.effect == "send"}
    assert {"mass_send", "post_create", "auto_mass", "auto_story"} <= sends, sends
    for t in td.TOOLS:
        if t.effect != "send":
            assert not t.model_text and t.text_kind is None, t.name
            continue
        assert t.text_kind in ("mass", "post", "auto_mass", "auto_story"), f"{t.name}: send kind undeclared"
        assert t.model_text or t.text_kind == "auto_story", f"{t.name}: send text undeclared"
        fields = t.args.model_fields
        for path in t.model_text:
            assert path in fields and fields[path].annotation is str, (t.name, path, "not a str arg")
        free = [n for n, f in fields.items() if f.annotation is str and f.is_required()
                and n not in t.model_text and n != "account_id"]
        assert not free, f"{t.name}: required string args outside model_text: {free}"


def _pages() -> list[tuple[str, ...]]:
    out = []
    for p in APP.rglob("page.tsx"):
        parts = tuple(s for s in p.parent.relative_to(APP).parts if not (s.startswith("(") and s.endswith(")")))
        out.append(parts)
    return out


def _page_for(path: str, pages: list[tuple[str, ...]]) -> bool:
    want = tuple(s for s in path.strip("/").split("/") if s)
    for parts in pages:
        if parts and re.fullmatch(r"\[\[\.\.\.[^\]]+\]\]", parts[-1]):
            parts, want_n = parts[:-1], want[:len(parts) - 1]
        else:
            want_n = want
        if len(parts) == len(want_n) and all(
                a == b or (re.fullmatch(r"\[[^\]]+\]", a) and (re.fullmatch(r"\{[a-z_]+\}", b)
                                                              or re.fullmatch(r"[a-z0-9-]+", b)))
                for a, b in zip(parts, want_n)):
            return True
    return False


def case_open_pages_exist() -> None:
    pages = _pages()
    assert pages, APP
    for t in td.TOOLS:
        if t.open is None:
            continue
        for path in t.open.paths():
            assert _page_for(path, pages), f"{t.name}: no app page for {path}"


if __name__ == "__main__":
    _harness.run()
