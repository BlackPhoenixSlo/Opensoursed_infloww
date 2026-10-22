"""service/remote_login_api.py — HTTP surface for the served Browserbase login
(job runner: remote_login.py).

  POST /admin/login/remote/start          begin a login job → the job's status
  GET  /admin/login/remote/{id}           poll status (no secrets)
  POST /admin/login/remote/{id}/cancel    cancel the job

The human solves any challenge in the Browserbase live view whose URL the
status carries while the job runs.

SECURITY
  * /admin/login is in employees._AUDIT_SKIP_PREFIXES: the start body carries
    the OnlyFans password and must never reach the audit log.
  * /admin/login is owner-only (chatters._CHATTER_BLOCKED_ADMIN_PREFIXES), like
    /admin/session.
  * Only the principal that started a job may read or cancel it (403).
  * The proxy is resolved with the same visibility rule as binding one
    (server._assert_proxy_assignable): your own or a shared default, never the
    Inflowwww pool or another user's.
"""
from __future__ import annotations

import importlib.util
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

import auth
import remote_login

router = APIRouter()


class _StartBody(BaseModel):
    # Defaults instead of required fields: a 422 echoes the request body, which
    # would send the password back into an error message. Checked by hand below.
    email: str = ""
    password: str = ""
    proxy_label: str = Field("", description="Registry label of the proxy bound to the account (all traffic after the login)")
    nickname: str | None = None
    make_active: bool = True
    backend: str = Field(
        remote_login.BACKEND_LOCAL,
        description='"local" (not available in this build) or "browserbase"',
    )


def _principal() -> str | None:
    u = auth.get_request_user()
    return u.id if u is not None else None


def _require_job(job_id: str) -> remote_login.RemoteLoginJob:
    job = remote_login.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such login job (expired?)")
    if _principal() != job.principal:
        raise HTTPException(status_code=403, detail="not your login job")
    return job


@router.post("/admin/login/remote/start")
def remote_login_start(body: _StartBody = Body(...)) -> dict[str, Any]:
    if not body.email.strip() or not body.password:
        raise HTTPException(status_code=400, detail="email and password are required")
    if not body.proxy_label:
        raise HTTPException(status_code=400, detail="a proxy is required (it is bound to the account)")
    if body.backend not in remote_login.BACKENDS:
        raise HTTPException(status_code=400, detail=(
            f"unknown backend {body.backend!r} (expected one of {remote_login.BACKENDS})"))
    if body.backend == remote_login.BACKEND_BROWSERBASE and importlib.util.find_spec("playwright") is None:
        raise HTTPException(status_code=501, detail=(
            "Browserbase login needs the playwright Python package on the relay"))

    p = remote_login.live_server()._assert_proxy_assignable(body.proxy_label)
    try:
        job = remote_login.start_login(
            email=body.email.strip(), password=body.password,
            proxy_label=p["label"],
            principal=_principal(), nickname=(body.nickname or "").strip() or None,
            make_active=body.make_active, backend=body.backend,
        )
    except remote_login.BackendUnavailable as e:
        raise HTTPException(status_code=501, detail=str(e))
    except remote_login.RemoteLoginConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:  # Browserbase env not configured
        raise HTTPException(status_code=503, detail=str(e))
    return job.public()


@router.get("/admin/login/remote/{job_id}")
def remote_login_status(job_id: str) -> dict[str, Any]:
    return _require_job(job_id).public()


@router.post("/admin/login/remote/{job_id}/cancel")
def remote_login_cancel(job_id: str) -> dict[str, Any]:
    remote_login.cancel(_require_job(job_id))
    return {"ok": True}
