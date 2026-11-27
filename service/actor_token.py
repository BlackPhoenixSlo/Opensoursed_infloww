from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

log = logging.getLogger("of-relay.actor-token")

COOKIE = "oi_actor"
VERSION = 1
TTL_S = 900
SKEW_S = 60
# Only data cells hard-refuse a bad token; these stay as without a cookie so probes, share links and the Agency copy work.
_AGED_OPEN = ("/health", "/livez", "/fleet/", "/t/", "/share/", "/api/cell/hold", "/.well-known/")
_OPEN = (*_AGED_OPEN, "/auth/", "/chatter/")

ROLE = os.environ.get("OI_CELL_ROLE", "")
DATA = ROLE == "data"
_private: Ed25519PrivateKey | None = None
_public: Ed25519PublicKey | None = None
_agency = ""


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _raw_public(key: Ed25519PublicKey) -> str:
    return _b64(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def configure(agency: str) -> None:
    global _private, _public, _agency, ROLE, DATA
    _agency, _private, _public = agency, None, None
    ROLE = os.environ.get("OI_CELL_ROLE", "")
    DATA = ROLE == "data"
    key_file = os.environ.get("OI_CELL_ACTOR_KEY_FILE", "").strip()
    pub = os.environ.get("OI_CELL_ACTOR_PUBKEY", "").strip()
    if key_file and ROLE != "control":
        raise SystemExit("Cells: refusing to start: only the Control cell may hold the Actor token private key"
                         " (unset OI_CELL_ACTOR_KEY_FILE on this Cell)")
    if key_file:
        try:
            key = serialization.load_pem_private_key(Path(key_file).read_bytes(), password=None)
        except (OSError, ValueError) as e:
            raise SystemExit(f"Cells: refusing to start: OI_CELL_ACTOR_KEY_FILE {key_file} is unreadable ({e})")
        if not isinstance(key, Ed25519PrivateKey):
            raise SystemExit(f"Cells: refusing to start: {key_file} is not an Ed25519 private key")
        if pub and pub != _raw_public(key.public_key()):
            raise SystemExit("Cells: refusing to start: OI_CELL_ACTOR_PUBKEY does not match OI_CELL_ACTOR_KEY_FILE")
        _private, _public = key, key.public_key()
    elif pub:
        try:
            _public = Ed25519PublicKey.from_public_bytes(_unb64(pub))
        except ValueError as e:
            raise SystemExit(f"Cells: refusing to start: OI_CELL_ACTOR_PUBKEY is not an Ed25519 public key ({e})")
    if _public is None:
        log.error("Cells: no Actor token key (OI_CELL_ACTOR_PUBKEY / OI_CELL_ACTOR_KEY_FILE): every oi_actor is refused")
    elif ROLE == "control" and _private is None:
        log.error("Cells: Control cell has no OI_CELL_ACTOR_KEY_FILE: it cannot mint oi_actor")


@dataclass(frozen=True)
class Claims:
    agency: str
    kind: str
    id: str
    eff_id: str
    ro: bool
    iat: int
    exp: int
    ggen: int


def mint(kind: str, pid: str, *, ggen: int, eff_id: str | None = None, now: float | None = None,
         until: int | None = None) -> str:
    if _private is None:
        raise RuntimeError("only the Control cell mints Actor tokens")
    iat = int(now if now is not None else time.time())
    eff = eff_id or pid
    body = {"v": VERSION, "agency": _agency, "kind": kind, "id": pid, "eff_id": eff, "ro": eff != pid,
            "iat": iat, "exp": min(iat + TTL_S, until if until is not None else iat + TTL_S), "ggen": int(ggen)}
    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    return f"{_b64(payload)}.{_b64(_private.sign(payload))}"


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def verify(raw: str, now: float | None = None) -> tuple[Claims | None, str]:
    if _public is None:
        return None, "actor_invalid"
    try:
        p64, s64 = raw.split(".")
        payload = _unb64(p64)
        _public.verify(_unb64(s64), payload)
        d = json.loads(payload)
    except (ValueError, InvalidSignature):
        return None, "actor_invalid"
    ok = (isinstance(d, dict) and d.get("v") == VERSION and d.get("agency") == _agency
          and d.get("kind") in ("user", "chatter") and all(isinstance(d.get(k), str) and d[k] for k in ("id", "eff_id"))
          and isinstance(d.get("ro"), bool) and d["ro"] == (d["eff_id"] != d["id"])
          and (d["kind"] == "user" or not d["ro"])
          and all(_int(d.get(k)) for k in ("iat", "exp", "ggen")) and 0 < d["exp"] - d["iat"] <= TTL_S)
    if not ok:
        return None, "actor_invalid"
    t = now if now is not None else time.time()
    if d["iat"] > t + SKEW_S:
        return None, "actor_invalid"
    if t >= d["exp"]:
        return None, "actor_expired"
    return Claims(d["agency"], d["kind"], d["id"], d["eff_id"], d["ro"], d["iat"], d["exp"], d["ggen"]), ""


async def grant_gen(s) -> int | None:
    from sqlalchemy import text
    return (await s.execute(text("SELECT grant_gen FROM agency_copy_version"))).scalar()


def aged_refusal(request):
    if not DATA or request.url.path.startswith(_AGED_OPEN):
        return None
    if COOKIE not in request.cookies and not request.headers.get("authorization"):
        return None
    import agency_copy
    if not agency_copy.aged():
        return None
    return JSONResponse({"detail": {"error": agency_copy.GRANT_AGE_MSG}}, status_code=503,
                        headers={"Cache-Control": "no-store"})


def stream_refusal(claims: Claims | None):
    if not DATA or claims is None:
        return None
    import agency_copy
    gen = agency_copy.held_grant_gen()
    return None if gen is None or gen <= claims.ggen else refused("/events", "actor_stale")


def is_open(path: str) -> bool:
    return path.startswith(_OPEN)


def refused(path: str, reason: str):
    if not DATA or is_open(path):
        return None
    return JSONResponse({"detail": {"error": reason}}, status_code=401, headers={"Cache-Control": "no-store"})


async def resolve(request):
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    if not DATA:
        import chatters
        c = request.cookies.get(chatters.COOKIE_NAME)
        if c and chatters.parse_cookie_issued(c):
            return None
    claims, why = verify(raw)
    if claims is None:
        return refused(request.url.path, why)
    if not DATA and (claims.kind == "user" or request.method not in ("GET", "HEAD", "OPTIONS")):
        return None
    from db.engine import get_session
    if DATA:
        import agency_copy
        gen = agency_copy.held_grant_gen()
    else:
        async with get_session() as s:
            gen = await grant_gen(s)
    if gen is None or claims.ggen < gen:
        return refused(request.url.path, "actor_stale")
    if DATA and claims.kind == "user":
        import auth
        async with get_session() as s:
            if not await auth.apply_actor(s, claims):
                return refused(request.url.path, "actor_revoked")
    request.state.oi_actor = claims
    return None


async def chatter_identity(claims: Claims):
    import chatters
    import chatter_identity_cache as identity_cache
    from session_stamps import session_revoked
    entry = identity_cache.get(claims.id)
    if entry is None:
        gen = identity_cache.generation()
        entry = await chatters.load_identity(claims.id)
        if entry is None:
            return None
        identity_cache.store(claims.id, entry, gen)
    return None if session_revoked(claims.iat * 1000, entry.sessions_valid_after) else entry.identity


def clear(response) -> None:
    response.delete_cookie(COOKIE, samesite="lax")


def set_cookie(response, token: str, exp: int) -> None:
    import auth
    response.set_cookie(COOKIE, token, max_age=max(1, exp - int(time.time())), httponly=True, samesite="lax",
                        secure=auth.cookie_secure(), path="/")


def router() -> APIRouter:
    r = APIRouter()

    @r.post("/auth/actor")
    async def renew(request: Request, response: Response) -> dict:
        """Mint `oi_actor` for the signed-in session (control only). A token alone is no proof: renewal rides the
        long-lived session cookies so logout, sign-out-everywhere and the impersonation TTL apply."""
        import auth
        import chatters
        from db.engine import get_session
        if _private is None:
            raise HTTPException(status_code=503, detail={"error": "actor_key_missing"})
        user, chatter = auth.get_request_user(), chatters.get_request_chatter()
        if getattr(request.state, "oi_actor", None) is not None or auth.get_request_token() is not None or (
                user is None and chatter is None):
            clear(response)
            raise HTTPException(status_code=401, detail={"error": "session_required"})
        async with get_session() as s:
            gen = int(await grant_gen(s) or 0)
        imp = auth.get_impersonation()
        if imp is not None:
            until = auth.impersonation_expires(request)
            token = mint("user", imp.real_user_id, ggen=gen, eff_id=imp.impersonated_user_id, until=until)
        elif user is not None:
            token = mint("user", user.id, ggen=gen)
        else:
            token = mint("chatter", chatter.id, ggen=gen)
        claims, _ = verify(token)
        if claims is None:
            clear(response)
            raise HTTPException(status_code=401, detail={"error": "session_required"})
        set_cookie(response, token, claims.exp)
        return {"exp": claims.exp, "ggen": gen, "ro": claims.ro}

    @r.get("/auth/cells")
    async def cells(response: Response) -> dict:
        import auth
        import chatters
        from db.engine import get_session
        response.headers["Cache-Control"] = "no-store"
        user, chatter = auth.get_request_user(), chatters.get_request_chatter()
        if user is None and chatter is None:
            raise HTTPException(status_code=401, detail={"error": "session_required"})
        try:
            doc = json.loads(Path(os.environ["OI_CELL_MAP"]).read_bytes())
        except (KeyError, OSError, ValueError):
            raise HTTPException(status_code=503, detail={"error": "placement_unreadable"})
        placed = doc.get("accounts") if isinstance(doc.get("accounts"), dict) else {}
        data = sorted(c for c, row in doc.get("cells", {}).items() if isinstance(row, dict) and row.get("role") == "data")
        async with get_session() as s:
            gen = int(await grant_gen(s) or 0)
            if user is not None:
                from accounts import get_platform
                placed_platforms: dict[str, list[str]] = {}
                for key in placed:
                    platform, sep, aid = key.partition(":")
                    if sep and aid in user.account_ids:
                        placed_platforms.setdefault(aid, []).append(platform)
                granted = [(platforms[0] if len(platforms) == 1 else get_platform(aid), aid)
                           for aid, platforms in sorted(placed_platforms.items())]
                restricted = False
                actor = f"user:{user.id}"
            else:
                granted = [(a.platform, a.account_id) for a in await chatters._flat_accounts_for(chatter)]
                restricted = bool(await chatters._account_restrictions_for(s, chatter.id))
                actor = f"chatter:{chatter.id}"
        rows = [{"platform": p, "account_id": a, "cell": placed[f"{p}:{a}"]} for p, a in granted if f"{p}:{a}" in placed]
        ask = sorted({row["cell"] for row in rows}) if restricted else data
        pgen = doc.get("generation")
        control = next((c for c, row in sorted(doc.get("cells", {}).items())
                        if isinstance(row, dict) and row.get("role") == "control"), None)
        return {"actor": actor, "grant_gen": gen, "placement_gen": pgen if _int(pgen) else None,
                "accounts": rows, "cells": ask, "control": control}

    return r


def new_key(out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    path = out / "actor_ed25519.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    os.chmod(path, 0o600)
    pub = _raw_public(key.public_key())
    (out / "actor_ed25519.pub").write_text(pub + "\n")
    return pub


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Actor token key pair: rotation = new pair, then restart every Cell.")
    ap.add_argument("--new-key", metavar="DIR", required=True,
                    help="write actor_ed25519.pem (Control cell only) and actor_ed25519.pub (OI_CELL_ACTOR_PUBKEY)")
    print(new_key(Path(ap.parse_args().new_key)))
    sys.exit(0)
