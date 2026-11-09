"""Shared browser and proxy setup for the vault scenarios."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
import sys

from slop.lib.proxy_wire import ProxyWire


async def _proxy(owner, label: str) -> dict | None:
    r = await owner.get("/admin/proxies")
    if r.status_code != 200:
        return None
    return next((p for p in r.json().get("proxies", []) if p.get("label") == label), None)


async def _await_bound(owner, label: str, account_id: str | None, bound: bool,
                       timeout_s: float = 10.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        p = await _proxy(owner, label)
        if account_id is None:
            if bool(p) == bound:
                return
        elif (account_id in (p or {}).get("assigned_account_ids", [])) == bound:
            return
        await asyncio.sleep(0.1)
    raise TimeoutError(f"proxy {label} bound={bound} for account {account_id} timed out")


async def proxy_ready(owner, label: str, account_id: str | None = None, timeout_s: float = 10.0) -> None:
    """Wait until the product's proxy registry exposes a created or assigned proxy."""
    await _await_bound(owner, label, account_id, True, timeout_s)


@dataclass
class ProxyBinding:
    wire: ProxyWire
    owner: object
    label: str
    assign_status: int | None = None
    account_id: str | None = None
    bound: bool = False

    @property
    def port(self) -> int:
        return self.wire.port

    @property
    def connects(self):
        return self.wire.connects

    async def assign(self, account_id: str) -> None:
        r = await self.owner.post("/admin/proxies/assign", json={"label": self.label, "account_id": account_id})
        self.assign_status = r.status_code
        self.bound = False
        if r.status_code == 200:
            self.account_id = account_id
            try:
                await _await_bound(self.owner, self.label, account_id, True)
            except TimeoutError:
                return
            self.bound = True

TOURS_SEEN = ("localStorage.setItem('vaultProOnboarding', JSON.stringify({batchUploadEntry: '1', "
              "uploadPageStep: '1', batchEdit: '1', uploadBtn: '1'}));")


async def open_vault_picker(page, ctx, account_id: str, fan_id: int, *, timeout: int = 60_000,
                            navigate: bool = True):
    """Open the Messages Pro vault picker and return its dialog."""
    if navigate:
        await page.goto(f"{ctx.app}/messages-pro/{account_id}/{fan_id}",
                        wait_until="domcontentloaded", timeout=timeout)
    button = page.get_by_role("button", name="Vault", exact=True).first
    await button.wait_for(timeout=timeout)
    await button.click(timeout=timeout)
    dialog = page.get_by_role("dialog", name="Vault picker")
    await dialog.wait_for(timeout=timeout)
    return dialog


async def open_vault_pro(page, ctx, *, timeout: int = 60_000) -> None:
    await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=timeout)


async def cdn_count(ctx) -> int:
    return (await ctx.owner.get("/__slop/img/stats")).json()["n"]


async def cdn_calls(ctx, since: int = 0, *, allow_failure: bool = False) -> list[dict]:
    r = await ctx.owner.get(f"/__slop/img/calls?since={since}")
    return r.json()["calls"] if r.status_code == 200 or not allow_failure else []


@asynccontextmanager
async def proxy_bind(owner, label: str, *, notes: str, account_id: str | None = None):
    """Create a wire proxy and optionally bind it; always unbind and close it."""
    with ProxyWire() as wire:
        binding = ProxyBinding(wire, owner, label)
        r = await owner.post("/admin/proxies", json={"label": label, "scheme": "socks5",
                                                     "host": "127.0.0.1", "port": wire.port, "notes": notes})
        r.raise_for_status()
        await proxy_ready(owner, label)
        try:
            if account_id is not None:
                await binding.assign(account_id)
            yield binding
        finally:
            body_failed = sys.exc_info()[0] is not None
            unbind = binding.account_id
            if unbind is not None:
                try:
                    r = await owner.post(f"/admin/proxies/{label}/unbind", json={"account_id": unbind})
                    r.raise_for_status()
                    await _await_bound(owner, label, unbind, False)
                except Exception:
                    if not body_failed:
                        raise
                    logging.exception("proxy %s unbind failed while handling an earlier error", label)


@asynccontextmanager
async def captured(ctx, page, data: dict, name: str):
    """Record a browser error and its failed screenshot in `data`."""
    try:
        yield
    except Exception as e:  # noqa: BLE001 — the scenario check reports it
        data["error"] = f"{type(e).__name__}: {e}"[:600]
        try:
            from slop.actors import ui
            data["failed_shot"] = await ui.shot(ctx, page, name)
        except Exception:  # noqa: BLE001
            pass
