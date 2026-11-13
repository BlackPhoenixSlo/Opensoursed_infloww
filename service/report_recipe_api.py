"""service/report_recipe_api.py — the report recipe's routes (owners only, v1):

  POST /admin/reports/run        → {recipe, format csv|xlsx|json}: the report
                                   (`report_recipe.run`); 400 {errors} per field
                                   when refused, 429 while another run of the
                                   Agency is in flight. The "export" Function
                                   permission's route (permissions.ACTIONS).
  GET  /admin/reports/catalogue  → the datasets a recipe may name: the help
                                   bot's closed book (`report_recipe_decide`).
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import report_recipe
import report_recipe_decide as rd
from agency_context import owner_context

router = APIRouter()

OWNERS_ONLY = "reports are for Agency owners"


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
    try:
        return await report_recipe.run(ctx, body.recipe, body.format)
    except report_recipe.RecipeError as e:
        return JSONResponse({"detail": str(e), "errors": e.errors}, status_code=e.status)


@router.get("/admin/reports/catalogue")
async def catalogue() -> dict[str, Any]:
    await _owner()
    return rd.catalogue_json()
