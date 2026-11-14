"""service/report_recipe_api.py — the report recipe's routes (owners only, v1):

  POST /admin/reports/run        → {recipe, format csv|xlsx|json}: the report
                                   (`report_recipe.run` / `build_file`); 400 {errors} per field
                                   when refused, 429 while another run of the
                                   Agency is in flight. The "export" Function
                                   permission's route (permissions.ACTIONS).
  GET  /admin/reports/catalogue  → the datasets a recipe may name: the help
                                   bot's closed book (`report_recipe_decide`).
  POST /admin/reports/files      → {recipe, format csv|xlsx}: the same file, held
                                   15 min in memory (`report_files`); answers
                                   {id, download_url, filename, bytes, expires_in_s}
                                   (MCP `report_file`: the client saves it).
  GET  /admin/reports/files/{id} → that file, for the user who built it only;
                                   anyone else, unknown or expired: 404.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import report_files
import report_recipe
import report_recipe_decide as rd
from agency_context import owner_context
from auth import get_request_user

router = APIRouter()

OWNERS_ONLY = "reports are for Agency owners"


async def refused(_request: Request, e: report_recipe.RecipeError) -> JSONResponse:
    """report_recipe.RecipeError's answer (server.py registers it): 400/429 {detail, errors}."""
    return JSONResponse({"detail": str(e), "errors": e.errors}, status_code=e.status)


def _download(f: report_recipe.ReportFile | report_files.File) -> Response:
    return Response(f.body, media_type=f.media_type, headers={
        "Content-Disposition": f'attachment; filename="{f.filename}"', "Cache-Control": "no-store"})


class RunBody(BaseModel):
    recipe: dict[str, Any]
    format: Literal["csv", "xlsx", "json"] = "csv"


async def _owner():
    ctx = await owner_context(None, OWNERS_ONLY)
    if not ctx.is_owner:
        raise HTTPException(status_code=403, detail=OWNERS_ONLY)
    return ctx


@router.post("/admin/reports/run", response_model=None)
async def run_report(body: RunBody) -> Any:
    ctx = await _owner()
    if body.format == "json":
        return await report_recipe.run(ctx, body.recipe)
    return _download(await report_recipe.build_file(ctx, body.recipe, body.format))


@router.get("/admin/reports/catalogue")
async def catalogue() -> dict[str, Any]:
    await _owner()
    return rd.catalogue_json()


class FileBody(BaseModel):
    recipe: dict[str, Any]
    format: Literal["csv", "xlsx"] = "csv"


@router.post("/admin/reports/files")
async def make_report_file(body: FileBody) -> Any:
    made = await report_recipe.build_file(await _owner(), body.recipe, body.format)
    try:
        f = report_files.put(get_request_user().id, made.filename, made.media_type, made.body)
    except report_files.TooLarge as e:
        raise HTTPException(status_code=413, detail=str(e)) from None
    except report_files.Full as e:
        raise HTTPException(status_code=429, detail=str(e), headers={"Retry-After": "60"}) from None
    return {"id": f.id, "download_url": report_files.ROUTE.format(file_id=f.id), "filename": f.filename,
            "bytes": len(f.body), "expires_in_s": report_files.TTL_S}


@router.get(report_files.ROUTE)
async def get_report_file(file_id: str) -> Response:
    user = get_request_user()
    f = report_files.get(file_id, user.id) if user is not None else None
    if f is None:
        raise HTTPException(status_code=404, detail="no such report file (links last 15 minutes)")
    return _download(f)
