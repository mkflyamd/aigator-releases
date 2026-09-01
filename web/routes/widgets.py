"""Widget persistence endpoints — save, load, delete, list user-created HTML widgets."""
import json
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import GATOR_DIR

router = APIRouter()

WIDGETS_DB = GATOR_DIR / "widgets.db"


async def _init_db():
    WIDGETS_DB.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(WIDGETS_DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS widgets (
                widget_id   TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT,
                html        TEXT NOT NULL,
                pinned      INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)
        await db.commit()


class SaveWidgetRequest(BaseModel):
    name: str
    description: str = ""
    html: str
    pinned: bool = False


class UpdateWidgetRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    html: str | None = None
    pinned: bool | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return {
        "widget_id": row["widget_id"],
        "name": row["name"],
        "description": row["description"] or "",
        "html": row["html"],
        "pinned": bool(row["pinned"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/api/widgets")
async def list_widgets():
    await _init_db()
    async with aiosqlite.connect(WIDGETS_DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM widgets ORDER BY pinned DESC, updated_at DESC"
        )
        rows = await cur.fetchall()
    return {"widgets": [_row_to_dict(r) for r in rows]}


@router.post("/api/widgets")
async def save_widget(req: SaveWidgetRequest):
    await _init_db()
    widget_id = str(uuid.uuid4())
    now = _now()
    async with aiosqlite.connect(WIDGETS_DB) as db:
        await db.execute(
            "INSERT INTO widgets (widget_id, name, description, html, pinned, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (widget_id, req.name, req.description, req.html, int(req.pinned), now, now),
        )
        await db.commit()
    return {"widget_id": widget_id, "name": req.name, "created_at": now}


@router.get("/api/widgets/{widget_id}")
async def get_widget(widget_id: str):
    await _init_db()
    async with aiosqlite.connect(WIDGETS_DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM widgets WHERE widget_id = ?", (widget_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Widget not found")
    return _row_to_dict(row)


@router.patch("/api/widgets/{widget_id}")
async def update_widget(widget_id: str, req: UpdateWidgetRequest):
    await _init_db()
    async with aiosqlite.connect(WIDGETS_DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM widgets WHERE widget_id = ?", (widget_id,))
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Widget not found")
        name = req.name if req.name is not None else row["name"]
        description = req.description if req.description is not None else row["description"]
        html = req.html if req.html is not None else row["html"]
        pinned = int(req.pinned) if req.pinned is not None else row["pinned"]
        now = _now()
        await db.execute(
            "UPDATE widgets SET name=?, description=?, html=?, pinned=?, updated_at=? WHERE widget_id=?",
            (name, description, html, pinned, now, widget_id),
        )
        await db.commit()
    return {"ok": True, "widget_id": widget_id, "updated_at": now}


@router.delete("/api/widgets/{widget_id}")
async def delete_widget(widget_id: str):
    await _init_db()
    async with aiosqlite.connect(WIDGETS_DB) as db:
        cur = await db.execute("DELETE FROM widgets WHERE widget_id = ?", (widget_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Widget not found")
    return {"ok": True, "widget_id": widget_id}
