"""A fake OF transport on a (bare) OFClient, for tests. No side effects at import.

`fake_wire(client, http)` makes every signed call lease `http` (an object with
the curl Session methods the test needs: get / request / put ...) and every raw
call use it too. The real `OFClient._signed_session` still runs, so the retired
guard (OFSessionRetired after close_signed_sessions) holds as in production;
only the leased curl handle is the fake.
"""
from __future__ import annotations

import contextlib
import threading


class _FakeLeases:
    def __init__(self, http) -> None:
        self._http = http

    @contextlib.contextmanager
    def lease(self):
        yield self._http

    def close(self) -> None:
        pass


def fake_wire(client, http):
    client.http = http
    client._signed_pool_lock = threading.Lock()
    client._signed_retired = False
    client._signed_pool = _FakeLeases(http)
    return client
