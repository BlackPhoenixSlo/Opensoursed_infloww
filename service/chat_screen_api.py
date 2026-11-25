from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Query, Request, Response

import fans
import messages
from auth import assert_account_owned
import relay_host
import saved_replies_api
import sensitive_words_api
import vault_sends_api
import vault_stills
from screens_api import DEADLINE_MAX_MS, DEADLINE_MS, Read, deadline_at, run_screen

router = APIRouter()

# OF reads (page, pinned, users/me) stay out: OF-bound, they would hold the DB-first paint hostage.
SEED_PAGE = 30
ATTRIBUTION_LIMIT = 200
THUMBS = 6
LACKS = ("savedReplies", "sensitiveWords")


def thumbs(seed: Any, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    out: list[str] = []
    for m in (seed or {}).get("messages") or []:
        for med in m.get("media") or []:
            u = med.get("thumb_url") if med.get("type") == "photo" else None
            if u and not vault_stills.signed_url_expired(u, now) and u not in out:
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
    assert_account_owned(account)
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
