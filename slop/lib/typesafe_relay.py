HANDLERS: list = []
FALLBACK: list = []


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
