"""TypeSafe's System One wire, faked at its HTTP boundary (lib/relay.py loads it; no `OF` class).

  POST /__slop/fake/typesafe/v1/systemone   the product's real `typesafe_sdk` client posts here
       (TYPESAFE_BASE_URL, lib/stack.py). Loopback only; no Bearer key is a 401.

Each flow that calls TypeSafe answers its own requests: it registers an `async (request) -> response | None`
handler in `wire` (None = not mine). `HANDLERS` (claim by body, e.g. lib/vault_jev_relay.py) are tried first, in
order, then `FALLBACK` (one flow's catch-all, if any); a call nobody answers is a 500. With SLOP_LIVE=1
lib/stack.py does not point the SDK here.
"""

HANDLERS: list = []
FALLBACK: list = []  # at most one catch-all handler


def wire(app, loopback, _relay) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    async def fake_typesafe(request: Request):
        loopback(request)
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return JSONResponse({"detail": "no key"}, status_code=401)
        for handle in HANDLERS + FALLBACK:
            got = await handle(request)
            if got is not None:
                return got
        return JSONResponse({"detail": "slop fake TypeSafe: no handler claimed the call"}, status_code=500)

    app.add_api_route("/__slop/fake/typesafe/v1/systemone", fake_typesafe, methods=["POST"])
