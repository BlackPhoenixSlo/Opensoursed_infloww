#!/usr/bin/env python3
"""Toolbox drift test (docs/plans/ultra-mode/issues/04-toolbox.md, 05-mcp-server.md, 13-send-chain.md):
the registry (`toolbox_decide.TOOLS`) against the real app.

Cases:
  case_routes_exist        — every Tool's method + path is a route in `server.app`.
  case_args_match_route    — every arg (by alias) and every `fixed` key is a param of that route (query /
                             path for a GET, body field for a write); every required route param is a
                             required arg or fixed. An untyped body (dict / Request) is allowed for a
                             write tool only, which then must carry a `check` (its echo test).
  case_paths_full_match    — a sample request to each tool's path is dispatched to exactly that route +
                             method by the token gate's own first-FULL-match walk, and is on the token
                             allowlist.
  case_checks_on_writes    — only a write tool carries a `check`.
  case_schema_rules        — names unique + [a-z0-9_]{1,64}; descriptions set; args forbid unknown keys;
                             each client schema is a closed object with no $ref / $defs and no top-level
                             oneOf / anyOf / allOf; GET implies effect "read".
  case_send_text_declared  — a send tool with a string arg declares `model_text` (each an arg) and a
                             `text_kind` (vacuous until step 4 adds send tools).
  case_open_pages_exist    — each Open path (and per-value path) is an `app/app/**/page.tsx`.

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


def case_routes_exist() -> None:
    for t in td.TOOLS:
        _route(t)


def case_args_match_route() -> None:
    for t in td.TOOLS:
        params = _route_params(t, _route(t))
        args, fixed = _args(t), dict(t.fixed)
        for name in (*args, *fixed):
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


def case_checks_on_writes() -> None:
    for t in td.TOOLS:
        assert t.effect == "write" or t.check is None, f"{t.name}: a check is for write tools"


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
    for t in td.TOOLS:
        if t.effect != "send":
            assert not t.model_text and t.text_kind is None, t.name
            continue
        strings = [n for n, f in t.args.model_fields.items() if "str" in str(f.annotation)]
        if strings:
            assert t.model_text and t.text_kind in ("mass", "post"), f"{t.name}: send text undeclared"
            for path in t.model_text:
                assert path.split(".")[0] in t.args.model_fields, (t.name, path)


def _pages() -> list[tuple[str, ...]]:
    out = []
    for p in APP.rglob("page.tsx"):
        parts = tuple(s for s in p.parent.relative_to(APP).parts if not (s.startswith("(") and s.endswith(")")))
        out.append(parts)
    return out


def _page_for(path: str, pages: list[tuple[str, ...]]) -> bool:
    want = tuple(s for s in path.strip("/").split("/") if s)
    for parts in pages:
        if len(parts) == len(want) and all(
                a == b or (re.fullmatch(r"\[[^\]]+\]", a) and re.fullmatch(r"\{[a-z_]+\}", b))
                for a, b in zip(parts, want)):
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
