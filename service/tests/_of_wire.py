from __future__ import annotations


def fake_wire(client, http):
    client.http = http
    client._signed_retired = False
    return client
