"""A fake OF transport on a (bare) OFClient, for tests. No side effects at import.

`fake_wire(client, http)` makes every signed and raw call use `http` (an object
with the curl Session methods the test needs: get / request / put ...). The real
`OFClient._signed_slot` still runs, so the retired guard (OFSessionRetired after
close_signed_sessions) holds as in production; only the curl session is the fake.
"""
from __future__ import annotations


def fake_wire(client, http):
    client.http = http
    client._signed_retired = False
    return client
