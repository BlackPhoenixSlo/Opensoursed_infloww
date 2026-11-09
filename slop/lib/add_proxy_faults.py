"""Add new proxy on a phone (app/components/setup/AddProxyModal.tsx, opened from ProxiesTable on /creators/proxy):
the check and its break-it-once fault. lib/faults.py merges `register(Fault)` into FAULTS. Client side: actors/ui.py
rewrites the JS `next dev` serves, never the repo files. The check is scenarios/2026-10-29-state-reducers.py's
(section "proxy-phone", `_proxy_phone`), which imports the name, so the target can never name a check that does not
exist.

  add-proxy-row-overflows   slop/run 2026-10-29-state-reducers --break --fault=add-proxy-row-overflows
                            --set only=proxy-phone --baseline=<a green only=proxy-phone run>
"""
from __future__ import annotations

PROXY_ADD_PHONE = ("add proxy, 390x844 phone: the dialog fits (no sideways page scroll, the dialog on screen, every "
                   "field's box inside it, Cancel and Add proxy on screen); Cancel closes it with no POST "
                   "/admin/proxies and GET /admin/proxies unchanged")


def register(Fault) -> dict:
    return {
        # The IP address / Port row gets a fixed 640 px min-width (a desktop-only layout leaking onto a phone): the
        # dialog body scrolls sideways, so the page and the dialog box still fit, but the host and port boxes run
        # past the dialog's right edge. Only PROXY_ADD_PHONE goes red. The class string is that row's alone.
        "add-proxy-row-overflows": Fault(None, (PROXY_ADD_PHONE,), browser=(
            # `next dev` serves the module inside an eval string, its quotes escaped (\"): the group keeps them.
            (r'(className:\s*(\\?)"flex flex-col sm:flex-row sm:gap-6\2")', r"\1, style: { minWidth: 640 }"),
        )),
    }
