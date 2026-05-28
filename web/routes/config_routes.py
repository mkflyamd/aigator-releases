"""Configuration routes — API key, model, Jira, Confluence, GitHub, username, personas."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from config import load_config as _load_config, save_config as _save_config, CONFIG_FILE, PATCHABLE_CONFIG_KEYS
import shared

router = APIRouter()

# ── Pydantic models ───────────────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    api_key: str
    user_id: str = ""

class ModelRequest(BaseModel):
    model: str

class JiraPatRequest(BaseModel):
    pat: str
    base_url: str = ""
    email: str = ""

class ConfluenceRequest(BaseModel):
    email: str
    token: str
    base_url: str = ""

class GithubConfigRequest(BaseModel):
    url: str
    token: str

class UsernameRequest(BaseModel):
    username: str


# ── API Key ───────────────────────────────────────────────────────────────────

@router.post("/api/config/apikey")
async def save_api_key(req: ApiKeyRequest):
    from llm import get_active_model, reset_provider
    from llm.gateway import get_gateway_url, gateway_headers
    import httpx

    key = req.api_key.strip()
    user_id = req.user_id.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")

    # Set env vars so gateway_headers() picks them up for the test request
    if user_id:
        os.environ["GATEWAY_USER_ID"] = user_id

    try:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            **gateway_headers(key),
        }
        resp = httpx.post(
            f"{get_gateway_url()}/v1/messages",
            headers=headers,
            json={"model": get_active_model(), "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]},
            timeout=15,
        )
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid API key — authentication failed")
        if not resp.is_success:
            raise HTTPException(status_code=500, detail=f"Gateway error {resp.status_code}: {resp.text[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    os.environ["ANTHROPIC_API_KEY"] = key
    reset_provider("anthropic")
    cfg = _load_config()
    cfg["api_key"] = key
    if user_id:
        cfg["gateway_user_id"] = user_id
    _save_config(cfg)
    return {"ok": True}


@router.get("/api/config")
async def get_config():
    return _load_config()


@router.patch("/api/config")
async def patch_config(request: Request):
    body = await request.json()
    cfg = _load_config()
    for k, v in body.items():
        if k in PATCHABLE_CONFIG_KEYS:
            cfg[k] = v
    _save_config(cfg)
    # Update in-memory config so changes take effect immediately
    import shared
    shared.cfg.update(cfg)
    return cfg


@router.get("/api/config/apikey/status")
async def api_key_status():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    user_id = os.environ.get("GATEWAY_USER_ID", "")
    configured = bool(key and key not in ("", "dummy", "amd-gateway") and user_id)
    preview = f"{key[:4]}…{key[-4:]}" if configured and len(key) > 8 else ""
    return {"configured": configured, "preview": preview, "user_id": user_id}


# ── Model ─────────────────────────────────────────────────────────────────────

@router.post("/api/config/model")
async def set_model(req: ModelRequest):
    """Change the active LLM model at runtime."""
    from llm import get_active_model, set_active_model, available_models, context_window
    try:
        set_active_model(req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cfg = _load_config()
    cfg["model"] = req.model
    # Also persist into the active profile so it survives restarts
    active_id = cfg.get("llm_active_profile", "")
    for p in cfg.get("llm_profiles", []):
        if p.get("id") == active_id:
            p["active_model"] = req.model
            break
    _save_config(cfg)
    # Notify all open browser tabs so their model pill stays in sync
    try:
        import shared
        shared.notify_all({"type": "model_changed", "model": req.model})
    except Exception:
        pass
    return {"ok": True, "model": get_active_model()}


@router.get("/api/config/model/status")
async def model_status():
    from llm import get_active_model, available_models, context_window
    m = get_active_model()
    return {
        "model": m,
        "available": available_models(),
        "context_window": context_window(m),
    }


# ── Jira ──────────────────────────────────────────────────────────────────────

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "")

@router.post("/api/config/jira")
def save_jira_pat(req: JiraPatRequest):
    global JIRA_BASE_URL
    token = req.pat.strip()
    email = req.email.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token cannot be empty")
    base_url = req.base_url.strip().rstrip("/")
    is_cloud = "atlassian.net" in base_url
    if is_cloud and not email:
        raise HTTPException(status_code=400, detail="Email is required for Atlassian Cloud")
    import urllib.request as _req2, urllib.error, base64 as _b64
    if is_cloud:
        creds = _b64.b64encode(f"{email}:{token}".encode()).decode()
        auth_header = f"Basic {creds}"
    else:
        auth_header = f"Bearer {token}"
    try:
        r = _req2.Request(f"{base_url}/rest/api/2/myself",
                          headers={"Authorization": auth_header, "Content-Type": "application/json"})
        with _req2.urlopen(r, timeout=10) as resp:
            me = json.loads(resp.read())
        display_name = me.get("displayName", me.get("name", ""))
    except urllib.error.HTTPError as he:
        body = he.read().decode("utf-8", errors="replace")[:300]
        raise HTTPException(status_code=401, detail=f"Jira auth failed: HTTP {he.code} — {body}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Jira auth failed: {e}")
    # Store — Cloud uses email+token, Server uses PAT
    cfg = _load_config()
    if is_cloud:
        os.environ["JIRA_EMAIL"] = email
        os.environ["JIRA_API_TOKEN"] = token
        os.environ.pop("JIRA_PAT_TOKEN", None)
        cfg["jira_email"] = email
        cfg["jira_api_token"] = token
        cfg.pop("jira_pat", None)
    else:
        os.environ["JIRA_PAT_TOKEN"] = token
        os.environ.pop("JIRA_EMAIL", None)
        os.environ.pop("JIRA_API_TOKEN", None)
        cfg["jira_pat"] = token
        cfg.pop("jira_email", None)
        cfg.pop("jira_api_token", None)
    os.environ["JIRA_BASE_URL"] = base_url
    JIRA_BASE_URL = base_url
    cfg["jira_base_url"] = base_url
    _save_config(cfg)
    return {"ok": True, "user": display_name, "base_url": base_url}


@router.get("/api/config/jira/status")
def jira_status():
    import urllib.request as _req2, base64 as _b64
    pat = os.environ.get("JIRA_PAT_TOKEN", "")
    email = os.environ.get("JIRA_EMAIL", "")
    api_token = os.environ.get("JIRA_API_TOKEN", "")
    if pat:
        auth_header = f"Bearer {pat}"
    elif email and api_token:
        creds = _b64.b64encode(f"{email}:{api_token}".encode()).decode()
        auth_header = f"Basic {creds}"
    else:
        return {"configured": False}
    base_url = os.environ.get("JIRA_BASE_URL", JIRA_BASE_URL)
    try:
        r = _req2.Request(f"{base_url}/rest/api/2/myself",
                          headers={"Authorization": auth_header, "Content-Type": "application/json"})
        with _req2.urlopen(r, timeout=10) as resp:
            me = json.loads(resp.read())
        return {"configured": True, "user": me.get("displayName", me.get("name", "")), "base_url": base_url}
    except Exception:
        return {"configured": True, "user": "", "base_url": base_url, "error": "Could not verify"}


# ── Confluence ────────────────────────────────────────────────────────────────

@router.post("/api/config/confluence")
def save_confluence(req: ConfluenceRequest):
    email = req.email.strip()
    token = req.token.strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if not token:
        raise HTTPException(status_code=400, detail="API token is required")
    base_url = req.base_url.strip().rstrip("/")
    # Validate using Basic auth (email:token)
    import urllib.request as _req2, base64 as _b64
    creds = _b64.b64encode(f"{email}:{token}".encode()).decode()
    try:
        r = _req2.Request(f"{base_url}/rest/api/user/current",
                          headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"})
        with _req2.urlopen(r, timeout=10) as resp:
            me = json.loads(resp.read())
        display_name = me.get("displayName", me.get("username", email))
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Confluence auth failed: {e}")
    os.environ["CONFLUENCE_EMAIL"] = email
    os.environ["CONFLUENCE_PAT"] = token
    os.environ["CONFLUENCE_BASE_URL"] = base_url
    cfg = _load_config()
    cfg["confluence_email"] = email
    cfg["confluence_pat"] = token
    cfg["confluence_base_url"] = base_url
    _save_config(cfg)
    return {"ok": True, "user": display_name, "base_url": base_url}


@router.get("/api/config/confluence/status")
def confluence_status():
    email = os.environ.get("CONFLUENCE_EMAIL", "") or os.environ.get("ATLASSIAN_EMAIL", "")
    token = os.environ.get("CONFLUENCE_PAT", "") or os.environ.get("ATLASSIAN_PAT", "")
    if not email or not token:
        return {"configured": False}
    base_url = os.environ.get("CONFLUENCE_BASE_URL", "")
    import urllib.request as _req2, base64 as _b64
    creds = _b64.b64encode(f"{email}:{token}".encode()).decode()
    try:
        r = _req2.Request(f"{base_url}/rest/api/user/current",
                          headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"})
        with _req2.urlopen(r, timeout=10) as resp:
            me = json.loads(resp.read())
        return {"configured": True, "user": me.get("displayName", me.get("username", email)), "base_url": base_url}
    except Exception:
        return {"configured": True, "user": "", "base_url": base_url, "error": "Could not verify"}


# ── GitHub ────────────────────────────────────────────────────────────────────

@router.post("/api/config/github")
def save_github(req: GithubConfigRequest):
    """Validate GitHub PAT and store credentials."""
    token = req.token.strip()
    base_url = req.url.strip().rstrip("/")
    if not token:
        raise HTTPException(status_code=400, detail="Access token is required")
    if not base_url:
        raise HTTPException(status_code=400, detail="GitHub URL is required")
    api_url = f"{base_url}/api/v3/user" if "github.com" not in base_url else "https://api.github.com/user"
    try:
        r = urllib.request.Request(api_url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(r, timeout=10) as resp:
            me = json.loads(resp.read())
        username = me.get("login", "")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"GitHub auth failed: {e}")
    os.environ["GITHUB_TOKEN"] = token
    os.environ["GITHUB_BASE_URL"] = base_url
    cfg = _load_config()
    cfg["github_token"] = token
    cfg["github_base_url"] = base_url
    _save_config(cfg)
    return {"ok": True, "user": username, "base_url": base_url}


@router.get("/api/config/github/status")
def github_status():
    token = os.environ.get("GITHUB_TOKEN", "")
    base_url = os.environ.get("GITHUB_BASE_URL", "")
    if not token:
        return {"configured": False}
    api_url = f"{base_url}/api/v3/user" if base_url and "github.com" not in base_url else "https://api.github.com/user"
    try:
        r = urllib.request.Request(api_url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(r, timeout=10) as resp:
            me = json.loads(resp.read())
        return {"configured": True, "user": me.get("login", ""), "base_url": base_url}
    except Exception:
        return {"configured": True, "user": "", "base_url": base_url, "error": "Could not verify"}


# ── Username ──────────────────────────────────────────────────────────────────

@router.post("/api/config/username")
async def save_username(req: UsernameRequest):
    name = req.username.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    os.environ["AIGATOR_SLACK_USER"] = name
    cfg = _load_config()
    cfg["slack_username"] = name
    _save_config(cfg)
    return {"ok": True, "username": name}

@router.get("/api/config/username/status")
async def username_status():
    name = os.environ.get("AIGATOR_SLACK_USER", "")
    return {"configured": bool(name), "username": name}


# ── Personas ──────────────────────────────────────────────────────────────────

_DEFAULT_PERSONAS = {
    "program-manager": {
        "name": "Program Manager",
        "prompt": (
            "You are helping a **Program Manager** who coordinates cross-team deliverables, "
            "tracks milestones, writes weekly status updates, and communicates with stakeholders.\n\n"
            "Prioritize:\n"
            "- Actionable summaries over raw data\n"
            "- Status/risk/blocker framing\n"
            "- Stakeholder-ready formatting (bullets, tables, clear headers)\n"
            "- Timeline awareness — flag what's late, what's coming up"
        ),
    },
    "engineer": {
        "name": "Engineer",
        "prompt": (
            "You are helping a **Software Engineer** who writes code, debugs issues, "
            "reviews PRs, and tracks technical work across Jira and GitHub.\n\n"
            "Prioritize:\n"
            "- Technical precision — exact error messages, code snippets, commit SHAs\n"
            "- Root cause analysis over symptom summaries\n"
            "- Concise answers — skip the business context unless asked\n"
            "- Link directly to tickets, PRs, and code"
        ),
    },
    "analyst": {
        "name": "Analyst",
        "prompt": (
            "You are helping a **Data/Business Analyst** who gathers requirements, "
            "analyzes data, creates reports, and translates between technical and business teams.\n\n"
            "Prioritize:\n"
            "- Data-driven insights with supporting evidence\n"
            "- Clear visualizations (tables, comparisons)\n"
            "- Context bridging — explain technical details in business terms\n"
            "- Structured analysis (findings, implications, recommendations)"
        ),
    },
}


def _get_personas() -> dict:
    cfg = _load_config()
    personas = cfg.get("personas")
    if personas is None:
        cfg["personas"] = dict(_DEFAULT_PERSONAS)
        _save_config(cfg)
        return cfg["personas"]
    return personas


def _get_active_persona_id() -> str:
    return _load_config().get("active_persona", "")


def _get_active_persona_prompt() -> str:
    pid = _get_active_persona_id()
    if not pid:
        return ""
    personas = _get_personas()
    persona = personas.get(pid)
    if not persona:
        return ""
    return persona.get("prompt", "")


@router.get("/api/config/personas")
async def list_personas():
    personas = _get_personas()
    active = _get_active_persona_id()
    return {"personas": personas, "active": active}


@router.post("/api/config/persona")
async def save_persona(req: dict = Body(...)):
    pid = req.get("id", "").strip()
    name = req.get("name", "").strip()
    prompt = req.get("prompt", "").strip()
    if not pid or not name:
        raise HTTPException(status_code=400, detail="id and name are required")
    cfg = _load_config()
    if "personas" not in cfg:
        cfg["personas"] = dict(_DEFAULT_PERSONAS)
    cfg["personas"][pid] = {"name": name, "prompt": prompt}
    _save_config(cfg)
    return {"ok": True, "id": pid}


@router.delete("/api/config/persona/{persona_id}")
async def delete_persona(persona_id: str):
    cfg = _load_config()
    personas = cfg.get("personas", {})
    if persona_id not in personas:
        raise HTTPException(status_code=404, detail="Persona not found")
    del personas[persona_id]
    if cfg.get("active_persona") == persona_id:
        cfg["active_persona"] = ""
    _save_config(cfg)
    return {"ok": True}


@router.post("/api/config/active-persona")
async def set_active_persona(req: dict = Body(...)):
    pid = req.get("id", "")
    cfg = _load_config()
    cfg["active_persona"] = pid
    _save_config(cfg)
    return {"ok": True, "active": pid}


# ── LLM Profiles ─────────────────────────────────────────────────────────────

import uuid as _uuid


def _fetch_profile_models(profile: dict) -> list[str]:
    """Fetch model list from profile's /v1/models endpoint. Returns list of model IDs.
    Raises HTTPException on auth failure, not-found, or timeout."""
    import httpx
    from llm.gateway import profile_headers
    base = profile.get("base_url", "").rstrip("/")
    url = f"{base}/v1/models"
    headers = profile_headers(profile)
    # For standard OpenAI-compatible APIs (no custom key header), use Bearer auth
    if not profile.get("api_key_header") and profile.get("api_key"):
        headers["Authorization"] = f"Bearer {profile['api_key']}"
    try:
        resp = httpx.get(url, headers=headers, timeout=15)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Could not reach the endpoint — check the URL and your network")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid API key — check your credentials")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Endpoint not found — check the base URL")
    if not resp.is_success:
        raise HTTPException(status_code=502, detail=f"Endpoint error {resp.status_code}")
    data = resp.json()
    # OpenAI /v1/models returns {"data": [{"id": "..."}, ...]}
    items = data.get("data", data) if isinstance(data, dict) else data
    all_ids = [m["id"] if isinstance(m, dict) else str(m) for m in items]
    # Filter out non-chat models (TTS, STT, embeddings) — these can't be used for chat completions
    _NON_CHAT = ("whisper", "distil-whisper", "orpheus", "playai", "embed", "tts", "dall-e")
    return [mid for mid in all_ids if not any(mid.lower().startswith(p) or p in mid.lower() for p in _NON_CHAT)]


@router.get("/api/config/llm/profiles")
async def list_llm_profiles():
    cfg = _load_config()
    return {
        "profiles": cfg.get("llm_profiles", []),
        "active": cfg.get("llm_active_profile", ""),
    }


@router.post("/api/config/llm/profiles")
async def create_or_update_llm_profile(req: dict = Body(...)):
    from llm.registry import load_profile
    cfg = _load_config()
    profiles: list = cfg.setdefault("llm_profiles", [])

    profile = dict(req)
    if not profile.get("id"):
        profile["id"] = str(_uuid.uuid4())

    # Validate credentials and fetch live model list
    models = _fetch_profile_models(profile)
    profile["models"] = models

    # Update in-place if id already exists, otherwise append
    existing_index = next((i for i, p in enumerate(profiles) if p.get("id") == profile["id"]), None)
    is_new = existing_index is None
    if existing_index is not None:
        profiles[existing_index] = profile
    else:
        profiles.append(profile)

    # Auto-activate when this is the very first profile ever added
    if is_new and len(profiles) == 1:
        cfg["llm_active_profile"] = profile["id"]
        _save_config(cfg)
        load_profile(profile)
    else:
        _save_config(cfg)

    return profile


@router.delete("/api/config/llm/profiles/{profile_id}")
async def delete_llm_profile(profile_id: str):
    cfg = _load_config()
    if cfg.get("llm_active_profile") == profile_id:
        raise HTTPException(status_code=400, detail="Cannot delete the active profile")
    profiles: list = cfg.get("llm_profiles", [])
    updated = [p for p in profiles if p.get("id") != profile_id]
    if len(updated) == len(profiles):
        raise HTTPException(status_code=404, detail="Profile not found")
    cfg["llm_profiles"] = updated
    _save_config(cfg)
    return {"ok": True}


@router.post("/api/config/llm/profiles/{profile_id}/activate")
async def activate_llm_profile(profile_id: str):
    from llm.registry import load_profile
    cfg = _load_config()
    profiles: list = cfg.get("llm_profiles", [])
    profile = next((p for p in profiles if p.get("id") == profile_id), None)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    cfg["llm_active_profile"] = profile_id
    _save_config(cfg)
    load_profile(profile)
    return {"ok": True, "active": profile_id}


@router.get("/api/config/llm/profiles/{profile_id}/models")
async def get_llm_profile_models(profile_id: str):
    cfg = _load_config()
    profiles: list = cfg.get("llm_profiles", [])
    profile = next((p for p in profiles if p.get("id") == profile_id), None)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    models = _fetch_profile_models(profile)
    return {"models": models}
