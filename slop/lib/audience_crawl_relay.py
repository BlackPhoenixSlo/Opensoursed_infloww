"""The mass-audience-crawl flow's part of the slop relay (lib/relay.py loads it: `wire` runs at the end of its
`_wire`), for scenarios/2026-11-08-mass-audience-crawl.py. Inert until called.

  POST /__slop/audience-crawl/pacing {PAGE_GAP_S, JITTER_S}  sets service/of_pacing.py's background pacer gap
       and jitter (time compression, declared bypass: one background GET per gap per Creator, the pacer and
       its callers are the product's) -> both values now.
The crawl's own Knobs (AUDIENCE_CRAWL_*) are env, read at call time: the scenario's RELAY_ENV compresses them.
"""

FIELDS = ("PAGE_GAP_S", "JITTER_S")


def wire(app, loopback, _relay) -> None:
    from fastapi import HTTPException, Request

    async def pacing(request: Request) -> dict:
        loopback(request)
        import of_pacing
        body = await request.json()
        for k, v in body.items():
            if k not in FIELDS:
                raise HTTPException(400, f"not a pacing field: {k}")
            setattr(of_pacing, k, float(v))
        return {k: getattr(of_pacing, k) for k in FIELDS}

    app.add_api_route("/__slop/audience-crawl/pacing", pacing, methods=["POST"])
