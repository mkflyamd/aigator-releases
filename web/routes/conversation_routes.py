from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import shared

router = APIRouter()


class SeedRequest(BaseModel):
    history: list[dict]


@router.delete("/api/conversation/{context_id}")
async def delete_conversation(context_id: str):
    """Clear server-side history when a tab is closed."""
    await shared.conversation_store.delete(context_id)
    shared.task_state_store.clear(context_id)
    return {"deleted": context_id}


@router.post("/api/conversation/{context_id}/seed")
async def seed_conversation(context_id: str, req: SeedRequest):
    """Seed conversation history for a new context_id (used by fork-to-new-tab).

    Refuses to overwrite an existing conversation — fork always creates a fresh
    context_id, so a collision indicates a client-side bug worth surfacing.
    """
    if shared.conversation_store.has(context_id):
        raise HTTPException(status_code=409, detail="Conversation already exists for this context_id")
    await shared.conversation_store.seed(context_id, req.history)
    return {"seeded": context_id, "turns": len(req.history)}
