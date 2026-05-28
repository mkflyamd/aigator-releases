from fastapi import APIRouter
import shared

router = APIRouter()


@router.delete("/api/conversation/{context_id}")
async def delete_conversation(context_id: str):
    """Clear server-side history when a tab is closed."""
    await shared.conversation_store.delete(context_id)
    shared.task_state_store.clear(context_id)
    return {"deleted": context_id}
