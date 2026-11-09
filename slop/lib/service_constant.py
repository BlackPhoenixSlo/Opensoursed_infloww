"""Read relay constants from source without importing service modules into the harness."""
from pathlib import Path
import re


def service_number(module: str, name: str, *, as_float: bool = False) -> int | float:
    src = (Path(__file__).resolve().parents[2] / "service" / f"{module}.py").read_text()
    value = re.search(rf"^{re.escape(name)}\s*=\s*(\d+(?:\.\d+)?)\b", src, re.M)
    if value is None:
        raise ValueError(f"{module}.{name} is not a literal numeric constant")
    return float(value.group(1)) if as_float else int(value.group(1))
