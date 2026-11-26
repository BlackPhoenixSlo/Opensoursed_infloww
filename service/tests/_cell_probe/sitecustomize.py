import importlib.util
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
for _d in sys.path:
    _p = os.path.join(_d or ".", "sitecustomize.py")
    if os.path.abspath(_d or ".") != _here and os.path.isfile(_p):
        _spec = importlib.util.spec_from_file_location("_chained_sitecustomize", _p)
        _spec.loader.exec_module(importlib.util.module_from_spec(_spec))
        break

import cell_probe  # noqa: E402

cell_probe.activate_from_env()
