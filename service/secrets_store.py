from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from threading import Lock

log = logging.getLogger("of-relay.secrets")

# Inside a bind-mounted DIRECTORY, not a file mount (Docker materialises a missing file mount as a directory); a store lost on deploy would delete ADMIN_PASSWORD and reopen the bootstrap window.
_DIR = Path(__file__).resolve().parent / "secrets"
_PATH = _DIR / "secrets.json"
_LEGACY_PATH = Path(__file__).resolve().parent / "secrets.json"
_LOCK = Lock()

KNOWN: dict[str, dict] = {
    "DEEPSEEK_API_KEY": {
        "label": "DeepSeek API key",
        "group": "AI models",
        "help": "Required for AI auto-messaging. Get one at platform.deepseek.com.",
    },
    "ZAI_API_KEY": {
        "label": "Z.ai (GLM) API key",
        "group": "AI models",
        "help": "Optional provider for chat replies (z.ai). Only needed if an "
                "account's Brain is set to a GLM model.",
    },
    "ANTHROPIC_API_KEY": {
        "label": "Anthropic (Claude) API key",
        "group": "AI models",
        "help": "Optional. Help assistant answers (Claude Opus); any account "
                "an operator points at a Claude model. console.anthropic.com.",
    },
    "TYPESAFE_API_KEY": {
        "label": "TypeSafe API key (Jev)",
        "group": "AI models",
        "help": "Optional. Jev's key for every agency with no TypeSafe key of its "
                "own, paid by this deployment: the FM auto-reply's off-script "
                "check, Full AI's Router and the vault AI's Jev pass run on it. "
                "Blank = those agencies get no Jev: the off-script check is "
                "skipped (the script is sent as before), Full AI cannot go Live, "
                "the vault's Jev pass is skipped. Get one at console.typesafe.ai.",
    },
    "HELP_ASSISTANT_DEEPSEEK_KEY": {
        "label": "Help-bot fallback key (DeepSeek)",
        "group": "AI models",
        "help": "Paid by this deployment, used ONLY by the in-product help "
                "chatbot and ONLY for an agency that has pasted no DeepSeek key "
                "of its own. It is what lets a brand-new agency ask the product "
                "where to paste its keys. Blank = the help bot fails closed for "
                "keyless agencies, as it did before.",
    },
    "HELP_ASSISTANT_ANTHROPIC_KEY": {
        "label": "Help-bot fallback key (Anthropic)",
        "group": "AI models",
        "help": "Paid by this deployment, used ONLY by the in-product help "
                "chatbot for an agency with no Anthropic key of its own. Set = "
                "the help bot answers with Claude Opus by default instead of "
                "DeepSeek. Blank = DeepSeek, as before.",
    },
    "GOOGLE_DRIVE_API_KEY": {
        "label": "Google Drive API key",
        "group": "Vault import",
        "secret": True,
        "help": ("Lets the vault importer pull publicly-shared Drive links. A plain "
                 "API key, not an OAuth token. Create one at console.cloud.google.com "
                 "→ APIs & Services → Credentials with the Drive API enabled, and "
                 "restrict it to the Drive API."),
    },
    "ADMIN_PASSWORD": {
        "label": "Founder password",
        "group": "Access",
        "help": "Second factor on founder-only writes: granting or revoking a "
                "model, transferring one, deleting a user, and setting another "
                "agency's AI keys. BOOTSTRAP ONLY — set it here once; changing "
                "it is done in the relay's environment (ADMIN_PASSWORD in "
                "the compose-level .env, then restart), which outranks this value.",
    },
    "SHARE_TOKEN": {
        "label": "Access password (share link token)",
        "group": "Access",
        "help": "Set to require ?t=<token> on the public URL. Blank = the "
                "friend-auth login is the only gate. Takes effect immediately.",
    },
}


MASK_CHAR = "•"


def mask(val: str) -> str:
    if not val:
        return ""
    return MASK_CHAR * 4 if len(val) <= 8 else MASK_CHAR * 4 + val[-4:]


_CACHE: tuple[tuple[int, int, int, int], dict] | None = None


def _stamp() -> tuple[int, int, int, int] | None:
    try:
        st = _PATH.stat()
    except FileNotFoundError:
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _adopt_legacy_file() -> None:
    try:
        if _PATH.exists() or not _LEGACY_PATH.is_file():
            return
        _DIR.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(_LEGACY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            os.chmod(_PATH, 0o600)
        except OSError:
            pass
        log.info("secrets_store: adopted legacy %s into %s", _LEGACY_PATH, _PATH)
    except Exception:
        log.exception("secrets_store: could not adopt the legacy secrets file")


def _load() -> dict:
    # stat() by path still answers when out of descriptors; on an unreadable file keep the last answer, since {} would silently swap the access gate's token to the env default.
    global _CACHE
    stamp = _stamp()
    if stamp is None:
        _CACHE = None
        return {}
    cached = _CACHE
    if cached is not None and cached[0] == stamp:
        return dict(cached[1])
    try:
        with open(_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        _CACHE = None
        return {}
    except OSError:
        # Last good parse beats "no secrets set", which would silently swap the access gate's token.
        log.warning("secrets.json could not be opened — serving last known good",
                    exc_info=True)
        return dict(cached[1]) if cached is not None else {}
    except Exception:  # pragma: no cover — a corrupt file must not crash callers
        log.warning("secrets.json unreadable — ignoring", exc_info=True)
        _CACHE = (stamp, {})
        return {}
    if not isinstance(data, dict):
        _CACHE = (stamp, {})
        return {}
    _CACHE = (stamp, data)
    return dict(data)


def stored(name: str) -> str:
    v = _load().get(name)
    return v.strip() if isinstance(v, str) else ""


def get(name: str) -> str:
    return stored(name) or (os.environ.get(name) or "").strip()


# ADMIN_PASSWORD may be created but never changed from a session: a stolen cookie would collapse the two factors into one. Rotation is the VPS .env, read first by auth.
_BOOTSTRAP_ONLY = ("ADMIN_PASSWORD",)


def _assert_bootstrap_only(values: dict[str, str | None]) -> None:
    for k in _BOOTSTRAP_ONLY:
        if k not in values:
            continue
        raw = values[k]
        blank = not str(raw or "").strip()
        superseded = (os.environ.get(k) or "").strip()
        if superseded and blank:
            continue
        if get(k):
            raise ValueError(
                f"{k} is already configured and cannot be changed from here — "
                "set ADMIN_PASSWORD in the relay's environment (the compose-level .env) "
                "and restart; it outranks this value, and you can then clear "
                "this one"
            )


def set_many(values: dict[str, str | None]) -> None:
    # A value made of this store's own mask is refused, not stored: it would replace a working secret with bullets.
    for k, v in values.items():
        if k not in KNOWN or v is None:
            continue
        if not isinstance(v, str):
            raise ValueError(f"{k}: expected a string value, got {type(v).__name__}")
        if MASK_CHAR in v:
            raise ValueError(
                f"{k}: that looks like the masked placeholder, not a value — "
                "leave the field blank to keep what is stored"
            )
    _assert_bootstrap_only(values)
    with _LOCK:
        data = _load()
        for k, v in values.items():
            if k not in KNOWN:
                continue
            if v is None or not str(v).strip():
                data.pop(k, None)
            else:
                data[k] = str(v).strip()
        _atomic_write(data)


def _atomic_write(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(_PATH.parent), prefix=".secrets.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, _PATH)
        try:
            os.chmod(_PATH, 0o600)
        except OSError:  # pragma: no cover — best-effort on odd filesystems
            pass
        global _CACHE
        stamp = _stamp()
        _CACHE = (stamp, dict(data)) if stamp is not None else None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _hint(name: str, val: str, meta: dict) -> str:
    if name in _BOOTSTRAP_ONLY:
        return "••••••••" if val else ""
    if not val:
        return ""
    if meta.get("secret", True) is False:
        return val if len(val) <= 80 else val[:77] + "…"
    if meta.get("multiline"):
        return f"{MASK_CHAR * 4} ({len(val)} chars)"
    return mask(val)


def status() -> dict:
    data = _load()
    out: dict[str, dict] = {}
    for name, meta in KNOWN.items():
        sval = data.get(name)
        sval = sval.strip() if isinstance(sval, str) else ""
        env = (os.environ.get(name) or "").strip()
        if name in _BOOTSTRAP_ONLY:
            source = "env" if env else ("store" if sval else "unset")
            live = env or sval
        else:
            source = "store" if sval else ("env" if env else "unset")
            live = sval or env
        out[name] = {
            "label": meta["label"],
            "group": meta["group"],
            "secret": meta.get("secret", True),
            "multiline": bool(meta.get("multiline")),
            "help": meta.get("help", ""),
            "set": bool(live),
            "clearable": bool(sval) and (
                name not in _BOOTSTRAP_ONLY
                or bool((os.environ.get(name) or "").strip())
            ),
            "source": source,
            "hint": _hint(name, live, meta),
        }
    return out


_adopt_legacy_file()
