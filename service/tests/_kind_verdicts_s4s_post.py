from __future__ import annotations

from _kind_verdict_seeds import _s4s

VERDICTS = {
    "fansly": {"s4s_post": {"run": "same", "media": "gated:platform_lacks:create_post:media"}},
    "onlyfans": {"s4s_post": {"run": "same", "media": "same"}},
}

PAYLOADS = {"s4s_post": {"run": {}, "media": {}}}

SAME_EFFECTS = {
    "fansly": {"s4s_post": {"run": (
        "POST /post", "job:s4s_check", "job:unsend_messages", "table:actions", "table:posts", "table:s4s_schedule")}},
    "onlyfans": {"s4s_post": {
        "run": ("create_post", "job:s4s_check", "job:unsend_messages", "table:actions", "table:posts",
                "table:s4s_schedule"),
        "media": ("create_post", "job:s4s_check", "job:unsend_messages", "table:actions", "table:posts",
                  "table:s4s_media", "table:s4s_schedule", "upload_media")}},
}

SEEDS = {("s4s_post", "run"): _s4s(), ("s4s_post", "media"): _s4s(media=True)}
