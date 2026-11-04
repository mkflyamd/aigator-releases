"""Settings routes for the permissions the user saved with "Always allow".

Every route that changes a rule is guarded by verify_csrf, so the in-process agent loop
and widgets cannot grant a permission on the user's behalf.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import permissions
from permissions import registry
from security import verify_csrf

router = APIRouter()


class PermissionModeRequest(BaseModel):
    category: str
    mode: Literal["ask", "always"]


def _category_json(category: registry.Category, rules: list[dict]) -> dict:
    whole = any(r["category"] == category.id and r["subject"] == "" for r in rules)
    return {
        "id": category.id, "label": category.label, "description": category.description, "risk": category.risk,
        "rememberable": category.rememberable, "subject_scoped": category.subject_scoped,
        "mode": None if category.subject_scoped or not category.rememberable else ("always" if whole else "ask"),
        "card": permissions.card_options(category.id),
    }


@router.get("/api/permissions")
def list_permissions():
    rules = permissions.list_rules()
    categories = registry.known()
    shown = {c.id for c in categories}
    for rule in rules:  # a rule for a server that is no longer connected stays visible so it can be removed
        if rule["category"] not in shown:
            extra = registry.get(rule["category"])
            if extra is not None:
                categories.append(extra)
                shown.add(extra.id)
    labels = {c.id: c.label for c in categories}
    return {
        "persistent_allowed": permissions.persistent_allowed(),
        "categories": [_category_json(c, rules) for c in categories],
        "rules": [{"id": r["id"], "category": r["category"], "label": labels.get(r["category"], r["category"]),
                   "subject": r["subject"], "created": r["created"]} for r in rules],
    }


@router.post("/api/permissions/mode", dependencies=[Depends(verify_csrf)])
def set_permission_mode(body: PermissionModeRequest):
    category = registry.get(body.category)
    if category is None or category.subject_scoped or not category.rememberable:
        raise HTTPException(status_code=404, detail="That permission has no setting.")
    if body.mode == "always" and not permissions.persistent_allowed():
        raise HTTPException(status_code=409, detail="Your administrator has turned off Always allow.")
    try:
        permissions.set_mode(body.category, body.mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/api/permissions/rules/{rule_id}", dependencies=[Depends(verify_csrf)])
def remove_permission_rule(rule_id: str):
    if not permissions.remove_rule(rule_id):
        raise HTTPException(status_code=404, detail="That permission was not found.")
    return {"ok": True}


@router.delete("/api/permissions/rules", dependencies=[Depends(verify_csrf)])
def remove_all_permission_rules():
    permissions.remove_all_rules()
    return {"ok": True}
