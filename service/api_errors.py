from __future__ import annotations

from fastapi import HTTPException


# OF answers "Access denied." on /trials (401) and /promotions (403) when the subscription is FREE.
def raise_if_free_page_denied(exc: Exception, feature: str) -> None:
    if "Access denied" in repr(exc):
        raise HTTPException(
            409,
            f"OnlyFans refused: {feature} need a PAID subscription price. "
            "Set a price on the OnlyFans profile (Settings → Subscription), then retry.")
