# of-live-proof

The OF Manager's Live proof harness: Request captures and Live proofs of a Mirror control against OnlyFans, every live
write held to the plan's hard limits, undone and logged. Read this page instead of
`docs/spec/ofm-not-yet/phase-00-live-capture-proof-harness.md`; where the code and the spec differ, the code wins and
the difference is noted here (`spec:`). A Mirror check (`scripts/of-mirror-check/`) is mocked by definition; this
harness is the one path that may reach OnlyFans.

## Safety model

One policy, two enforcement points, one backstop beneath them.

| layer | where | what it does |
|---|---|---|
| policy | `proof_core.decide(request, run)` | pure; answers `read`, `allow`, `reversal` or `refused` with a class and reason (table below) |
| enforcement 1: Relay egress | `relay_live.py` `_guard_egress` | wraps `curl_cffi` `Session.request` and `urllib.request.urlopen` in the real Relay; logs the intent before forwarding; a refusal raises `of_client.OFDeniedError` (Relay answers 403, never retried) |
| enforcement 2: capture browser | `of_browser.py` route on every request | asks the Relay's `POST /__proof/decide` (same `decide`, same wire log, Undo log and Run state); a refused request is aborted |
| backstop | `service/of_client.py` `_denied` (~line 348) | the Relay's own refusal of logout, account deletion, `/log`, `bug*.onlyfans.com` and non-GET `/sessions`, before egress; `decide` mirrors it in class 3 so the browser (no Relay behind it) is held to it too; nothing lifts it |

Around them: the app browser (Playwright Chromium, no DNS but loopback) aborts and records every non-loopback
request (`app-offhost.jsonl`, any entry fails the run); `next dev` runs under `scripts/demo-shots/fetch-guard.cjs`
with dead proxies; the Relay keeps `scripts/demo-shots/net_guard.py` and `_run_ui_safe` (every background loop off,
`CHATTERLY_TEST_MODE=1`, temp DB, secrets/sessions/proxies redirected into the run's temp dir). Nothing in `service/`
changes: every hook lives in this directory. The run fails if `service/`, `app/` or `soak/` change during it.

Arming is the primary safety: only the armed proof's declared method, path template and, where pinned, body pass.
The Critical, Critical GET, stream and lockout lists are backstops no arming lifts; each starts small and grows from
Request captures.

### `decide` classes (first match wins)

| # | class | rule |
|---|---|---|
| 1 | `host` | host is not `onlyfans.com` / a subdomain (fake mode: FakeOF's origin counts as it) and not named in `Run.hosts` (the armed proof's `hosts`, ticket 53); never a wildcard; a named host takes no read and only the armed `Write` naming it (`Write.host`), which takes no other host (fake mode: also FakeOF's origin) |
| 2 | `read` / `critical_read` | GET, HEAD, OPTIONS pass, except a `_denied` path, or a Critical-topic path the armed proof does not list in `reads` |
| 3 | `critical` | always refused, armed or not: `POST`/`PATCH /payouts/requests`, the `_denied` mirror, the Critical topic patterns (`proof_core._TOPICS`), a `PATCH /users/me` body with `username`/`email`/`phone`/`password` |
| 3b | `capture_abort` | under `capture --abort` every other write is recorded and never sent |
| 4 | `unarmed`, `over_count`, `no_undo` | no proof armed; not this proof's write; a body outside its arm's declared payload (`Write.payload`: this run's exact marker, `Run.marker` from the arm, `marker_problem`; the PPV proof's price and one locked medium, the Co-tag proofs' tag and no media); armed count (`max`, default 1) spent; an undo whose `{id}` or any Write whose `{created}` (ticket 34) the arms it reverses (every arm when `reverses` is None) did not create, or an undo before any write; an armed write of a proof with no undo (unless `irreversible` + `owner_go` names the proof) |
| 5 | `oauth`, `mocked`, `stream`, `lockout` | an oauth proof never writes; a mocked proof never writes live; stream start (tag, or `POST /streams`) needs `owner_go` `stream` and a pinned `body_must`; lockout (tag, or a block-IP/country path or body key) needs `lockout` and a pinned `body_must` |
| 6 | `mass_message` | chat send only to the Proof fan; `messages/queue` only with `userIds` exactly `[Proof fan]` and empty `userLists`; queue edit / `PUT /schedules/{id}/publish` only on an id this proof created; Proof fan unset refuses all of them |
| 7 | `post` | a post write needs `isScheduled` with `scheduledDate` at least 30 min ahead, or the `delete_at_once` tag |
| 7b | `fan_visible` | a publish Fans can see (schedule publish, unscheduled post, queue with no `scheduledDate`, any non-post, non-queue arm of a `fan_visible` proof): one per proof, 2 per run (`FAN_VISIBLE_CAP`; one entry per attempt in `Run.fan_visible_done`, never carried across runs), only inside `Run.quiet_hour`, only with `delete_at_once` and an undo |
| 8 | `reversal` | a declared undo of a write already allowed |
| 9 | `allow` | anything else armed (`not reversible, owner go` when that path applied) |

spec: the spec seeds the lockout list with non-GET `/sessions`; the code refuses it outright in class 3 (D3: Close all
sessions gets a Mocked proof only). Class 7b is not in the spec (owner-proxy Q15, ticket 01/104). The driver never sends
`owner_go`, `lockout` or `quiet_hour` to `/__proof/arm` yet, so today every stream, lockout and fan-visible write is
refused.

## Hard limits

| limit | how it holds |
|---|---|
| Proof Creator 80000112 only | preflight: exactly one Creator in the Relay, the uncached `/__proof/session` (`users_me.__wrapped__`) names it and answers alive, the capture browser's own `GET /api2/v2/users/me` names it |
| loopback stack, temp DB, temp session copy | `Stack` in `prove.py`; temp dir deleted at teardown (SIGINT/SIGTERM ignored during teardown); session never printed, `session_leaks` greps evidence + output |
| Proof fan only | class 6; message/PPV proofs park until `--proof-fan` names the Fan; the run never picks one |
| Scheduled post ≥ 30 min ahead, undo forced 10 min before its time | class 7 + driver timer (`undo_deadline`) |
| delete-at-once deleted within 60 s | timer forces the undo at 50 s (60 s − 5 s pace − 5 s request), whatever step the proof is on |
| live writes ≥ 5 s apart | Relay waits before forwarding (`pace_wait`); `pace_problems` re-checks the wire log after every run |
| Critical never | class 3 in both enforcement points; no flag; a Critical capture runs only with `--abort` (refused before start otherwise) |
| stream start, irreversible | need the owner's named go. Currently refused only (D27): under `--of live` such proofs never start (`not_started`), and no CLI flag passes a go; the owner-go run path is ticket 126 |
| proof order | `order()` (ofm-not-yet ticket 101) runs reads (no armed write), then writes no Fan can see, then Fan-reaching writes (`fan_visible`, `delete_at_once`, `message`, or a schedule publish), then Lockout, whatever order `--proof` gave; inside a group the proof list's order (`proofs.ORDER`, Phase 6's "Proof order") wins, then the given order |
| lockout last | `order()` puts lockout proofs last and refuses a non-lockout proof after one; `--lockout`, session-alive check after each lockout write and its revert, and session-lost stop are ticket 126 |
| every write undone | class 4 refuses a write with no undo; Undo log row opened `pending` before forwarding; a failed undo stops the run (later proofs `<id>: not run`), exit non-zero; where the undo's `max` leaves room (the PPV's 2), a trigger's own reversal counts only while a fresh read no longer shows the item (`still_shown`), else the driver sends its own (a 2xx `{"success": false}` included); elsewhere it counts only answered 2xx |
| lost reply never retried | row stays `pending`, write found by `Proof.find` in the after-write read, then undone; libcurl's own resend is blocked (`FRESH_CONNECT` on writes) |
| one run per Creator | lock `$TMPDIR/ofm-live-proof-<creator>.lock` (pid, evidence), shared by every lane; stale (dead pid) taken over and reported |
| earlier `pending` row blocks | any `pending` row in an earlier same-mode run's `undo-log.jsonl` refuses the run (live: also a `FAILED` or `not reversible` row, `unresolved_rows`); clear by hand by appending `{"row": N, "state": "cleared by hand", ...}`; live runs also list their log in `$TMPDIR/ofm-live-proof-<creator>.undo-index.json` (beside the lock) so other worktrees' unresolved logs block too; resolved logs drop out, a listed log that is gone blocks until its path is removed by hand |
| nice ≥ 10 | `run.sh` and `main` renice; every child checked (`niceness_low` fails the run) |

## Modes and flags

```sh
scripts/of-live-proof/run.sh --of fake [--proof <id,...>] [--fault ...] [--proof-fan <id>|none]
scripts/of-live-proof/run.sh --of fake capture [--abort] --proof <id>
scripts/of-live-proof/run.sh --of live --session-dir <dir> [--proof-fan <id>] [capture [--abort]] --proof <id>
scripts/of-live-proof/run.sh --of fake|live [--session-dir <dir>] serve
```

| subcommand / flag | meaning |
|---|---|
| `prove` (default) | start the stack, run each selected proof on the running app (Single-Creator scope `model:<creator>`, 1440x900), one evidence folder |
| `capture [--abort]` | one proof's `capture_steps` in the capture browser (no app); writes `capture-<id>.raw.json` + scrubbed `.record.json` into the evidence folder. `--abort`: the write is recorded and aborted before it leaves |
| `serve` | start the stack, print app/Relay URLs and the throwaway owner's login, wait for Ctrl-C/SIGTERM |
| `--of fake` | soak's FakeOF on loopback behind `fake_layer.py` (hit recorder, faults, tagged reads); session bootstrapped from FakeOF's signed curl; census after the run |
| `--of live` | Relay at onlyfans.com with a temp copy of `--session-dir` (required, no default; must hold `latest.json`) |
| `--proof` | comma-separated ids (default `tracer.create-list`); unknown id exits 2; a `PENDING` id parks |
| `--proof-fan <id>\|none` | fake default is FakeOF's fan; `none` unsets (message proofs park); live never defaults |
| `--cotag-partner <id>\|none` | ticket 98's Co-tag partner; fake default is FakeOF's taggable creator; `none` unsets (both Co-tag proofs park); live never defaults; the guard refuses any other Co-tag. Fake faults: `cotag-extra` (the app's post gains a second creator: the guard refuses it, FakeOF sees no create); `lost-reply` also drops the immediate Co-tagged post's create |
| `--fault` (fake only) | `delete-500` (tracer's list DELETE, or a post's DELETE, answers 500: the undo fails; ofm-not-yet ticket 101), `lost-reply` (a list, vault folder or trial link create applied, connection dropped), `cdn-src` (a vault tile src on a CDN host), `trial-delete-500` (the trial link's DELETE answers 500), `rename-ignored` (a vault folder PATCH answered 200, not applied: `vault.more.rename` must fail), `post-drop-label`, `post-drop-expiry`, `post-drop-target` (a post stored without its labels, expiry or target, answered 200: `p2.post-labels-expiry-target` must fail), `unsend-delete-500` (a message's DELETE answers 500: `p2.bubble-unsend-ppv` must fail, the app's red note shown), `email-off` (the account starts with Email notifications and New Likes Summary off, as live: `settings--email-update-frequency` must park), `wrong-creator` (run expects another Creator; preflight must refuse) |

Exit 0 only when every proof passed (or parked), the census, pacing, off-host, niceness, trees, teardown and
session-leak checks held, and every Undo log row is `undone`. CLI refusals exit 2 before anything starts:
`--session-dir` missing under live, `--abort` outside `capture`, `--fault` under live, a fake-only proof under live,
a Critical capture without `--abort`.

spec: `--owner-go stream|<id>` and `--lockout` are not CLI flags (D27, ticket 126). The fake folder is
`...-ofm-fake-<sha>`, not `-ofm-live-`.

## Proof definitions

Data in `proofs/phase<N>.py` (`PROOFS`), plus fake-only `proofs/fixtures.py`; `proofs/__init__.py` builds `ALL`
(id → Proof) and `PENDING` (ids a Phase lists with no definition yet; parked "Live proof pending").

```python
Proof(id, phase, page, control, kind,          # kind: live | mocked | oauth
      tags=frozenset(),                        # message, post, delete_at_once, stream_start, lockout, irreversible, fan_visible, never-titled
      reads=(),                                # Critical GET path templates this proof may read (class 2)
      branches=(),                             # named verdicts (recorded in the capture record; driver support: ticket 126)
      arm=(Write(method, of_path_template, max=1, body_must=None, relay=None, host=None),),   # empty = read proof
                                               # host: exact non-onlyfans.com host (ticket 53); Proof.hosts = the arms' hosts,
                                               # each a facts.<name>_host of its capture record
      narrowing=None, trigger=(), settled=None,
      of_read=None,                            # of_read(get, fan) -> comparable value; get(path, query) is one signed GET
      effect=None,                             # (before, after_write) -> bool; required when arm is non-empty
      undo=(Write(..., relay="/api/of/v2/...{id}"),),   # Relay route the undo goes through; {id} = created OnlyFans id
      capture_steps=(),
      find=None,                               # (before, after, marker) -> OnlyFans id of a lost-reply write
      fake_only=False, refused_as=None, refused_body=None,   # drills: pass only when refused with that class
      check=None)                              # read proof's own judgement of what the app browser saw
```

| kind / tag | effect |
|---|---|
| `live` | runs in both modes |
| `mocked` | fake mode only; under live never started, recorded `mocked: not run live` (D14) |
| `oauth` | no write; passes when the hand-off navigation is recorded and aborted |
| read proof (`arm` empty) | passes only with zero writes, settled condition met; any write fails it (`read proof sent a write`) |
| `message` (or an armed chat/queue write) | parks without a Proof fan |
| `post`, `delete_at_once` | class 7 and the forced-undo timer |
| `stream_start`, `irreversible` | never started live today (D27); `body_must` required for stream/lockout arms |
| `lockout` | ordered last; refused without `--lockout` (not yet a flag) |
| `fan_visible` | class 7b |
| `never-titled` | `--check-sweep`: the controls never had the Not-yet title (Wired before ofm-not-yet). `control` is their real sweep labels joined by `NEVER_TITLED_SEP` (`"; "`); each must be absent from `ny`, with or without a Live pass, and on the page's Mirror HTML (`app/public/of-mirror/pages/<page>.html`) |
| `fake_only` | `--of live` refuses the run before anything starts (drills, fixtures) |

Trigger steps are one family per proof: UI steps in the Mirror frame (`("click", sel)`, `("fill", sel, text)`,
`("text", sel, want)`, `("wait", s)`, `("goto", page)`, `("images", sel)`, ticket 69: `("select", sel, value)` on a
native `<select>`); `{marker}` = the run's `oi-proof-<run>` in a fill's text and a text wait's `want` (`{handle}` = the
marker as `oi_proof_<run>`, a social username; `{fan}` likewise; a wait whose `{fan}` has no Proof fan fails);
ticket 34: `("goto", "page?query")` may carry a query and `{id}`, the newest OnlyFans id this proof's Undo log rows
recorded; `("frame", page)` takes the Mirror frame a click navigated to and waits for its load (the next steps run there); `("accept", sel, want)` clicks and accepts
the `confirm()` it opens when its text holds `want`; any other dialog is dismissed, and it or no dialog within 5 s fails
the step), `("relay", method, route, body)`
calling a Relay route as the scoped Creator, or capture-browser steps `("fetch", method, path, body, expect)` (fake
only) and `("hand-off", sel)`. `settled` is `("text", sel, want)`, `("text", sel, want, page)` (ticket 61: the
trigger led to that Mirror page and it settles there) or None; its `want` takes `{marker}` too (ticket 64: a text only
this run's write shows).

A text wait's `want` (a step's or `settled`'s) may instead be `Expect(path, query, rows)` (ticket 61): read from
OnlyFans at run time, never a FakeOF name. Just before the before read (so before the page opens) the driver calls
`rows(get(path, query))` through the same Relay `get` as `of_read` (fake and live alike) and waits for the first row's
text (`expects.resolve_expects`; the resolved texts go in the proof's report entry as `wants`). Against a vacuous
pass, judged from OnlyFans alone (never the app's page, where a Mirror bug could already show the target order): each
read needs two rows or more, the first wait's first row must differ from OnlyFans's unsorted first row (the same read
without `field`/`sort`), and each later wait's from the previous wait's; otherwise the proof parks:
`parked — needs ≥2 rows whose order the sort changes: ...`. The read proof's wire check then needs an app GET of each
`path` carrying that `field` and `sort` (`expect_problems`): a Mirror sorting one loaded page client-side fails; and
the app's first GET of it, at page load, carrying neither (else the unsorted baseline is not what the page loaded: a
persisted or default sort fails). `run_proof` adds these beside `wire_problems`. A park after anything beyond the
driver's reads left, or with a closed undo row, fails (`park_problems`).
A proof parked at run time (`expects.Park`,
raised before the trigger, so nothing was sent) is listed in the report's `parked` with its reason, like a proof parked
before the run. A proof's `ready(before)` (ticket 60) parks it the same way, right after the before read and before
the page opens, when OnlyFans's side is not set for the trigger and no captured body can set it (Update frequency:
Email notifications or New Likes Summary off).

Proofs: `proofs/*.py` (list ids with `proof_list.py --ids`; also `--check-records <dir>`, `--check-sweep <sweep>
<dir>`). Shared proofs files are append-only, one `# ticket NN` block per ticket (D29).

Driver per proof: arm → OnlyFans-side read (before) → open page → trigger screenshot → steps → settled → settled
screenshot → wire check (exactly the armed writes, no refusal; a Relay 4xx with no wire line is named as the Relay's
own backstop) → after-write read, `effect` must hold → undo (in `finally`; forced by the timer when due) → after-undo
read must equal before → disarm → close the row.

## Shapes

**Wire log** `wire.jsonl`: one intent line before forwarding, one `done` line after (last per `seq` wins):
`{seq, time, origin: relay|of-browser, method, host, path, query, body, status, verdict, class, reason, proof, phase}`.
No header or cookie is ever logged. Ticket 53: every secret query param (`X-Amz-*`, signature, policy, token, credential, ...) keeps its name with the value `REDACTED` (`proof_core.redact_query`; also in `capture-browser.jsonl`, `fake-hits.jsonl`, `app-offhost.jsonl`), and a binary upload's body is logged as `<N bytes>` (`log_body`).

**Undo log** `undo-log.jsonl` (whole-row snapshots, last per `row` wins; Relay opens, driver closes) and
`undo-log.md` (one table, paste into the PR body unedited):
`{row, proof, state: pending|undone|FAILED|"not reversible, owner go", note, opened, closed, write: {method, path, narrowed},
of_id, wire_seq, write_status, found_by, effect, reversal: {method, path, status, relay, relay_status},
reads: {before, after_write, after_undo, equal}, fan_visible, forced, evidence: [...]}`.
Not written yet: the `session lost` state (ticket 126) and `"not reversible, owner go"`.

**Capture record** `docs/of-manager/captures/<section>--<control-slug>.json` (spec Contracts; placeholders and rules
in `docs/of-manager/captures/README.md`): `{id, section, label, pages, phase, source: live|aborted|of-js, of_rev,
captured, of_js: {bundle, symbol}, request: {method, path, query, content_type, body}, response: {status, keys},
proof: {kind, verdict: pass|fail|parked, evidence, undo, reason, branches}}`. Check before committing:

```sh
./venv/bin/python -I scripts/of-live-proof/capture_record.py check-records docs/of-manager/captures
```

## Evidence folder

`slop/evidence/<UTC>-ofm-<live|fake>-<sha>/` (gitignored): `report.json` + `report.md`, `wire.jsonl`,
`undo-log.jsonl` + `undo-log.md`, `of-read-<proof>-<before|after-write|after-undo>.json`, per-proof screenshot dir,
`fake-hits.jsonl` (fake), `app-offhost.jsonl`, `capture-browser.jsonl`, `capture-<id>.raw.json` / `.record.json`
(capture), `relay.log`, `next.log`. The run prints the folder first and last. In a PR quote that exact folder,
never `latest`, and paste `undo-log.md`.

## Current live limits

- Live reader (ticket 11): `Stack.of_get` is one GET to the run's own Relay (`/__proof/of-read`), signed there with
  the session copy in the run's temp dir, decided by the Live guard and logged in `wire.jsonl` with origin `driver`
  (headers never logged; a non-GET driver request is refused). Fake mode takes the same path, plus FakeOF's
  `x-oi-proof-read` tag (never sent live); the census fails a tagged FakeOF hit with no `driver` wire line. A proof
  that writes or reads OnlyFans now starts live.
- Still refused live, with `refused: capture-browser steps run only on the fake-mode drill page; live capture steps
  (clicks on onlyfans.com) are not written yet`: `capture` (send or `--abort`) of a proof that writes or reads, and a
  proof with a `fetch` / `hand-off` trigger step. Unchanged: mocked, stream start, irreversible, fake-only, Proof fan
  unset, no trigger.
- Capture browser opens on demand only: for `capture` or a proof with capture-browser steps (D27). Its sign-in seeds
  cookies plus localStorage `bcTokenSha`; a cookie-only copy killed the stored session (D26). A `fetch` step is
  fake-only; live capture steps (clicks on onlyfans.com) are not written yet.
- ASSUMPTION (egress): live Relay calls leave direct with no proxy (the operator's IP); ADR-0030 (IP change ≠ session
  loss) is unobserved; ticket 11 decides the live egress.
- ASSUMPTION (`route.fetch`): OnlyFans accepts capture-browser requests forwarded by Playwright's `route.fetch` under
  a Chromium UA; the attended live run measures it before any capture step; a dead session overturns it.
- UI undo through OnlyFans's own page is not built: an undo needs a `Write.relay` route.

## Manual live steps (never in an unattended run)

The spec's `# manual:` Acceptance lines run only attended, by the orchestrator or the owner (ticket 11), never in
`/spec-auto` or any scheduled job. Today the two `capture` lines are refused by the limits above (capture by hand);
the Live proof line runs.

```sh
nice -n 10 scripts/of-live-proof/run.sh --of live --session-dir <owner checkout>/service/sessions/accounts/80000112 capture --proof tracer.create-list
nice -n 10 scripts/of-live-proof/run.sh --of live --session-dir <same> capture --abort --proof tracer.create-list
nice -n 10 scripts/of-live-proof/run.sh --of live --session-dir <same> --proof tracer.create-list
# then: every Undo log row "undone"; paste <evidence>/undo-log.md into the PR; quote slop/evidence/<UTC>-ofm-live-<sha>/
```

Also manual: the owner names the Proof fan (`--proof-fan`) before any message or PPV proof.

For the attended run (ticket 98): only the two Co-tag proofs (`Proof.may_tag`) may send a tagged post. The guard
refuses an upload, dedupe or publish-now post that the Relay's co-performer auto-tag tagged (fail safe). For those
proofs to pass live, use solo media or set the auto-tag off.

## Tests

`./venv/bin/python -m pytest -q scripts/of-live-proof` (policy, scrubber, Undo log, driver rules, live entry,
capture browser, stdlib-name trap). The Phase's whole check is the spec's Acceptance block. Its fake-mode part (the
whole proof list in batches of at most 4, Lockout last with `--lockout`, one solo retry only on a `Page.goto` timeout
or "no Mirror frame", then `--check-records` and `--check-sweep`) is `accept.py --phase <N> [--sweep-port <port>]`
(ticket 77; `SWEEP_SECTIONS` names each Phase's sweep sections, Phase 3 only so far).
