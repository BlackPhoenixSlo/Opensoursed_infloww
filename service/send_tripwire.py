from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Callable, TypeVar

from fastapi import HTTPException

T = TypeVar("T")


class Budget:
    """One Send claim's wire budget: one attempt, a second only after a full 4xx or a refusal before any tunnel."""
    __slots__ = ("op_id", "sent", "open", "last", "_check_permit")

    def __init__(self, op_id: str, check_permit: Callable[[], None]):
        self.op_id = op_id
        self._check_permit = check_permit
        self.sent = 0
        self.open = True
        self.last = "none"

    def upstream_refused(self) -> bool:
        return self.last in ("4xx", "before_tunnel")

    def leave(self, request: Callable[[], T], before_tunnel: Callable[[BaseException], bool] | None) -> T:
        if not self.open:
            raise SendBudgetSpent(self.op_id, self.last)
        self._check_permit()
        self.open, self.sent, self.last = False, self.sent + 1, "unknown"
        try:
            r = request()
        except Exception as e:
            if before_tunnel is not None and before_tunnel(e):
                self.open, self.last = True, "before_tunnel"
            raise
        status = getattr(r, "status_code", 0)
        self.last = "4xx" if 400 <= status < 500 else f"{status // 100}xx"
        self.open = self.last == "4xx"
        return r


claim: ContextVar[Budget | None] = ContextVar("send_claim", default=None)
preparation: ContextVar[Budget | None] = ContextVar("send_preparation", default=None)


class UnclaimedSend(HTTPException):
    def __init__(self, method: str):
        super().__init__(status_code=409, detail={"error": "unclaimed_send", "method": method})


class CellHeld(Exception):
    def __init__(self, hold):
        super().__init__(f"Cell held ({hold.why})")
        self.hold = hold


class SendBudgetSpent(Exception):
    def __init__(self, op_id: str, last: str):
        super().__init__(f"send op {op_id}: wire attempt refused, the last one ended {last}")


def check(method: str) -> None:
    if os.environ.get("OI_CELL_MAP") and claim.get() is None:
        raise UnclaimedSend(method)


def budget() -> Budget | None:
    return claim.get()


def leave(request: Callable[[], T], *, delivery: bool = False,
          before_tunnel: Callable[[BaseException], bool] | None = None) -> T:
    active = budget()
    if delivery and active is not None:
        return active.leave(request, before_tunnel)
    if not os.environ.get("OI_CELL_MAP"):
        return request()
    from cell_hold import wire_write, writing
    if active is None and preparation.get() is None:
        return wire_write(request)
    with writing():
        return request()
