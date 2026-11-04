# slop/: Media upload on OnlyFans' wire

Media upload through the REAL `OFClient` (`service/of_upload.py`): hash dedupe, signed S3 (single PUT, or multipart
past 5 MiB), the convert claim, and the vault id minted once something references the claim (a fan send, an
import's carrier post). The harness, its knobs and its rules are in `README.md`; this file is only what this flow
adds. The scenario's docstring is its spec (phases, the closed #171 loop finding with its runs, bypasses).

## Layout

| Path | Role |
|---|---|
| `lib/of_wire_upload.py` | OnlyFans' media upload at its wire, part of `lib/of_wire.py`'s fake (`FakeOF.upload`, an `UploadWire`; `of_wire.py`'s route table lists the routes). A claim is minted into the vault only once a send's or a post's `mediaFiles` references it, one vault id per S3 object (ETag + size); a carrier post lists its media in a seeded shuffled order. Kept per Creator in arrival order (`snapshot()`). |
| `lib/upload_relay.py` | Its relay part (no `OF` class), only under `OF_API_ORIGIN`: wraps `curl_cffi.requests.Session.request` so the product's hard-coded `convert.onlyfans.com` claim goes to `$OF_API_ORIGIN/convert/<path>` (the fake's `POST /convert/file/upload`); everything else untouched, outside relay.py's curl_cffi guard. |
| `lib/upload_faults.py` | The check names, `BUDGET` (the two route budgets' names) and its faults (below), each patching a function in `service/of_upload.py` inside the relay. No fault proves `CLAIM_ETAG` (declared). |
| `scenarios/2026-11-02-of-upload-wire.py` | The scenario; files made harness-side, deterministic from `--seed`. |

## Scenarios

- `2026-11-02-of-upload-wire`: `agency_inbox`, each Creator with a captured session (`seed/of_sessions`,
  `OF_WIRE`). `--files=` Composer files over the Creators, `--big_files=` of them 2-3 parts (> 5 MiB), the rest
  20-200 KB; per Creator `--import_files=` fresh import files and `--import_dupes=` of its landed single-part
  Composer files (SCALES `of_upload_<knob>`). `--users` at once: A the Composer upload (`POST
  /api/of/v2/upload`); B that claim sent to a fan (`POST /api/of/v2/chats/{fan}/messages`, `media_files`); C per
  Creator a vault import (`.../vault/upload/batch` + `/batch/append`, `GET .../upload/status` until finished); D
  every Composer and fresh import file uploaded again. Checks (`lib/upload_faults.py`): `UPLOAD_SHAPE`,
  `ONE_CLAIM`, `S3_BYTES`, `DEDUPE_KEY`, `CLAIM_ETAG`, `CLAIM_TARGET`, `REUPLOAD_ONE`, `REUPLOAD_MULTI`, `SEND`,
  `IMPORT`, `OFFHOST`, `AUDIT_ROWS` (one `actions` row per 2xx upload and send, one outbound `messages` row per
  accepted send); budgets: p95 of A and B, both vs the last green run. Faults: `upload-dedupe-uses-md5` (default;
  `s3_etag_and_md5` answers the plain md5; targets `REUPLOAD_MULTI`, `DEDUPE_KEY`), `upload-convert-claimed-twice`
  (`ONE_CLAIM`), `upload-on-loop` (the Composer's `upload_media` back on the event loop, the #171 shape; both
  budgets and `AUDIT_ROWS`, at `--scale=medium --users=200`; nothing to catch at small / 20). No UI.
