# ui-explore

Property-based UI exploration with [Bombadil](https://github.com/antithesishq/bombadil) 0.8.0 (pinned in `package.json`): random clicks, inputs, scrolls and navigation across the signed-in app, checking `specification.ts` after every step.

```sh
scripts/ui-explore/run.sh [--time-limit=2m] [--viewport=desktop|phone] [--exit-on-violation]
scripts/ui-explore/run.sh --shrink=<trace.bin> [--time-limit=10m]   # smaller trace, same violation
scripts/ui-explore/run.sh --reproduce=<trace.bin> [--viewport=...]  # replay (same viewport)
```

Exit 0 = clean; non-zero = violations or a Bombadil failure (stall, CDP/navigation timeout under heavy load; the summary says which).

## Stack
- `scripts/demo-shots/run.sh serve`: temp-DB relay + `next dev`, loopback-only guards. Needs `venv/`, `cwebp`, `magick`.
- `seed_session.py`: registers the owner and seeds the demo agency, then prints the session cookie.
- `shim.py`: the browser origin in front of next. It answers OnlyFans reads from the demo-shots fixtures (the relay would 503 them), serves vault stills, and drops next's `serverComponentChanges` HMR message. It also retries chunks that next truncates while recompiling.
- `warm.py`: loads the app once so next has compiled it.
- Chrome resolves only loopback names (`--host-resolver-rules`). Every process runs at `nice -n 10`.
- Teardown signals only the process groups `run.sh` started.

## Properties (`specification.ts`)
- No uncaught exceptions or unhandled rejections.
- No document response ≥ 400.
- No `console.error` (allowlist).
- No 5xx on any request.
- Stays on loopback (allowlist).
- No Next error overlay or crash screen.
- No visible `NaN`, `$NaN`, `undefined` or `[object Object]`.
- No horizontal overflow at width ≤ 390.

Sign-out controls and Next dev tools are never clicked. The login page triggers a re-auth, and `about:blank` triggers a return to the app.

## Output: `.scratch/ui-explore/<run-id>/`
- `summary.json`: for each violated property, the state count and the first state's URL, action and detail.
- `violations/<state>.jpeg`: screenshot of that first state. It can lag the DOM by one frame; the detail text is authoritative.
- `trace.bin` / `trace.txt`: the full trace. Browse it with `node_modules/.bin/bombadil browser inspect <trace.bin>`.
- `stack.log`, `shim.log`, `relay.log`, `next.log`, `shim-unmatched.txt`: logs. The last one lists OF reads that had no fixture and got `{}`.

## Allowlists
One regex per entry, each with the reason it is not a product bug. Never allowlist a real bug: report it instead. Fix harness artifacts in the harness.

## Limits
- Bombadil has no RNG seed (`--seed` is refused).
- Replays can diverge on timing. Shrink first: shrunk traces replay reliably.
- Runs on `next dev` only.
- One run per checkout at a time, because of the shared `.next/demo-shots`.
