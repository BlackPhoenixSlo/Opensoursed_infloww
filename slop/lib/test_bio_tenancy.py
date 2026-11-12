"""The editor tenancy check must record an owner-filter failure without raising."""
import asyncio
import importlib.util
from pathlib import Path


SCENARIO = Path(__file__).resolve().parents[1] / "scenarios/2026-11-11-bio-pages-editor.py"


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self.body = body

    def json(self):
        return self.body


class Client:
    def __init__(self, role, faulty=False):
        self.role, self.faulty = role, faulty

    async def request(self, method, path, **kw):
        if self.role == "chatter":
            return Response(403)
        if self.role == "other":
            if path == "/admin/bio-pages/b-page":
                return Response(200, {"profile": {"avatar": "a.webp"},
                                      "links": [{"id": "b-link", "background_image": ""}]})
            return Response(200)
        if path == "/admin/bio-pages":
            return Response(200, {"profiles": [{"id": "b-page"}] if self.faulty else []})
        return Response(200 if self.faulty else 404)


def test_owner_filter_fault_reaches_tenancy_check():
    spec = importlib.util.spec_from_file_location("bio_editor_tenancy", SCENARIO)
    scenario = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scenario)
    ids = ("b-page", "b-link", "a-page", "a-link")
    for faulty in (False, True):
        clients = (Client("owner", faulty), Client("other"), Client("chatter"))
        bad = asyncio.run(scenario.tenancy_check(clients, ids, "probe"))
        assert bool(bad) is faulty, bad
