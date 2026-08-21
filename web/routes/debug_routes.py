"""Debug endpoints for turn telemetry — triage stuck/stalled/errored turns.

CSRF-guarded, intended for the developer/debugging UI, not end users.
Output is JSON, ready for a future debug panel or direct curl/inspection.
"""

from fastapi import APIRouter, Depends, Query
from security import verify_csrf
import turn_telemetry

router = APIRouter()


@router.get("/api/debug/turns/{context_id}", dependencies=[Depends(verify_csrf)])
async def get_conversation_turns(context_id: str, limit: int = Query(100, le=500)):
    """Full turn timeline for a conversation, ordered by time. Each row includes
    next_turn_id / next_turn_delay_s so you can see if the user continued or
    gave up after an error."""
    return {
        "context_id": context_id,
        "turns": await turn_telemetry.get_conversation_timeline(context_id, limit),
    }


@router.get("/api/debug/turns", dependencies=[Depends(verify_csrf)])
async def get_turns_by_outcome(
    outcome: str = Query(...), limit: int = Query(50, le=500)
):
    """Find all turns with a given outcome (e.g. 'stalled', 'llm_error',
    'circuit_breaker', 'max_iterations', 'cancelled')."""
    return {
        "outcome": outcome,
        "turns": await turn_telemetry.get_turns_by_outcome(outcome, limit),
    }


@router.get("/api/debug/stuck", dependencies=[Depends(verify_csrf)])
async def get_stuck_conversations():
    """Find conversations where the last turn was 'stalled', 'llm_error',
    'circuit_breaker', or 'max_iterations' AND no follow-up turn was logged —
    i.e. the user likely gave up. The highest-value triage query."""
    return {"stuck": await turn_telemetry.get_stuck_conversations()}
