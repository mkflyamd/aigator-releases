"""Local speech-to-text for dictation."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from dictation import service
from security import verify_csrf

router = APIRouter()


@router.post("/api/dictation/transcribe", dependencies=[Depends(verify_csrf)])
async def transcribe(request: Request):
    """Body: raw 16 kHz mono PCM16 little-endian bytes. Returns {"text": ...}."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > service.MAX_PCM_BYTES:
        raise HTTPException(status_code=413, detail="audio too long")
    pcm = await request.body()
    if len(pcm) > service.MAX_PCM_BYTES:
        raise HTTPException(status_code=413, detail="audio too long")
    if len(pcm) % 2:
        raise HTTPException(status_code=400, detail="audio length must be even (PCM16)")
    if not pcm:
        return {"text": ""}
    try:
        text = await asyncio.get_running_loop().run_in_executor(None, service.transcribe, pcm)
    except service.DictationUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"text": text}
