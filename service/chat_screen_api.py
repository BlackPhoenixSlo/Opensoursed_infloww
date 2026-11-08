"""service/chat_screen_api.py — a thread open's local reads in one relay call (screens_api's pattern).

A phone 250 ms from the host opened a thread with 22 requests in three waves (slop slow-connections jp): the DB
seed, the Fan record, attribution (three times), fan-history (twice), saved replies, sensitive words, scheduled
sends, each its own round trip. This route answers the local (relay DB) ones at once:

  GET /admin/screens/chat?account=&fan=&lacks=savedReplies,sensitiveWords&deadline_ms=
      {answers: [{accountId, read, body} | {accountId, read, status, detail}], thumbs, asOf}   (screens_api's envelope)

`read` names the field; every body is the exact one its own route answers, from that route's function with every argument explicit:
`seed` = GET /admin/messages/{account}/{fan}?limit=30 (useChatMessagesLocal), `fan` = GET /admin/fans/{account}/{fan},
`attribution` = GET /admin/messages/{account}/{fan}/attribution (bare: the last 200 outbound rows; the client derives
its `since_id` read from it when it holds fewer than 200), `fanHistory` = GET /admin/vault/fan-history,
`scheduledSends` = GET /api/of/v2/scheduled-sends?fan_id= (X-Account-Id), `savedReplies` / `sensitiveWords` = their
lists, read only when `lacks` names them (the client's copy is missing or stale). `thumbs`: the seed page's media
thumbnail URLs, newest first, at most THUMBS, a signature already expired left out, so the client starts those /img
loads with this answer instead of after OnlyFans' page.

OnlyFans reads (the thread's page, pinned, users/me) are NOT here: each is OF-bound (prod ~1 s), and bundled they
would hold the DB-first paint hostage; the client sends them alongside, as before.

Authorization: the caller must own `account` (403 before any read), then screens_api's per read (`_serve`: a real
inner Request per route, the role hook and the ownership resolver before it, the route's own checks); every read is the
open thread's, so all keep the caller's priority (`focus=account`). An answer's accountId: the X-Account-Id the
browser's read would send, null for the /admin routes; past the deadline
`bundle_deadline` (the client then reads that route itself; no follow-up bundle).
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Query, Request, Response

import fans
import messages
from auth import assert_account_owned
import relay_host
import saved_replies_api
import sensitive_words_api
import vault_sends_api
from screens_api import DEADLINE_MAX_MS, DEADLINE_MS, Read, deadline_at, run_screen

router = APIRouter()

SEED_PAGE = 30     # useChatMessagesLocal's default limit
ATTRIBUTION_LIMIT = 200   # the attribution route's default (and max) limit
THUMBS = 6         # the newest media tiles a phone's first screen shows (the client's first-screen image preload)
LACKS = ("savedReplies", "sensitiveWords")


def _expired(url: str, now: float) -> bool:
    """A CloudFront-signed URL past its expiry (canned `Expires=`, or a custom Policy's DateLessThan
    AWS:EpochTime). Anything unparseable counts as fresh: /img decides."""
    q = parse_qs(urlsplit(url).query)
    try:
        if "Expires" in q:
            return float(q["Expires"][0]) < now
        if "Policy" in q:
            raw = q["Policy"][0].replace("-", "+").replace("_", "=").replace("~", "/")
            pol = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
            exp = pol["Statement"][0]["Condition"]["DateLessThan"]["AWS:EpochTime"]
            return float(exp) < now
    except Exception:  # noqa: BLE001
        return False
    return False


def thumbs(seed: Any, now: float | None = None) -> list[str]:
    """The seed page's photo thumbnails (the URL MessageMedia paints: a video's tile is its still), newest message
    first, at most THUMBS, none expired."""
    now = time.time() if now is None else now
    out: list[str] = []
    for m in (seed or {}).get("messages") or []:
        for med in m.get("media") or []:
            u = med.get("thumb_url") if med.get("type") == "photo" else None
            if u and not _expired(u, now) and u not in out:
                out.append(u)
            if len(out) >= THUMBS:
                return out
    return out


async def _saved_replies(account: str) -> Any:
    resp = await saved_replies_api.admin_saved_replies_list(account_id=account)
    return json.loads(resp.body)


@router.get("/admin/screens/chat")
async def chat_screen(
    request: Request,
    response: Response,
    account: str = Query(..., max_length=40),
    fan: int = Query(...),
    lacks: str | None = Query(None, max_length=200),
    deadline_ms: int = Query(DEADLINE_MS, ge=0, le=DEADLINE_MAX_MS),
) -> dict[str, Any]:
    """A thread open's local reads in one call (module docstring)."""
    until = deadline_at(deadline_ms)
    assert_account_owned(account)  # 403 before any read: every read here is this Creator's
    srv = relay_host.live_server()
    want = {x for x in (lacks or "").split(",") if x in LACKS}
    base = f"/admin/messages/{account}/{fan}"
    reads = [
        Read("seed", None, base, {"limit": SEED_PAGE},
              lambda: messages.list_messages(account, fan, limit=SEED_PAGE, before_id=None)),
        Read("fan", None, f"/admin/fans/{account}/{fan}", {}, lambda: fans.get_fan(account, fan)),
        Read("attribution", None, f"{base}/attribution", {},
              lambda: messages.list_message_attribution(account, fan, since_id=None, limit=ATTRIBUTION_LIMIT)),
        Read("fanHistory", None, "/admin/vault/fan-history", {"account_id": account, "fan_id": fan},
              lambda: vault_sends_api.admin_vault_fan_history(account_id=account, fan_id=fan)),
        Read("scheduledSends", account, "/api/of/v2/scheduled-sends", {"fan_id": fan},
              lambda: srv.list_scheduled_sends(srv._request_ctx.get(), fan_id=fan)),
    ]
    if "savedReplies" in want:
        reads.append(Read("savedReplies", None, "/admin/saved-replies", {"account_id": account},
                           lambda: _saved_replies(account)))
    if "sensitiveWords" in want:
        reads.append(Read("sensitiveWords", None, "/admin/sensitive-words", {"account_id": account},
                           lambda: sensitive_words_api.list_words(account_id=account)))
    # Every read is the open thread's Creator: none demoted to background.
    env = await run_screen(request, response, reads, until, focus=account)
    seed = next((a.get("body") for a in env["answers"] if a["read"] == "seed"), None)
    return {**env, "thumbs": thumbs(seed)}
