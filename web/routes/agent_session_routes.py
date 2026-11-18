"""Agent session history: this project's past and live agent sessions.

GET only. Resume goes through POST /api/generic-agent/terminal (resume_id), which
already requires CSRF, so nothing here mutates state.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

import agent_handoff
import agent_liveness
import agent_sessions
import generic_agent
from skills.code_agent import projects as code_projects

router = APIRouter()


def _repo_path(project_name: str) -> str:
    repo_path = (code_projects.get_project(project_name) or {}).get("repo_path")
    if not repo_path:
        raise HTTPException(status_code=404, detail="Unknown project.")
    return repo_path


def _live_terminals(pty: list[str]) -> list[dict]:
    live = []
    for item in pty:
        agent, _, pty_id = item.partition(":")
        if agent not in agent_sessions.AGENTS or not pty_id:
            continue
        session_id = generic_agent.linked_session_id(pty_id)
        created_at = agent_handoff._session_started_at(pty_id)
        if session_id is None and created_at is None:
            continue
        live.append({"agent": agent, "pty_session_id": pty_id, "session_id": session_id, "created_at": created_at})
    return live


def _join_live_processes(records: list[dict], redact) -> list[dict]:
    """Mark sessions open outside Gator and show the live process's own name for any live session."""
    newest = {}
    for agent in {r["agent"] for r in records}:
        for proc in sorted(agent_liveness.live_processes(agent), key=lambda p: p["started_at"]):
            newest[(agent, proc["session_id"])] = proc
    out = []
    for rec in records:
        proc = newest.get((rec["agent"], rec["id"]))
        if proc is None:
            out.append(rec)
            continue
        rec = dict(rec)
        if proc["name"]:
            rec["title"] = redact(proc["name"])
        if "pty_session_id" not in rec:
            rec["live_elsewhere"] = True
        out.append(rec)
    return out


def _list_sessions(repo_path: str, pty: list[str]) -> dict:
    agents = tuple(a for a in agent_sessions.AGENTS if generic_agent.is_installed(a))
    records = agent_sessions.scan_project(repo_path, agents=agents)
    wsl, pending = agent_sessions.wsl_sessions(repo_path)
    records = sorted([*records, *wsl], key=lambda r: r["last_active_at"], reverse=True)
    records = records[: agent_sessions.MAX_SESSIONS]
    red = agent_handoff.Redactor(agent_handoff._configured_api_keys())
    records = [dict(r, title=red(r["title"])) for r in records]
    joined = _join_live_processes(agent_sessions.join_live(records, _live_terminals(pty)), red)
    return {"sessions": [agent_sessions.public(r) for r in joined], "wsl_pending": pending}


@router.get("/api/agent-sessions")
async def list_agent_sessions(project_name: str, pty: list[str] = Query(default=[])):
    repo_path = _repo_path(project_name)
    return await asyncio.to_thread(_list_sessions, repo_path, pty)


@router.get("/api/agent-sessions/{agent}/{session_id}/preview")
async def preview_agent_session(agent: str, session_id: str, project_name: str):
    if agent not in agent_sessions.AGENTS or not agent_sessions.SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Unknown agent or session id.")
    repo_path = _repo_path(project_name)

    def load():
        rec = agent_sessions.find_session(repo_path, agent, session_id)
        if rec is None:
            return None
        try:
            return agent_sessions.preview(rec)
        except OSError:
            return None

    messages = await asyncio.to_thread(load)
    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"messages": messages}
