from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from db.models import Fan

from . import _voice
from ._common import guard_offplatform, strip_emojis
from ._markers import strip_asides, strip_narration
from ._persona import verify_self_consistency

log = logging.getLogger("of-relay.automation.outbound")


@dataclass(frozen=True)
class ConsistencyCtx:
    fan: Fan
    persona: str
    model: str
    last_inbound: str = ""


async def finalize_draft(
    text: str,
    *,
    account_id: str,
    fan_id: int,
    purpose: str,
    consistency: ConsistencyCtx | None = None,
    strip_emoji: bool = False,
    v: "_voice.VoiceBlocks" = _voice.HER,
) -> tuple[str, list[str]]:
    # Order is load-bearing: guard before any rewrite so word-restriction cannot hide a leak; re-guard a rewrite (model output); strip emojis last.
    text, leak = _guard(text, account_id=account_id, fan_id=fan_id, purpose=purpose,
                        v=v)
    if consistency is not None:
        fixed = await verify_self_consistency(
            account_id, fan_id, consistency.fan, text, consistency.persona,
            consistency.model, purpose, last_inbound=consistency.last_inbound)
        if fixed != text:
            fixed, refix = _guard(fixed, account_id=account_id, fan_id=fan_id,
                                  purpose=f"{purpose}/consistency-fix",
                                  v=v)
            # Merged so a caller acting on leak (dropping a paid attach) hears of a leak from either pass.
            leak = list(dict.fromkeys([*leak, *refix]))
        text = fixed
    if strip_emoji:
        text = strip_emojis(text)
    return text, leak


def _guard(text: str, *, account_id: str, fan_id: int, purpose: str,
           v: "_voice.VoiceBlocks" = _voice.HER) -> tuple[str, list[str]]:
    text = strip_asides(strip_narration(text))
    text, leak = guard_offplatform(text, random.Random(f"{fan_id}:{text}"), v)
    if leak:
        log.info("%s off-platform leak guarded account=%s fan=%s reasons=%s",
                 purpose, account_id, fan_id, leak)
    return text, leak
