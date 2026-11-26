from __future__ import annotations

import _harness

import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

import tempfile  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import actor_token  # noqa: E402

KEYS = ("OI_CELL_ROLE", "OI_CELL_ACTOR_KEY_FILE", "OI_CELL_ACTOR_PUBKEY")


@contextlib.contextmanager
def _role(role: str, *, key: bool, pub: str | None = None):
    old = {k: os.environ.get(k) for k in KEYS}
    with tempfile.TemporaryDirectory() as t:
        made = actor_token.new_key(Path(t))
        os.environ["OI_CELL_ROLE"] = role
        os.environ.pop("OI_CELL_ACTOR_KEY_FILE", None)
        os.environ.pop("OI_CELL_ACTOR_PUBKEY", None)
        if key:
            os.environ["OI_CELL_ACTOR_KEY_FILE"] = str(Path(t) / "actor_ed25519.pem")
        if pub is not None:
            os.environ["OI_CELL_ACTOR_PUBKEY"] = pub or made
        try:
            yield made, Path(t)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


def _refused(needle: str) -> None:
    try:
        actor_token.configure("acme")
    except SystemExit as e:
        assert needle in str(e.code), e.code
        return
    raise AssertionError(f"configure passed; expected a refusal naming {needle!r}")


def case_env_unset_imports_nothing_new() -> None:
    import auth
    import chatters  # noqa: F401
    assert auth._ACTOR is None


def case_round_trip_and_claims() -> None:
    with _role("control", key=True):
        actor_token.configure("acme")
        now = time.time()
        tok = actor_token.mint("user", "u1", ggen=7, now=now)
        c, why = actor_token.verify(tok, now)
        assert why == "" and c == actor_token.Claims("acme", "user", "u1", "u1", False, int(now), int(now) + 900, 7), c
        imp, _ = actor_token.verify(actor_token.mint("user", "u1", ggen=7, eff_id="u2", now=now), now)
        assert imp.ro is True and imp.eff_id == "u2"
        capped, _ = actor_token.verify(actor_token.mint("user", "u1", ggen=7, eff_id="u2", now=now,
                                                        until=int(now) + 60), now)
        assert capped.exp == int(now) + 60, "impersonation TTL must cap the token"
        assert actor_token.verify(tok, now + 900)[1] == "actor_expired"
        assert actor_token.verify(tok, now - 120)[1] == "actor_invalid", "issued in the future"
        p, s = tok.split(".")
        forged = actor_token._b64(json.dumps({**json.loads(actor_token._unb64(p)), "id": "root"}).encode())
        assert actor_token.verify(f"{forged}.{s}", now)[1] == "actor_invalid"
        for junk in ("", "x", "a.b.c", f"{p}.", "%%%.%%%"):
            assert actor_token.verify(junk, now)[1] == "actor_invalid", junk
        actor_token.configure("other")
        assert actor_token.verify(tok, now)[1] == "actor_invalid", "another Agency's token"


def case_data_cell_verifies_but_cannot_mint() -> None:
    with _role("control", key=True) as (pub, _d):
        actor_token.configure("acme")
        tok = actor_token.mint("chatter", "c1", ggen=1)
    with _role("data", key=False, pub=pub):
        actor_token.configure("acme")
        assert actor_token.DATA and actor_token.verify(tok)[0].kind == "chatter"
        try:
            actor_token.mint("user", "u1", ggen=1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("a data Cell minted a token")


def case_key_refusals() -> None:
    with _role("data", key=True):
        _refused("only the Control cell may hold the Actor token private key")
    with _role("control", key=True, pub=actor_token._b64(b"\x01" * 32)):
        _refused("does not match")
    with _role("data", key=False, pub="not-a-key"):
        _refused("not an Ed25519 public key")
    with _role("data", key=False):
        actor_token.configure("acme")
        assert actor_token.verify("a.b")[1] == "actor_invalid", "no key: every token refused"


def case_refusal_is_hard_only_on_data_cells() -> None:
    with _role("data", key=False, pub=""):
        actor_token.configure("acme")
        r = actor_token.refused("/admin/chats/recent", "actor_stale")
        assert r is not None and r.status_code == 401 and json.loads(r.body) == {"detail": {"error": "actor_stale"}}
        assert r.headers["cache-control"] == "no-store"
        for p in ("/livez", "/health", "/fleet/agency-copy", "/share/x", "/t/x", "/auth/me", "/chatter/me"):
            assert actor_token.refused(p, "actor_stale") is None, p
    with _role("control", key=True):
        actor_token.configure("acme")
        assert actor_token.refused("/admin/chats/recent", "actor_stale") is None


_harness.run()
