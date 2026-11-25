#!/usr/bin/env python3
import _harness

import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

import platforms
from side_effect_gate import classify
from of_client import OFClient

SERVICE = Path(__file__).resolve().parents[1]

CLIENT_ATTR = re.compile(r"\bclient\.(\w+)")
ROUTE_ATTR = re.compile(r"\b_get_client\(\)\.(\w+)")
CLIENT_LITERAL = re.compile(r"\b(?:getattr|hasattr)\(\s*(?:[\w.]*\bclient|_get_client\(\))\s*,\s*[\"'](\w+)[\"']")
ROUTE_LITERAL = re.compile(r"\b(?:getattr|hasattr)\(\s*_get_client\(\)\s*,\s*[\"'](\w+)[\"']")

UNREACHED: dict[str, dict[str, str]] = {
    "fansly_backend": {
        "_proxy_ip": "of_ws.OFWebSocket only; Fansly runs its own Live connection",
        "close_signed_sessions": "client_pool holds OFClient only; Backend modules pool their own Shims",
        "get": "httpx clients (translate, DoH), not a Platform client",
        "post": "httpx client (llm_client), not a Platform client",
        "get_json": "OnlyFans purchases poll; Backend accounts take revenue_tick first (purchase_poll, transaction_ingest)",
        "session_path": "set on a fresh OFClient inside OFClient.from_account",
    },
}


def scan(root: Path = SERVICE) -> tuple[dict[str, set[str]], set[str]]:
    where: dict[str, set[str]] = {}
    routes: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        if root / "tests" in path.parents:
            continue
        text = path.read_text()
        rel = str(path.relative_to(root))
        for rx in (CLIENT_ATTR, ROUTE_ATTR, CLIENT_LITERAL):
            for name in rx.findall(text):
                where.setdefault(name, set()).add(rel)
        routes |= set(ROUTE_ATTR.findall(text)) | set(ROUTE_LITERAL.findall(text))
    kept = {n: files for n, files in where.items() if hasattr(OFClient, n)}
    return kept, routes & set(kept)


def verdict(shim: type, name: str) -> str:
    return classify(shim, name)[0]


def failures(backends, surface: dict[str, set[str]], routes: set[str],
             unreached: dict[str, dict[str, str]]) -> list[str]:
    out: list[str] = []
    if not backends:
        out.append("registry yields no Backend module")
    if not surface:
        out.append("scan found no client calls")
    if not routes:
        out.append("scan found no route calls")
    for module in backends:
        shim = module.Shim
        allowed = unreached.get(module.__name__, {})
        for name in sorted(surface):
            v = verdict(shim, name)
            if v == "missing" and name in routes:
                out.append(f"{module.__name__}: route-reached {name} missing ({', '.join(sorted(surface[name]))})")
            elif v == "missing" and name not in allowed:
                out.append(f"{module.__name__}: {name} missing and not Unreached ({', '.join(sorted(surface[name]))})")
        for name in sorted(allowed):
            if name in routes:
                out.append(f"{module.__name__}: Unreached {name} is route-reached")
            elif verdict(shim, name) != "missing":
                out.append(f"{module.__name__}: Unreached {name} now resolves; drop it")
    return out


def case_every_backend_shim_holds_the_surface():
    backends = platforms.backends()
    surface, routes = scan()
    for module in backends:
        shim = module.Shim
        kinds: dict[str, list[str]] = {}
        for name in sorted(surface):
            kinds.setdefault(verdict(shim, name), []).append(name)
        route_misses = [n for n in kinds.get("missing", []) if n in routes]
        other_misses = [n for n in kinds.get("missing", []) if n not in routes]
        print(f"{module.__name__}: {len(surface)} names, {len(routes)} route-reached; "
              + ", ".join(f"{k} {len(v)}" for k, v in sorted(kinds.items()))
              + f"; route misses {len(route_misses)}, other misses {len(other_misses)}")
        for name in kinds.get("blocked", []):
            print(f"    Blocked {name}: {classify(shim, name)[1]}")
    problems = failures(backends, surface, routes, UNREACHED)
    assert not problems, f"{len(problems)} capability failures:\n  " + "\n  ".join(problems)


class _Built:
    def me(self):
        return {}

    def subscribers(self):
        return {}


_Module = SimpleNamespace(__name__="fake_backend", Shim=_Built)
_ROUTE = {"me": {"server.py"}}


def case_no_backend_fails():
    assert failures((), _ROUTE, {"me"}, {}) == ["registry yields no Backend module"]


def case_no_calls_fails():
    assert failures((_Module,), {}, {"me"}, {}) == ["scan found no client calls"]


def case_no_route_calls_fails():
    assert failures((_Module,), _ROUTE, set(), {}) == ["scan found no route calls"]


def case_route_miss_fails_even_when_unreached():
    surface = {**_ROUTE, "list_chats": {"server.py"}}
    got = failures((_Module,), surface, {"me", "list_chats"}, {"fake_backend": {"list_chats": "x"}})
    assert any("route-reached list_chats missing" in p for p in got), got
    assert any("Unreached list_chats is route-reached" in p for p in got), got


def case_non_route_miss_needs_unreached():
    surface = {**_ROUTE, "list_chats": {"a.py"}}
    assert failures((_Module,), surface, {"me"}, {"fake_backend": {"list_chats": "why"}}) == []
    assert failures((_Module,), surface, {"me"}, {}) != []


def case_unreached_that_resolves_fails():
    surface = {**_ROUTE, "subscribers": {"a.py"}}
    got = failures((_Module,), surface, {"me"}, {"fake_backend": {"subscribers": "stale"}})
    assert got == ["fake_backend: Unreached subscribers now resolves; drop it"], got


def case_scan_reads_bound_and_route_forms():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "tests").mkdir()
        (root / "a.py").write_text(
            "run.client.list_chats\nx = _get_client().me()\nhasattr(client, 'subscribers')\n"
            "getattr(_get_client(), 'vault_media', None)\nof_client.add_social_button\n")
        (root / "tests" / "t.py").write_text("client.add_users_link\n")
        surface, routes = scan(root)
    assert set(surface) == {"list_chats", "me", "subscribers", "vault_media"}, surface
    assert routes == {"me", "vault_media"}, routes


if __name__ == "__main__":
    _harness.run()
