# Capture records

One scrubbed JSON per control, `<section>--<control-slug>.json`, shape in
`docs/spec/ofm-not-yet/phase-00-live-capture-proof-harness.md` (Contracts, Capture record).
Written by `scrub` in `scripts/of-live-proof/capture_record.py`; raw captures stay in the gitignored evidence folder.

Placeholders (the only stand-ins for ids):

| placeholder | replaces |
|---|---|
| `{creator}` | the Proof Creator's id |
| `{fan}` | the Proof fan's id |
| `{id}` | any other number of 5+ digits |
| `oi-proof-{run}` | the run's own `oi-proof-<run>` marker values |

Check before committing (exit 0 = clean):

```sh
./venv/bin/python -I scripts/of-live-proof/capture_record.py check-records docs/of-manager/captures
```

It fails on any 5+ digit run outside the placeholders, any email, any cookie or auth header name, any header but
the content type, any response row, an `of-js` record without bundle and symbol, and a branch verdict that is not
`pass` or `parked: <reason>`. Provenance exempt from the digit rule only in its fixed format: `of_rev`
(`<12 digits>-<10 hex>`), `proof.evidence` (`slop/evidence/<UTC>-ofm-live|fake-<sha>`), and the bundle `file`,
`offset`, `symbol` and JS `evidence` excerpt in `of_js` (`bundle_build` as `of_rev`). The older gatherer shape under
`.scratch/ofm-not-yet/captures/` also exempts the same fields in `requests[i].source` and `room_source.sources[i]`.
