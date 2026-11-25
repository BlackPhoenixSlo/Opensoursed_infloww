from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import fansly_client as fc
import fansly_shim as fs
import fansly_signer as signer

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "writes.json"

VOLATILE_BODY_FIELDS = {"createdAt"}


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class RecordingHTTP:

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


def load_fixture_writes(path: Path) -> list[dict]:
    doc = json.loads(path.read_text())
    return [
        {**w, "query": {},
         "headers": {**doc["headers"], "fansly-client-check": w["check"]},
         "status": 200}
        for w in doc["writes"]
    ]


def session_from(writes: list[dict]) -> fc.FanslySession:
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
            "device_id_ts": 9e12,
            "user_agent": headers["user-agent"],
            "accept_language": headers.get("accept-language", ""),
            "check_key": signer.CHECK_KEY,
        }
    )


def replay(client: fc.FanslyClient, write: dict):
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

    if path == "/api/v1/lists/commands":
        commands = body["listCommands"]
        if all(c["type"] == 1 for c in commands):
            by_list: dict[str, list[int]] = {}
            for c in commands:
                by_list.setdefault(c["listItem"]["listId"], []).append(int(c["listItem"]["id"]))
            return client.add_users_to_lists(by_list)
        if len(commands) == 1 and commands[0]["type"] == 2 and len(commands[0]["itemIds"]) == 1:
            return client.remove_user_from_list(commands[0]["listId"], commands[0]["itemIds"][0])

    return None


def check(condition: bool, label: str, failures: list[str]) -> None:
    if not condition:
        failures.append(label)


def main(argv: list[str]) -> int:
    from_fixture = len(argv) < 2
    source = FIXTURE if from_fixture else Path(argv[1])
    if not source.exists():
        print(f"nothing at {source}", file=sys.stderr)
        return 1

    writes = load_fixture_writes(source) if from_fixture else load_writes(source)
    if not writes:
        print(f"no signed POSTs in {source}", file=sys.stderr)
        return 1

    session = session_from(writes)
    failures: list[str] = []
    replayed = 0

    for write in writes:
        http = RecordingHTTP(write["payload"], write["status"])
        lists = write["path"] == "/api/v1/lists/commands"
        client = (fs.FanslyShimClient if lists else fc.FanslyClient)(session)
        client.http = http
        client.clock = type(
            "PinnedClock", (), {"value": lambda _self: int(write["headers"]["fansly-client-ts"])}
        )()

        raised = False
        result = None
        try:
            result = replay(client, write)
        except fc.FanslyAPIError:
            raised = True

        label = f"{write['path']}"
        if not http.calls:
            check(not from_fixture, f"{label}: fixture write not rebuilt", failures)
            continue

        replayed += 1
        check(len(http.calls) == 1, f"{label}: expected 1 request, got {len(http.calls)}", failures)
        expected_error = not write["payload"].get("success") or write["status"] >= 400
        check(raised == expected_error,
              f"{label}: expected {'API error' if expected_error else 'success'}", failures)
        if "expected_result" in write:
            check(not raised and result == write["expected_result"],
                  f"{label}: expected result {write['expected_result']!r}, got {result!r}", failures)
        call = http.calls[0]

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

    check(replayed > 0, "no write was rebuilt", failures)

    samples = [
        {"path": w["path"], "device_id": w["headers"]["fansly-client-id"],
         "check": w["headers"]["fansly-client-check"]}
        for w in writes
    ]
    matched, mismatches = signer.verify_samples(samples, signer.CHECK_KEY)
    check(not mismatches, f"signer: {matched}/{len(samples)} digests", failures)

    print(f"replayed {replayed}/{len(writes)} writes from {source.name}")
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
