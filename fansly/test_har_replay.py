"""
Replay the captured HAR through fansly_client and assert we rebuild each
request byte-for-byte where it matters.

This is the "only once samples pass do we trust it" gate from BRIEF.md, applied
to the whole request and not just the signature: for every write the browser
made, the client must produce the same method, path, query, Fansly headers and
JSON body. Nothing here touches the network.

    ../venv/bin/python test_har_replay.py [path/to/fanslycalls.har]
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import fansly_client as fc
import fansly_signer as signer

HERE = Path(__file__).resolve().parent
DEFAULT_HAR = HERE / "fanslycalls.har"

# Fields whose value is a fresh clock reading on every send; we assert on their
# presence and type, not their value.
VOLATILE_BODY_FIELDS = {"createdAt"}


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class RecordingHTTP:
    """Stands in for requests.Session — records, never sends."""

    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.calls: list[dict] = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "params": params or {},
             "json": json, "headers": headers or {}}
        )
        return FakeResponse(self.payload, self.status)


def load_writes(har_path: Path) -> list[dict]:
    """Every signed POST the browser made to the Fansly API, in order."""
    har = json.loads(har_path.read_text())
    writes = []

    for entry in har["log"]["entries"]:
        request = entry["request"]
        parts = urlsplit(request["url"])
        if parts.netloc != "apiv3.fansly.com" or request["method"] != "POST":
            continue

        headers = {h["name"].lower(): h["value"] for h in request.get("headers", [])}
        if "fansly-client-check" not in headers:
            continue

        content = entry["response"].get("content", {})
        text = content.get("text") or ""
        if content.get("encoding") == "base64":
            try:
                text = base64.b64decode(text).decode("utf-8", "replace")
            except Exception:
                text = ""
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {"success": True, "response": None}

        body = None
        if request.get("postData", {}).get("text"):
            try:
                body = json.loads(request["postData"]["text"])
            except ValueError:
                body = None

        writes.append(
            {"path": parts.path, "query": parse_qs(parts.query),
             "headers": headers, "body": body, "payload": payload,
             "status": entry["response"]["status"]}
        )

    return writes


def session_from(writes: list[dict]) -> fc.FanslySession:
    """Rebuild the browser's session state from the capture.

    The HAR was exported sanitized, so there is no authorization header in it;
    the token is irrelevant to what this test proves, so a placeholder stands in.
    """
    headers = writes[0]["headers"]
    account_id = ""
    for write in writes:
        response = (write["payload"] or {}).get("response") or {}
        if isinstance(response, dict):
            account_id = account_id or response.get("senderId") or response.get("followerId") or ""

    return fc.FanslySession(
        {
            "token": "har-replay-placeholder",
            "id": headers["fansly-session-id"],
            "accountId": account_id,
            "device_id": headers["fansly-client-id"],
            "device_id_ts": 9e12,          # never refresh during a replay
            "user_agent": headers["user-agent"],
            "accept_language": headers.get("accept-language", ""),
            "check_key": signer.CHECK_KEY,
        }
    )


def replay(client: fc.FanslyClient, write: dict):
    """Drive the client the way the app would for this captured request."""
    path, body = write["path"], write["body"]

    if path == "/api/v1/message/typing":
        return client.typing(body["groupId"])

    if path == "/api/v1/message":
        return client.send_message(body["groupId"], body["content"])

    if path == "/api/v1/group":
        other = next(
            user["userId"] for user in body["users"]
            if user["userId"] != client.session.account_id
        )
        return client.create_group(other)

    if path.endswith("/followers"):
        return client.follow(path.split("/")[-2])

    if path.endswith("/followers/remove"):
        return client.unfollow(path.split("/")[-3])

    return None


def check(condition: bool, label: str, failures: list[str]) -> None:
    if not condition:
        failures.append(label)


def main(argv: list[str]) -> int:
    har_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_HAR
    if not har_path.exists():
        print(f"no HAR at {har_path}", file=sys.stderr)
        return 1

    writes = load_writes(har_path)
    if not writes:
        print("no signed POSTs in that HAR", file=sys.stderr)
        return 1

    session = session_from(writes)
    failures: list[str] = []
    replayed = 0

    for write in writes:
        http = RecordingHTTP(write["payload"], write["status"])
        client = fc.FanslyClient(session)
        client.http = http
        # Pin the clock so the comparison is deterministic.
        client.clock = type(
            "PinnedClock", (), {"value": lambda _self: int(write["headers"]["fansly-client-ts"])}
        )()

        try:
            replay(client, write)
        except fc.FanslyAPIError:
            # One captured follow came back 422 "you can not follow". The
            # request was still built, and building it correctly is the point.
            pass

        if not http.calls:
            continue

        replayed += 1
        call = http.calls[-1]
        label = f"{write['path']}"

        check(call["method"] == "POST", f"{label}: method", failures)
        check(
            urlsplit(call["url"]).path == write["path"],
            f"{label}: path (got {urlsplit(call['url']).path})",
            failures,
        )
        check(call["params"].get("ngsw-bypass") == "true", f"{label}: ngsw-bypass", failures)

        for header in ("fansly-client-check", "fansly-client-id",
                       "fansly-client-ts", "fansly-session-id"):
            check(
                call["headers"].get(header) == write["headers"][header],
                f"{label}: {header} (got {call['headers'].get(header)!r}, "
                f"want {write['headers'][header]!r})",
                failures,
            )

        sent, captured = call["json"], write["body"]
        if captured is None:
            check(sent is None, f"{label}: expected no body, sent {sent!r}", failures)
        else:
            check(
                sorted(sent or {}) == sorted(captured),
                f"{label}: body keys {sorted(sent or {})} != {sorted(captured)}",
                failures,
            )
            for key, value in captured.items():
                if key in VOLATILE_BODY_FIELDS:
                    check(
                        isinstance((sent or {}).get(key), type(value)),
                        f"{label}: {key} type",
                        failures,
                    )
                    continue
                check(
                    (sent or {}).get(key) == value,
                    f"{label}: {key} = {(sent or {}).get(key)!r} != {value!r}",
                    failures,
                )

    samples = [
        {"path": w["path"], "device_id": w["headers"]["fansly-client-id"],
         "check": w["headers"]["fansly-client-check"]}
        for w in writes
    ]
    matched, mismatches = signer.verify_samples(samples, signer.CHECK_KEY)
    check(not mismatches, f"signer: {matched}/{len(samples)} digests", failures)

    print(f"replayed {replayed} captured writes")
    print(f"signer:   {matched}/{len(samples)} digests reproduced")

    for failure in failures:
        print(f"  FAIL {failure}", file=sys.stderr)

    if failures:
        print(f"{len(failures)} check(s) failed", file=sys.stderr)
        return 1

    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
