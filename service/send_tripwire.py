from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Callable, TypeVar

from fastapi import HTTPException

T = TypeVar("T")


class Budget:
    """One Send claim's wire budget: one attempt, a second only after a full 4xx or a refusal before any tunnel."""
    __slots__ = ("op_id", "sent", "open", "last")

    def __init__(self, op_id: str):
        self.op_id = op_id
        self.sent = 0
        self.open = True
        self.last = "none"

    def upstream_refused(self) -> bool:
        return self.last in ("4xx", "before_tunnel")

    def leave(self, request: Callable[[], T], before_tunnel: Callable[[BaseException], bool]) -> T:
        if not self.open:
            raise SendBudgetSpent(self.op_id, self.last)
        self.open, self.sent, self.last = False, self.sent + 1, "unknown"
        try:
            r = request()
        except Exception as e:
            if before_tunnel(e):
                self.open, self.last = True, "before_tunnel"
            raise
        status = getattr(r, "status_code", 0)
        self.last = "4xx" if 400 <= status < 500 else f"{status // 100}xx"
        self.open = self.last == "4xx"
        return r


claim: ContextVar[Budget | None] = ContextVar("send_claim", default=None)


class UnclaimedSend(HTTPException):
    def __init__(self, method: str):
        super().__init__(status_code=409, detail={"error": "unclaimed_send", "method": method})


class SendBudgetSpent(Exception):
    def __init__(self, op_id: str, last: str):
        super().__init__(f"send op {op_id}: wire attempt refused, the last one ended {last}")


def check(method: str) -> None:
    if os.environ.get("OI_CELL_MAP") and claim.get() is None:
        raise UnclaimedSend(method)


def budget() -> Budget | None:
    return claim.get()
