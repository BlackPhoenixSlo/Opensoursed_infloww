#!/usr/bin/env python3
import _harness

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
        assert not hasattr(m, "of_client"), f"{modname} carries an of_client reference"


_harness.run(case_gather_automations_are_db_first)
