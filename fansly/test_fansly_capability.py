"""Capability contract: every client.<method> an automation touches must exist.

WHY THIS IS A STATIC TEST. The shim does NOT subclass OFClient — it
reimplements ~40 methods and lacks the other ~140 — so a plugin calling a
method the shim is missing does not fall through to a base class. It
AttributeErrors mid-run, and because plugins run inside a task runner the
failure is usually swallowed: the automation just silently stops working.
Finding that by running automations is the backstop, not the guard.

THE SCAN MATCHES ATTRIBUTE ACCESS, NOT CALL SYNTAX, and that distinction is the
whole point. About half the call sites look like
    await asyncio.to_thread(client.pin_message, id, fan)
with no paren after the name. A `client\\.(\\w+)\\(` regex sees 12 of the 33
names actually referenced and would have declared this file green while
`delete_story` was still missing. Do not "tidy" the pattern into a call regex.

TWO SURFACES, NOT ONE. Automations reach the shim as `client.<method>`, but
the HTTP routes in service/server.py reach it as `_get_client().<method>` —
a far larger surface (~145 methods). Scanning only automations is how
subscribers_chart shipped as a live AttributeError 500 on the Statistics
screen: this file printed "every referenced method resolves" while 89
route-called methods did not. Both surfaces are scanned now.

Route misses are reported but NOT fatal yet: the OF route table is far ahead
of the Fansly port, so failing on all of them would just make this guard
permanently red and therefore ignored. The automation surface stays a hard
gate; routes are a visible, shrinking budget.

Residual known escape: string-dynamic getattr(client, name) — one site in
unsend_messages.py, already None-tolerant. A runtime sweep stays the backstop.
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from fansly_shim import FanslyShimClient  # noqa: E402

ATTR = re.compile(r"\bclient\.([a-z_0-9]+)\b")
# Routes call through the accessor, not a bare `client` name.
ROUTE_ATTR = re.compile(r"_get_client\(\)\.([a-z_0-9]+)\b")


def referenced_methods() -> dict[str, list[str]]:
    """name -> the files that reference it. Automations surface (hard gate)."""
    found: dict[str, list[str]] = {}
    for path in sorted((ROOT / "service" / "automations").rglob("*.py")):
        for match in ATTR.finditer(path.read_text()):
            found.setdefault(match.group(1), []).append(path.name)
    return found


def route_methods() -> set[str]:
    """Every client method the HTTP route table calls. Reported, not fatal."""
    server = ROOT / "service" / "server.py"
    return set(ROUTE_ATTR.findall(server.read_text())) if server.exists() else set()


def unresolved(names) -> list[str]:
    return sorted(n for n in names if getattr(FanslyShimClient, n, None) is None)


def main() -> int:
    referenced = referenced_methods()
    assert referenced, "scanned no automations — is the path still right?"

    missing: list[str] = []
    noop: list[str] = []
    blocked: list[str] = []
    for name in sorted(referenced):
        attr = getattr(FanslyShimClient, name, None)
        if attr is None:
            missing.append(name)
        elif getattr(attr, "fansly_unsupported", None):
            noop.append(name)
        elif getattr(attr, "fansly_blocked", None):
            blocked.append(name)

    real = len(referenced) - len(missing) - len(noop) - len(blocked)
    print(f"scanned {len(referenced)} distinct client.<method> references")
    print(f"  implemented : {real}")
    print(f"  no-op       : {len(noop)}  {noop}")
    print(f"  blocked     : {len(blocked)}  {blocked}")
    print(f"  MISSING     : {len(missing)}  {missing}")

    # A blocked method is unfinished work, not a resting state. Print the
    # reason every run so it stays visible instead of quietly becoming
    # permanent the way an undocumented stub does.
    for name in blocked:
        why = getattr(FanslyShimClient, name).fansly_blocked
        print(f"      TODO {name}: {why}")

    if missing:
        print()
        print("FAIL: these will AttributeError mid-automation:")
        for name in missing:
            where = sorted(set(referenced[name]))
            print(f"  - {name}  (called by {', '.join(where)})")
        print()
        print("Implement it, or mark it @fansly_unsupported with a reason.")
        return 1

    # Second surface: the HTTP routes. A miss here is a 500 on whichever
    # screen calls it, not a silent automation stall — same bug, louder.
    routes = route_methods()
    missing_routes = unresolved(routes)
    print()
    print(f"routes: {len(routes)} client methods called by service/server.py")
    print(f"  resolve : {len(routes) - len(missing_routes)}")
    print(f"  MISSING : {len(missing_routes)}  -> AttributeError 500 if hit")
    if missing_routes:
        print("  (not fatal: the OF route table leads the Fansly port. Shrink "
              "this by implementing or marking @fansly_unsupported.)")
        for name in missing_routes:
            print(f"      - {name}")

    print("\nOK: every referenced method resolves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
