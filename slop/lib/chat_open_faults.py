from __future__ import annotations

THREAD_ONCE = ("thread: each read once per open (no route GET twice: attribution, fan-history; a short thread's fill: "
               "each older page once, at most 4)")
THREAD_BUNDLE = "thread: the open's local reads in one /admin/screens/chat, none per route"


def _chat_bundle_drops_attribution() -> None:
    import chat_screen_api
    real = chat_screen_api.run_screen

    async def without(request, response, reads, *a, **kw):
        return await real(request, response, [r for r in reads if r.name != "attribution"], *a, **kw)

    chat_screen_api.run_screen = without


def register(Fault) -> dict:
    return {"chat-bundle-drops-attribution": Fault(_chat_bundle_drops_attribution, (THREAD_ONCE, THREAD_BUNDLE))}
