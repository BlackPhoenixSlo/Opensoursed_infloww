"""
The vault + send path through the RELAY'S REAL HTTP ROUTES — not the shim.

Why this exists as its own gate: every other Fansly test calls the shim
directly, and on 2026-09-01 that is exactly what let a 24h outage hide. The
shim was perfect; `vault_cache` was serving `{"list": []}` rows memoised the
night before, when the vault really was empty. Folders and media both blank
in the browser, every direct shim probe green. Only a request that goes
through the actual FastAPI stack — cache layer included — sees that class of
bug, so this drives the same URLs the browser drives, at the page sizes the
browser uses (the cache key includes limit: a hand probe at limit=20 reads
fine while the app's limit=50 serves poison).

LIVE and read-only. It needs `service/sessions/accounts/<id>/fansly_session.json`
and talks to Fansly; it never sends a message — the send route is exercised
with the client's send_message swapped for a spy, so the assertion is about
what REACHES the client, which is where the snowflake-id risk lives.

    ./venv/bin/python fansly/test_relay_e2e.py
Exit 0 = pass, 2 = skipped (no session).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The documented test escape hatch (auth.allow_anonymous_account_access is read
# per call precisely so a test can flip it). Must be set BEFORE importing the
# app, and it only affects this process — nothing running is weakened.
os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
os.environ["SHARE_TOKEN"] = ""
sys.path.insert(0, str(REPO / "service"))

ACCOUNT = "700237824869654528"
GROUP = "900234531911344131"

_fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + label + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        _fails.append(label)


def main() -> int:
    session = REPO / "service" / "sessions" / "accounts" / ACCOUNT / "fansly_session.json"
    if not session.exists():
        print(f"SKIP: no Fansly session at {session}")
        return 2

    from starlette.testclient import TestClient
    import server
    import fansly_backend

    c = TestClient(server.app)
    h = {"X-Account-Id": ACCOUNT}

    # -- the picker's folder rail -------------------------------------------
    # limit=50 deliberately: that is what app/hooks/useVaultMedia.ts asks for,
    # and the cache is keyed on it. Probing a different size tests a different
    # cache entry and can pass while the app is broken.
    r = c.get("/api/of/v2/vault/lists?view=main&limit=50&offset=0", headers=h)
    check(r.status_code == 200, "GET /vault/lists (limit=50, the app's size)",
          f"{r.status_code} {r.text[:160]}")
    lists = r.json().get("list", []) if r.status_code == 200 else []
    check(bool(lists), "vault has folders — an EMPTY rail is the outage signature",
          "no folders; check vault_response_cache before the shim")
    check(all(isinstance(x.get("id"), str) for x in lists),
          "folder ids are STRINGS (snowflakes exceed JS 2^53)")

    # -- the picker's default grid ("All", no folder selected) --------------
    r = c.get("/api/of/v2/vault/media?limit=24&offset=0", headers=h)
    check(r.status_code == 200, "GET /vault/media (All)",
          f"{r.status_code} {r.text[:160]}")
    items = r.json().get("list", []) if r.status_code == 200 else []
    check(bool(items), "the All grid has media — this is the exact call that "
                       "served an empty poisoned cache row for ~24h")
    mid = items[0]["id"] if items else None
    check(isinstance(mid, str), "media ids are STRINGS over the wire")
    check(bool((items[0].get("files") or {}).get("thumb", {}).get("url")) if items else False,
          "media carries files.thumb.url (what the grid paints)")

    # -- folder filter -------------------------------------------------------
    if lists:
        r = c.get(f"/api/of/v2/vault/media?limit=24&list_id={lists[0]['id']}", headers=h)
        check(r.status_code == 200 and r.json().get("list"),
              "GET /vault/media?list_id= filters to that album",
              f"{r.status_code} {r.text[:160]}")

    # -- single-media resolve (500'd before vault_media_by_id existed) ------
    if mid:
        r = c.get(f"/api/of/v2/vault/media/{mid}", headers=h)
        check(r.status_code == 200 and r.json().get("id") is not None,
              "GET /vault/media/{id} resolves one media (Brain-panel thumbs)",
              f"{r.status_code} {r.text[:160]}")

    # -- send: what actually REACHES the client -----------------------------
    # No message is sent. The risk being pinned is that a Fansly snowflake
    # (~9.5e17) rides through JSON -> Pydantic `list[int|dict]` -> client
    # unchanged; a lossy hop here would attach the WRONG vault media.
    if mid:
        seen: dict = {}

        def spy(chat_id, text=None, **kw):
            seen.update({"chat_id": chat_id, "text": text, **kw})
            return {"id": "1", "fromUser": {"id": ACCOUNT},
                    "createdAt": "2026-09-01T00:00:00Z"}

        fansly_backend.get_client(ACCOUNT).send_message = spy
        r = c.post(f"/api/of/v2/chats/{GROUP}/messages", headers=h,
                   json={"text": "relay-e2e (spied, not sent)",
                         "media_files": [int(mid)], "price": 0})
        check(r.status_code == 200, "POST /chats/{id}/messages accepted",
              f"{r.status_code} {r.text[:200]}")
        got = (seen.get("media_files") or [None])[0]
        check(str(got) == str(mid),
              "the snowflake media id reaches the client EXACTLY",
              f"sent {mid}, client saw {got}")

    print()
    if _fails:
        print(f"{len(_fails)} check(s) failed: {'; '.join(_fails)}", file=sys.stderr)
        return 1
    print("relay end-to-end: vault + send work through the real HTTP routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
