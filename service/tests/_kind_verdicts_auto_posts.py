from __future__ import annotations

VERDICTS = {
    "fansly": {"auto_posts": {"run": "same", "media": "gated:platform_lacks:create_post:media"}},
    "onlyfans": {"auto_posts": {"run": "same", "media": "same"}},
}

PAYLOADS = {"auto_posts": {"run": {"posts": [{"text": "new post", "hours_to_live": 24}]},
                           "media": {"posts": [{"text": "new post", "media_files": [901], "hours_to_live": 24}]}}}

SAME_EFFECTS = {
    "fansly": {"auto_posts": {"run": ("POST /post", "job:unsend_messages", "table:posts")}},
    "onlyfans": {"auto_posts": dict.fromkeys(("run", "media"), ("create_post", "job:unsend_messages", "table:posts"))},
}

SEEDS: dict = {}
