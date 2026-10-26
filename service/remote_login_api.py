"""service/remote_login_api.py — HTTP surface for the served Browserbase login
(job runner: remote_login.py).

  POST /admin/login/remote/start          begin a login job → the job's status
  GET  /admin/login/remote/{id}           poll status (no secrets)
  POST /admin/login/remote/{id}/otp       {"code"}: the 2FA code, while the job is in "otp"
                                          (404 once the job is past its code deadline, the
                                          answer for an expired job)
  POST /admin/login/remote/{id}/cancel    cancel the job

The human solves any challenge in the Browserbase live view whose URL the
status carries while the job runs. A 2FA code can be typed there too, or sent
to /otp: the job's thread types it into OnlyFans; a code OnlyFans does not take
leaves the job in "otp", asking again (remote_login.OTP_REJECTED). One code at a
time: while one is pending or being checked, another is 409.

SECURITY
  * /admin/login is in employees._AUDIT_SKIP_PREFIXES: the start body carries
    the OnlyFans password and must never reach the audit log.
  * /admin/login is owner-only (chatters._CHATTER_BLOCKED_ADMIN_PREFIXES), like
    /admin/session.
  * Only the principal that started a job may read, answer or cancel it (403).
  * The 2FA code is never echoed: not in the status, not in an error, not in a
    log line (the /otp body is audit-skipped with the rest of /admin/login).
  * The proxy is the Add creator flow's Proxy selection: "infloww" (the
    Inflowwww proxy), "none" or "custom" + proxy_label. Our proxy is never sent
    to Browserbase; it is bound after the login (remote_login.bind_proxy). With
    no choice given, the flow's default: the Inflowwww proxy when the relay has
    a pool, else none. A custom label goes through the same visibility rule as
    binding one (server._assert_proxy_assignable): your own or a shared
    default, never another user's.
"""
from __future__ import annotations

import importlib.util
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

import auth
import proxies as proxy_registry
import remote_login
from brand import BRAND_NAME

router = APIRouter()


class _StartBody(BaseModel):
    # Defaults instead of required fields: a 422 echoes the request body, which
    # would send the password back into an error message. Checked by hand below.
    email: str = ""
    password: str = ""
    proxy: str = Field("", description=(
        '"infloww" (Inflowwww proxy), "none" (server IP) or "custom" (proxy_label); bound to the account after the '
        'login. Default: "custom" when proxy_label is given, else the Inflowwww proxy when the relay has one, else none'))
    proxy_label: str = Field("", description="Registry label of a custom proxy")
    nickname: str | None = None
    make_active: bool = True
    backend: str = Field(
        remote_login.BACKEND_LOCAL,
        description='"local" (not available in this build) or "browserbase"',
    )


def _principal() -> str | None:
    u = auth.get_request_user()
    return u.id if u is not None else None


_NO_JOB = "no such login job (expired?)"


def _require_job(job_id: str) -> remote_login.RemoteLoginJob:
    job = remote_login.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=_NO_JOB)
    if _principal() != job.principal:
        raise HTTPException(status_code=403, detail="not your login job")
    return job


def _resolve_proxy(choice: str, label: str) -> tuple[str, str]:
    """(proxy choice, custom label), checked before any job exists."""
    has_pool = bool(proxy_registry.pool_entries())
    choice = choice or (remote_login.PROXY_CUSTOM if label else
                        remote_login.PROXY_INFLOWWW if has_pool else remote_login.PROXY_NONE)
    if choice not in remote_login.PROXY_CHOICES:
        raise HTTPException(status_code=400, detail=(
            f"unknown proxy {choice!r} (expected one of {remote_login.PROXY_CHOICES})"))
    if choice == remote_login.PROXY_CUSTOM:
        if not label:
            raise HTTPException(status_code=400, detail="a custom proxy needs proxy_label")
        return choice, remote_login.live_server()._assert_proxy_assignable(label)["label"]
    if choice == remote_login.PROXY_INFLOWWW and not has_pool:
        raise HTTPException(status_code=409, detail=f"no {BRAND_NAME} proxies are set up on this relay")
    return choice, ""


@router.post("/admin/login/remote/start")
def remote_login_start(body: _StartBody = Body(...)) -> dict[str, Any]:
    if not body.email.strip() or not body.password:
        raise HTTPException(status_code=400, detail="email and password are required")
    if body.backend not in remote_login.BACKENDS:
        raise HTTPException(status_code=400, detail=(
            f"unknown backend {body.backend!r} (expected one of {remote_login.BACKENDS})"))
    if body.backend == remote_login.BACKEND_BROWSERBASE and importlib.util.find_spec("playwright") is None:
        raise HTTPException(status_code=501, detail=(
            "Browserbase login needs the playwright Python package on the relay"))

    proxy, label = _resolve_proxy(body.proxy, body.proxy_label)
    try:
        job = remote_login.start_login(
            email=body.email.strip(), password=body.password,
            proxy=proxy, proxy_label=label,
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


@router.post("/admin/login/remote/{job_id}/otp")
def remote_login_otp(job_id: str, body: Any = Body(None)) -> dict[str, Any]:
    # Any, checked by hand: a pydantic 422 would echo the body (the code) back.
    job = _require_job(job_id)
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str):
        raise HTTPException(status_code=400, detail='the body is {"code": "<6 to 8 digits>"}')
    try:
        job.submit_otp(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except remote_login.RemoteLoginExpired:  # past its code deadline (its thread types no code), maybe still "otp"
        raise HTTPException(status_code=404, detail=_NO_JOB)
    except remote_login.RemoteLoginConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    return job.public()
