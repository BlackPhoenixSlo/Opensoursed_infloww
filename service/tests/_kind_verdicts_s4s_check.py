from __future__ import annotations

from _kind_verdict_seeds import _s4s
from stateful_fake import _Response

VERDICTS = {
    "fansly": {"s4s_check": {"text_baseline": "noop:inconclusive", "empty_baseline": "noop:inconclusive"}},
    "onlyfans": {"s4s_check": {"text_baseline": "same", "empty_baseline": "same"}},
}

PAYLOADS = {"s4s_check": {"text_baseline": {}, "empty_baseline": {}}}

SAME_EFFECTS = {"onlyfans": {"s4s_check": dict.fromkeys(("text_baseline", "empty_baseline"),
                                                        ("table:actions", "table:s4s_schedule"))}}

EMPTY_POST = {"success": True, "response": {"posts": []}}
IDLESS_POST = {"success": True, "response": {"posts": [{"content": "go follow #advertisement"}]}}
POST_ERROR = {"success": False, "error": {"code": 500, "details": "upstream"}}


def answers_post(payload: dict, status: int = 200):
    def shape(fake) -> None:
        dispatch = fake._dispatch

        def answer(method, url, path, params, query, body):
            if (method, path) == ("GET", "/post"):
                response = _Response(payload)
                response.status_code = status
                return response
            return dispatch(method, url, path, params, query, body)
        fake._dispatch = answer
    return shape


SEEDS = {("s4s_check", "text_baseline"): _s4s({"id": 5501, "text": "go follow\n#advertisement"}),
         ("s4s_check", "empty_baseline"): _s4s({})}

FAKE_STATE = {("s4s_check", b): answers_post(EMPTY_POST) for b in ("text_baseline", "empty_baseline")}
