#!/usr/bin/env python3
import _harness

import re
import tempfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import platforms
import fansly_shim
from side_effect_gate import LIVE_CHECK_LANES, classify
from of_client import OFClient

SERVICE = Path(__file__).resolve().parents[1]

CLIENT_ATTR = re.compile(r"\b(?:client|c)\.(\w+)")
ROUTE_ATTR = re.compile(r"\b_get_client\(\)\.(\w+)")
CLIENT_LITERAL = re.compile(r"\b(?:getattr|hasattr)\(\s*(?:[\w.]*\bclient|_get_client\(\))\s*,\s*[\"'](\w+)[\"']")
ROUTE_LITERAL = re.compile(r"\b(?:getattr|hasattr)\(\s*_get_client\(\)\s*,\s*[\"'](\w+)[\"']")
ROUTE_CALL = re.compile(r"\b_platform_call\(\s*[\"'](\w+)[\"']")

UNREACHED: dict[str, dict[str, str]] = {
    "fansly_backend": {
        "_proxy_ip": "of_ws.OFWebSocket only; Fansly runs its own Live connection",
        "close_signed_sessions": "client_pool holds OFClient only; Backend modules pool their own Shims",
        "get": "httpx clients (translate, DoH), not a Platform client",
        "post": "httpx client (llm_client), not a Platform client",
        "get_json": "OnlyFans purchases poll; Backend accounts take revenue_tick first (purchase_poll, transaction_ingest)",
        "session_path": "set on a fresh OFClient inside OFClient.from_account",
        "request": "httpx client (toolbox relay calls), not a Platform client",
        "unread_chat_fan_ids": "audiences.resolve_mass_audience only, whose callers are mass sends Fansly refuses first (02f)",
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
        for rx in (CLIENT_ATTR, ROUTE_ATTR, CLIENT_LITERAL, ROUTE_CALL):
            for name in rx.findall(text):
                where.setdefault(name, set()).add(rel)
        routes |= set(ROUTE_ATTR.findall(text)) | set(ROUTE_LITERAL.findall(text)) | set(ROUTE_CALL.findall(text))
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


def verdict_counts(shim, surface) -> dict[str, int]:
    return dict(sorted(Counter(v for n in surface if (v := verdict(shim, n)) != "live_check").items()))


def live_checks(shim, surface) -> set[str]:
    return {n for n in surface if verdict(shim, n) == "live_check"} | LIVE_CHECK_LANES


def case_every_backend_shim_holds_the_surface():
    backends = platforms.backends()
    surface, routes = scan()
    for module in backends:
        shim = module.Shim
        of = lambda v: [n for n in sorted(surface) if verdict(shim, n) == v]  # noqa: E731
        missing = of("missing")
        route_misses = [n for n in missing if n in routes]
        other_misses = [n for n in missing if n not in routes]
        live = live_checks(shim, surface)
        print(f"{module.__name__}: {len(surface)} names, {len(routes)} route-reached; "
              + ", ".join(f"{k} {n}" for k, n in verdict_counts(shim, surface).items())
              + f"; live_check {len(live)}"
              + f"; route misses {len(route_misses)}, other misses {len(other_misses)}")
        for name in of("blocked"):
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
            "getattr(_get_client(), 'vault_media', None)\nof_client.add_social_button\n"
            "c = client()\ngot = c.create_promo(**kw)\nabc.finish_promo\n"
            "_platform_call(\"search_chat\", \"search chat\")(x)\nmy_platform_call('pin_message', 'pin')\n")
        (root / "tests" / "t.py").write_text("client.add_users_link\n")
        surface, routes = scan(root)
    assert set(surface) == {"create_promo", "list_chats", "me", "search_chat", "subscribers", "vault_media"}, surface
    assert routes == {"me", "search_chat", "vault_media"}, routes


def case_fansly_counts_hold_the_lists_phase_verdicts():
    surface, routes = scan()
    shim = platforms.FANSLY.backend.Shim
    live = live_checks(shim, surface)
    assert live == {"delete_list", "block_user", "priority_mass", "nudge_online"}, live
    assert {n: verdict(shim, n) for n in ("list_users_in", "rename_list", "unblock_user", "unsend_mass_message",
                                        "engagement_messages", "mass_message_history", "scheduled_messages")} == {
        "list_users_in": "built", "rename_list": "built", "unblock_user": "blocked", "unsend_mass_message": "blocked",
        "engagement_messages": "built", "mass_message_history": "built", "scheduled_messages": "built"}
    assert surface.get("unsend_mass_message") == {"automations/unsend_messages.py"}, surface.get("unsend_mass_message")
    assert {"list_users_in", "rename_list", "block_user", "unblock_user"} <= routes, routes
    assert verdict_counts(shim, surface) == FANSLY_COUNTS, verdict_counts(shim, surface)


FANSLY_BLOCKED_READS = (
    ("transactions", "Fansly per-sale feed unproven; the earnings capture holds aggregates only"),
    ("payout_requests", "Fansly payouts not captured"),
    ("payout_balances", "Fansly wallet balance unit and shape unproven; no non-zero wallet seen"),
    ("earnings_chart", "Fansly earnings aggregates captured; category map and paging unproven; no Fansly caller"),
    ("queued_message", "no single-row GET; its only caller is the queued-message edit, graded I"),
    ("mass_message_buyers", "no buyers in broadcast stats; a priced broadcast needs a Proof purchase"),
)
FANSLY_COUNTS = {"blocked": 148, "built": 58, "missing": 8, "unsupported": 25}


def case_fansly_blocked_reads_refuse_before_any_request():
    shim = platforms.FANSLY.backend.Shim
    sent: list = []

    class _Probe(shim):
        def __init__(self):
            pass

        def _request(self, *a, **k):
            sent.append(a)
            return {}

    for name, reason in FANSLY_BLOCKED_READS:
        assert classify(shim, name) == ("blocked", reason), (name, classify(shim, name))
        try:
            getattr(_Probe(), name)()
        except fansly_shim.FanslyBlocked as e:
            assert e.status_code == 501 and str(e) == f"{name}: {reason}", (name, e)
        else:
            raise AssertionError(f"{name} answered instead of refusing")
    assert sent == [], sent


if __name__ == "__main__":
    _harness.run()
