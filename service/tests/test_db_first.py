#!/usr/bin/env python3
"""DB-first policy (user rule): the info-gathering automations must read OUR DB,
NOT make redundant OF calls for data we already have (fan name / id / facts).

gen_info is the GATHERER — the WS pump + scrape_chats already filled fans/messages,
so it must never import of_client (the fan name/id/facts all come from our DB).
apply_profiles is the APPLIER and scrape_chats is the BACKFILLER — both legitimately
hit OF (push / pull), so they are intentionally NOT checked here.

Enforced statically: assert gen_info does not import of_client (a docstring mention
is fine; an actual import is not).

Run: ./venv/bin/python service/tests/test_db_first.py   (exit 0 = green)
"""
import _harness  # MUST be first — sets sys.path / binds a throwaway temp DB

_harness.bootstrap()

import importlib  # noqa: E402
import inspect  # noqa: E402
import re  # noqa: E402

_IMPORT_RE = re.compile(r'^\s*(?:from\s+of_client\b|import\s+of_client\b)', re.M)


def case_gather_automations_are_db_first():
    for modname in ("automations.gen_info",):
        m = importlib.import_module(modname)
        src = inspect.getsource(m)
        assert not _IMPORT_RE.search(src), (
            f"{modname} imports of_client — it must be DB-first (no extra OF call "
            f"for info already in our DB: fan name/id/facts)")
        # No of_client handle leaked onto the module object either.
        assert not hasattr(m, "of_client"), f"{modname} carries an of_client reference"


_harness.run(case_gather_automations_are_db_first)
