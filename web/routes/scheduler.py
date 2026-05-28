from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
import scheduler as sched

router = APIRouter()


class CreateJobRequest(BaseModel):
    name: str
    prompt: str
    trigger_type: str  # 'cron' | 'interval' | 'date'
    trigger_args: dict
    token_budget: int = 50000
    end_date: str | None = None


class UpdateJobRequest(BaseModel):
    name: str | None = None
    prompt: str | None = None
    trigger_type: str | None = None
    trigger_args: dict | None = None
    end_date: str | None = None


# ── List all jobs (must be before /{job_id} to avoid path collision) ────────
@router.get("/api/scheduler/jobs")
async def list_jobs():
    return await sched.list_jobs()


# ── Get single job ──────────────────────────────────────────────────────────
@router.get("/api/scheduler/jobs/{job_id}")
async def get_job(job_id: str):
    job = await sched.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Create job ──────────────────────────────────────────────────────────────
@router.post("/api/scheduler/jobs")
async def create_job(req: CreateJobRequest):
    return await sched.add_job(
        req.name, req.prompt, req.trigger_type, req.trigger_args,
        req.token_budget, req.end_date,
    )


# ── Update job (name / prompt) ──────────────────────────────────────────────
@router.patch("/api/scheduler/jobs/{job_id}")
async def update_job(job_id: str, req: UpdateJobRequest):
    updated = await sched.update_job(
        job_id, req.name, req.prompt,
        req.trigger_type, req.trigger_args, req.end_date,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return updated


# ── Delete job ──────────────────────────────────────────────────────────────
@router.delete("/api/scheduler/jobs/{job_id}")
async def delete_job(job_id: str):
    removed = await sched.remove_job(job_id)
    return {"removed": removed}


# ── Pause job ───────────────────────────────────────────────────────────────
@router.post("/api/scheduler/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    ok = await sched.pause_job(job_id)
    return {"paused": ok}


# ── Resume job ──────────────────────────────────────────────────────────────
@router.post("/api/scheduler/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    ok = await sched.resume_job(job_id)
    return {"resumed": ok}


# ── Run job immediately ────────────────────────────────────────────────────
@router.post("/api/scheduler/jobs/{job_id}/run-now")
async def run_job_now(job_id: str):
    task_id = await sched.run_job_now(job_id)
    return {"task_id": task_id}


# ── Execution history ──────────────────────────────────────────────────────
@router.get("/api/scheduler/history")
async def get_history(request: Request):
    job_id = request.query_params.get("job_id")
    return await sched.get_job_history(job_id=job_id)
