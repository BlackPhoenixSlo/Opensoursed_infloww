#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (binds temp DB)

import ast  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

_SERVICE = Path(__file__).resolve().parents[1]
_ROUTES = {("server.py", "get_messages")}
_URL_ALLOWED = {
    ("of_reads.py", "get_messages"): "takes `peek`; its callers are checked above",
    ("of_reads.py", "get_pinned_messages"): "always sends PEEK_CURSOR (test_of_reads_peek)",
    ("of_reads.py", "search_chat"): "/messages/search does not mark read (measured 2026-11-22)",
    ("of_sends.py", "prepare_message"): "POST: a send",
    ("of_sends.py", "unpin_all_messages"): "DELETE: unpin",
}
_THREAD_URL = re.compile(r"/chats/[^/]+/messages")


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _never_none(v: ast.expr | None) -> bool:
    return (isinstance(v, (ast.BinOp, ast.Call))
            or (isinstance(v, ast.Constant) and v.value is not None))


def _may_be_first_page(call: ast.Call) -> bool:
    return _kw(call, "offset") is None and not _never_none(_kw(call, "before_id"))


def _peek_ok(call: ast.Call, rel: str, outer: str | None) -> bool:
    v = _kw(call, "peek")
    if isinstance(v, ast.Constant) and v.value is True:
        return True
    return (rel, outer) in _ROUTES and isinstance(v, ast.Name) and v.id == "peek"


def _is_get_messages(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "get_messages"


def _is_to_thread(func: ast.AST) -> bool:
    return ((isinstance(func, ast.Attribute) and func.attr == "to_thread")
            or (isinstance(func, ast.Name) and func.id == "to_thread"))


def scan(source: str, rel: str) -> tuple[list[str], int]:
    bad: list[str] = []
    checked = 0
    seen: set[int] = set()

    def visit(node: ast.AST, outer: str | None) -> None:
        nonlocal checked
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and outer is None:
                visit(n, n.name)
                continue
            if isinstance(n, ast.Call):
                target = None
                if _is_get_messages(n.func):
                    target = n.func
                elif _is_to_thread(n.func) and n.args and _is_get_messages(n.args[0]):
                    target = n.args[0]
                if target is not None:
                    seen.add(id(target))
                    checked += 1
                    if _may_be_first_page(n) and not _peek_ok(n, rel, outer):
                        bad.append(f"{rel}:{n.lineno}")
            visit(n, outer)

    tree = ast.parse(source)
    visit(tree, None)
    for n in ast.walk(tree):
        if _is_get_messages(n) and id(n) not in seen:
            bad.append(f"{rel}:{n.lineno} (unrecognised get_messages reference)")
    return bad, checked


def _of_url_text(n: ast.AST) -> str | None:
    if isinstance(n, ast.JoinedStr):
        if not any(isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)
                   and v.value.id == "API_BASE" for v in n.values):
            return None
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
    if isinstance(n, ast.Constant) and isinstance(n.value, str) and "/api2/v2/" in n.value:
        return n.value
    return None


def scan_urls(source: str, rel: str) -> list[str]:
    bad: list[str] = []
    docstrings = set()

    def visit(node: ast.AST, fn: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
            if not isinstance(node, (ast.ClassDef, ast.Module)):
                fn = node.name
        if id(node) not in docstrings:
            text = _of_url_text(node)
            if text is not None and _THREAD_URL.search(text) and (rel, fn) not in _URL_ALLOWED:
                bad.append(f"{rel}:{node.lineno} ({fn})")
            if isinstance(node, ast.JoinedStr):
                return
        for child in ast.iter_child_nodes(node):
            visit(child, fn)

    visit(ast.parse(source), "<module>")
    return bad


def _service_sources():
    for path in sorted(_SERVICE.rglob("*.py")):
        rel = path.relative_to(_SERVICE).as_posix()
        if not rel.startswith("tests/"):
            yield rel, path.read_text(encoding="utf-8")


def case_every_service_reader_peeks():
    bad: list[str] = []
    checked = 0
    for rel, src in _service_sources():
        b, c = scan(src, rel)
        bad += b
        checked += c
    assert not bad, "get_messages first page without peek=True:\n  " + "\n  ".join(bad)
    assert checked >= 9, f"scan found only {checked} readers: is it still walking service/?"


def case_every_thread_url_is_allowed():
    bad = [b for rel, src in _service_sources() for b in scan_urls(src, rel)]
    assert not bad, "OF thread URL outside the allowlist:\n  " + "\n  ".join(bad)
    sources = dict(_service_sources())
    stale = [k for k in _URL_ALLOWED if f"def {k[1]}(" not in sources.get(k[0], "")]
    assert not stale, f"allowlisted functions gone: {stale}"


def case_scan_catches_offenders():
    cases = [
        ("client.get_messages(1, limit=10)", 1),
        ("client.get_messages(1, limit=10, peek=False)", 1),
        ("client.get_messages(1, peek=flag)", 1),
        ("client.get_messages(1, **kw)", 1),
        ("client.get_messages(1, peek=True)", 0),
        ("client.get_messages(1, before_id=cursor)", 1),
        ("client.get_messages(1, before_id=cursor, peek=True)", 0),
        ("client.get_messages(1, before_id=int(m) + 1)", 0),
        ("client.get_messages(1, before_id=None)", 1),
        ("client.get_messages(1, order='asc', offset=0)", 0),
        ("asyncio.to_thread(client.get_messages, 1, limit=5)", 1),
        ("asyncio.to_thread(client.get_messages, 1, peek=True)", 0),
        ("asyncio.to_thread(client.get_messages, 1, order='asc', offset=o)", 0),
        ("asyncio.to_thread(lambda: client.get_messages(1, limit=10))", 1),
        ("asyncio.to_thread(lambda: client.get_messages(1, limit=10, peek=True))", 0),
        ("f = functools.partial(client.get_messages, 1)", 1),
        ("fn = client.get_messages", 1),
    ]
    for src, want in cases:
        got = len(scan(src, "x.py")[0])
        assert got == want, (src, got, want)
    assert scan("x = 1\nclient.get_messages(1)\n", "x.py")[0] == ["x.py:2"]
    route = "async def get_messages(peek=False):\n    return lambda: c().get_messages(1, peek=peek)\n"
    assert scan(route, "server.py")[0] == []
    assert scan(route, "other.py")[0] == ["other.py:2"]
    assert scan(route.replace("def get_messages", "def thread"), "server.py")[0] == ["server.py:2"]

    url_cases = [
        ('def f(self, c):\n    return self.get_json(f"{API_BASE}/chats/{c}/messages")', "x.py", 1),
        ('def f(c):\n    return get("/api2/v2/chats/1/messages?limit=5")', "x.py", 1),
        ('def get_pinned_messages(self, c):\n    return self.get_json(f"{API_BASE}/chats/{c}/messages")',
         "of_reads.py", 0),
        ('def get_pinned_messages(self, c):\n    return self.get_json(f"{API_BASE}/chats/{c}/messages")',
         "x.py", 1),
        ('def f(self, c):\n    """GET /api2/v2/chats/{c}/messages"""\n    return 1', "x.py", 0),
        ('def f(self, c):\n    return self.get_json(f"{API_BASE}/chats/{c}/media")', "x.py", 0),
        ('ROUTE = "/api/of/v2/chats/{chat_id}/messages"', "x.py", 0),
    ]
    for src, rel, want in url_cases:
        got = len(scan_urls(src, rel))
        assert got == want, (src, rel, got, want)


if __name__ == "__main__":
    _harness.run()
