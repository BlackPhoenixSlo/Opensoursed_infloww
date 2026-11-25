from __future__ import annotations

PROXY_ADD_PHONE = ("add proxy, 390x844 phone: the dialog fits (no sideways page scroll, the dialog on screen, every "
                   "field's box inside it, Cancel and Add proxy on screen); Cancel closes it with no POST "
                   "/admin/proxies and GET /admin/proxies unchanged")


def register(Fault) -> dict:
    return {
        "add-proxy-row-overflows": Fault(None, (PROXY_ADD_PHONE,), browser=(
            # `next dev` serves the module inside an eval string, its quotes escaped (\"): the group keeps them.
            (r'(className:\s*(\\?)"flex flex-col sm:flex-row sm:gap-6\2")', r"\1, style: { minWidth: 640 }"),
        )),
    }
