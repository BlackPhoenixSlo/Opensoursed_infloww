"""
Capture a Fansly session from a browser HAR — the analogue of OF's paste-curl.

A human logs in normally (password + the one-time email 2FA), browses far
enough that the client fires authenticated XHRs, and exports a HAR. This script
lifts the reusable auth material out of it and, in the same pass, proves the
signer against every `fansly-client-check` the browser actually sent.

    ../venv/bin/python bootstrap_from_har.py fanslycalls.har

Writes sessions/session.json (gitignored). Nothing here touches the network
except the optional --chunk fetch of main.<hash>.js.
"""
from __future__ import annotations

import argparse
import base64
import time as _time
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import fansly_signer as signer

HERE = Path(__file__).resolve().parent
SESSIONS_DIR = HERE / "sessions"
SESSION_FILE = SESSIONS_DIR / "session.json"

API_HOST = "apiv3.fansly.com"

SANITIZED_HAR_HELP = """\
This HAR carries no `authorization` header, so it was exported sanitized —
Chromium's "Export HAR (sanitized)" strips Authorization and Cookie. Everything
else (device id, session id, user agent, and the digests this verified against)
came through fine; only the token is missing.

Two ways to supply it:

  1. Re-export with "Export HAR (with sensitive data)" and re-run this.
  2. Read it off the tab and pass --token. On an authenticated fansly.com tab:

       JSON.parse(localStorage.session_active_session).token

The same blob also holds `id` (the fansly-session-id header) and `accountId`.\
"""


def _headers(entry: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in entry["request"].get("headers", [])}


def _body(entry: dict) -> str:
    content = entry["response"].get("content", {})
    text = content.get("text") or ""
    if content.get("encoding") == "base64":
        try:
            text = base64.b64decode(text).decode("utf-8", "replace")
        except Exception:
            return ""
    return text


def scan(har_path: Path) -> tuple[dict, list[dict]]:
    """Return (session material, check-digest samples) found in the HAR."""
    har = json.loads(har_path.read_text())

    session: dict = {}
    samples: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for entry in har["log"]["entries"]:
        request = entry["request"]
        parts = urlsplit(request["url"])
        if parts.netloc != API_HOST or request["method"] == "OPTIONS":
            continue

        headers = _headers(entry)
        check = headers.get("fansly-client-check")
        device_id = headers.get("fansly-client-id")

        if check and device_id:
            key = (parts.path, check)
            if key not in seen:
                seen.add(key)
                samples.append(
                    {"path": parts.path, "device_id": device_id, "check": check}
                )

        # Last writer wins — later entries are the freshest.
        for src, dst in (
            ("authorization", "token"),
            ("user-agent", "user_agent"),
            ("fansly-client-id", "device_id"),
            ("fansly-session-id", "id"),
            ("accept-language", "accept_language"),
            ("sec-ch-ua", "sec_ch_ua"),
            ("sec-ch-ua-platform", "sec_ch_ua_platform"),
            ("sec-ch-ua-mobile", "sec_ch_ua_mobile"),
        ):
            if headers.get(src):
                session[dst] = headers[src]

        # Our own account id falls out of any send/follow response.
        if "accountId" not in session:
            try:
                payload = json.loads(_body(entry)).get("response") or {}
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                owner = payload.get("senderId") or payload.get("followerId")
                if owner:
                    session["accountId"] = owner

    return session, samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("har", type=Path, help="path to the exported .har")
    parser.add_argument(
        "--chunk",
        type=Path,
        help="optional main.<hash>.js to re-derive the check key from",
    )
    parser.add_argument(
        "--token",
        help="authorization token, if your HAR was exported sanitized",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="verify and report, but do not write sessions/session.json",
    )
    args = parser.parse_args()

    session, samples = scan(args.har)

    if not samples:
        print("no signed Fansly API calls in this HAR — capture one that loads "
              "Messages or the feed", file=sys.stderr)
        return 1

    print(f"{len(samples)} distinct signed paths captured")

    check_key = signer.CHECK_KEY
    if args.chunk:
        derived = signer.derive_check_key(args.chunk.read_text(errors="replace"), samples)
        if derived is None:
            print("could not derive a check key from that chunk that reproduces "
                  "the captured digests — the scheme moved", file=sys.stderr)
            return 1
        if derived != signer.CHECK_KEY:
            print(f"check key rotated: {signer.CHECK_KEY!r} -> {derived!r} "
                  f"(update CHECK_KEY in fansly_signer.py)")
        check_key = derived

    matched, mismatches = signer.verify_samples(samples, check_key)
    print(f"signer: {matched}/{len(samples)} digests reproduced")

    for bad in mismatches:
        print(f"  MISMATCH {bad['path']}: got {bad['computed']} want {bad['check']}",
              file=sys.stderr)

    if mismatches:
        print("refusing to write a session against an unverified signer", file=sys.stderr)
        return 1

    if args.token:
        session["token"] = args.token

    if "token" not in session:
        print(SANITIZED_HAR_HELP, file=sys.stderr)
        return 1

    missing = [k for k in ("user_agent", "device_id") if k not in session]
    if missing:
        print(f"HAR is missing {', '.join(missing)}", file=sys.stderr)
        return 1

    session["check_key"] = check_key
    # Trust the captured device id for its TTL so a real run reuses the
    # exact id these digests were signed with, instead of re-fetching.
    session["device_id_ts"] = int(_time.time())
    print("captured:", ", ".join(
        f"{k}={'…' if k == 'token' else session[k]}" for k in sorted(session)
    ))

    if args.print_only:
        return 0

    SESSIONS_DIR.mkdir(exist_ok=True)
    SESSION_FILE.write_text(json.dumps(session, indent=2) + "\n")
    SESSION_FILE.chmod(0o600)
    print(f"wrote {SESSION_FILE.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
