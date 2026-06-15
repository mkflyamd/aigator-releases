"""Browser automation via browser-use.

ANONYMIZED_TELEMETRY=False is enforced here and at app.py startup.

Key optimizations:
- Session reuse: browser stays warm between tasks (skip 3-5s Chrome launch)
- Haiku for browser steps: 3x faster inference than Sonnet
- Capped DOM size: max_clickable_elements_length=15000
- No iframes: avoids AX tree errors on complex sites
- Profiling: per-step timing logged to server console
"""
import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import asyncio
import logging
import threading
import time as _time

_log = logging.getLogger(__name__)

# InfoBar suppression: not patching CHROME_DEFAULT_ARGS — removing flags
# breaks browser-use's target management. Cosmetic InfoBar is acceptable.

__all__ = ["run_browser_task"]

# ── HITL toolbar injected into every browser page via CDP ─────────────────
# Floating pill HITL — bottom-right corner, communicates via document.dataset
# (avoids CORS/mixed-content issues with HTTPS pages → HTTP localhost)
_HITL_TOOLBAR_BODY = r"""
if(document.getElementById('gator-hitl'))return;
var D=document.documentElement.dataset;
var pill=document.createElement('div');pill.id='gator-hitl';
pill.style.cssText='position:fixed;top:8px;left:8px;z-index:2147483647;background:rgba(10,22,40,.92);border:1px solid #4ade80;border-radius:20px;display:flex;align-items:center;padding:4px 6px 4px 10px;gap:8px;font-family:-apple-system,system-ui,sans-serif;font-size:12px;color:#e2e8f0;box-shadow:0 4px 16px rgba(0,0,0,.4);backdrop-filter:blur(8px);cursor:default;';

function mk(tag,st,txt){var e=document.createElement(tag);e.style.cssText=st;if(txt)e.textContent=txt;return e;}

var dot=mk('span','width:7px;height:7px;border-radius:50%;background:#4ade80;animation:gp 1.5s infinite;flex-shrink:0');
pill.appendChild(dot);
var lbl=mk('span','color:#94a3b8;font-size:11px;white-space:nowrap','\uD83D\uDC0A Gator');
pill.appendChild(lbl);

var pauseBtn=mk('button','font-size:10px;padding:2px 10px;border-radius:12px;border:1px solid #334155;background:#1e293b;color:#e2e8f0;cursor:pointer;font-weight:600;font-family:inherit','Pause');
pill.appendChild(pauseBtn);

var stopBtn=mk('button','font-size:10px;padding:2px 10px;border-radius:12px;border:1px solid #7f1d1d;background:#1e293b;color:#fca5a5;cursor:pointer;font-weight:600;font-family:inherit','Stop');
pill.appendChild(stopBtn);

var s=document.createElement('style');s.id='gator-hitl-style';
s.textContent='@keyframes gp{0%,100%{opacity:1}50%{opacity:.3}}';

function _gatorInject(){
  if(document.getElementById('gator-hitl'))return;
  var target=document.body||document.documentElement;
  if(!document.getElementById('gator-hitl-style'))target.appendChild(s);
  target.appendChild(pill);
  if(document.documentElement.dataset.gatorBotBlock==='true'){
    dot.style.background='#f97316';dot.style.animation='gp 1.5s infinite';
    lbl.textContent='\uD83D\uDC0A Bot wall \u2014 solve CAPTCHA';
    pauseBtn.textContent='Resume';paused=true;pill.style.borderColor='#f97316';
  } else if(document.documentElement.dataset.gatorPaused==='true'){
    dot.style.background='#eab308';dot.style.animation='none';
    lbl.textContent='\uD83D\uDC0A Paused';
    pauseBtn.textContent='Resume';paused=true;pill.style.borderColor='#eab308';
  }
}
function _gatorWatch(){
  if(!document.body){document.addEventListener('DOMContentLoaded',_gatorWatch);return;}
  _gatorInject();
  new MutationObserver(function(){if(!document.getElementById('gator-hitl'))_gatorInject();})
    .observe(document.body,{childList:true});
}
_gatorWatch();

new MutationObserver(function(){
  var bb=document.documentElement.dataset.gatorBotBlock;
  if(bb==='true'){
    dot.style.background='#f97316';dot.style.animation='gp 1.5s infinite';
    lbl.textContent='\uD83D\uDC0A Bot wall \u2014 solve CAPTCHA';
    pauseBtn.textContent='Resume';paused=true;
    pill.style.borderColor='#f97316';
  }
}).observe(document.documentElement,{attributes:true,attributeFilter:['data-gator-bot-block']});

var paused=false;
pauseBtn.onclick=function(){
  paused=!paused;this.textContent=paused?'Resume':'Pause';
  dot.style.background=paused?'#eab308':'#4ade80';
  dot.style.animation=paused?'none':'gp 1.5s infinite';
  lbl.textContent=paused?'\uD83D\uDC0A Paused':'\uD83D\uDC0A Gator';
  pill.style.borderColor=paused?'#eab308':'#4ade80';
  D.gatorAction=paused?'pause':'resume';
  D.gatorPaused=paused?'true':'';
  if(!paused)delete D.gatorBotBlock;
};
stopBtn.onclick=function(){
  lbl.textContent='\uD83D\uDC0A Stopping';
  dot.style.background='#ef4444';dot.style.animation='none';
  D.gatorAction='cancel';
};
"""

# Arrow function for page.evaluate: injects pill if missing + returns pending action
# Wrapped in inner function to isolate the early-return guard from the action read
_HITL_EVAL_JS = "() => { (function(){" + _HITL_TOOLBAR_BODY + "})(); var a=document.documentElement.dataset.gatorAction;document.documentElement.dataset.gatorAction='';return a||'';}"
# IIFE version for CDP addScriptToEvaluateOnNewDocument (raw JS)
_HITL_TOOLBAR_INIT = "(function(){" + _HITL_TOOLBAR_BODY + "})();"

_hitl_script_id = None  # CDP script identifier for cleanup


async def _inject_hitl_toolbar():
    """Inject HITL toolbar into the current browser page."""
    try:
        if _persistent_session:
            page = _persistent_session.get_current_page()
            if asyncio.iscoroutine(page):
                page = await page
            _log.info("[browser] HITL: injecting into current page (page=%s)", bool(page))
            if page:
                await page.evaluate(_HITL_EVAL_JS)
                _log.info("[browser] HITL: toolbar injected into current page OK")
    except Exception as e:
        _log.warning("[browser] HITL toolbar inject FAILED: %s", e)


async def _setup_hitl_init_script():
    """Register HITL toolbar as init script so it runs on every new page."""
    global _hitl_script_id
    _log.info("[browser] HITL: _setup_hitl_init_script called (session=%s, script_id=%s)",
              bool(_persistent_session), _hitl_script_id)
    try:
        if _persistent_session and not _hitl_script_id:
            _hitl_script_id = await _persistent_session._cdp_add_init_script(_HITL_TOOLBAR_INIT)
            _log.info("[browser] HITL toolbar init script registered (id=%s)", _hitl_script_id)
            # Also inject into current page immediately
            await _inject_hitl_toolbar()
    except Exception as e:
        _log.warning("[browser] HITL init script setup FAILED: %s", e)


def _create_browser_llm(cfg: dict, api_key: str, model: str, profile_base_url: str = ""):
    """Create the LLM instance for browser-use based on user's configured provider.

    Reads 'llm_provider' from config. Defaults to 'anthropic'.
    Supports: anthropic, openai, deepseek, google, groq, ollama.
    """
    provider = cfg.get("llm_provider", "anthropic").lower()
    base_url = profile_base_url or cfg.get("llm_base_url", "")

    if provider == "anthropic":
        from llm.gateway import create_gateway_chat_anthropic
        return create_gateway_chat_anthropic(model, api_key, base_url)

    elif provider == "openai":
        from llm.gateway import create_gateway_chat_openai
        return create_gateway_chat_openai(model, api_key, base_url)

    elif provider == "deepseek":
        from browser_use.llm.deepseek.chat import ChatDeepSeek
        return ChatDeepSeek(model=model, api_key=api_key)

    elif provider == "google":
        from browser_use.llm.google.chat import ChatGoogle
        return ChatGoogle(model=model, api_key=api_key)

    elif provider == "groq":
        from browser_use.llm.groq.chat import ChatGroq
        return ChatGroq(model=model, api_key=api_key)

    elif provider == "ollama":
        from browser_use.llm.ollama.chat import ChatOllama
        return ChatOllama(model=model)

    else:
        # Fallback: try anthropic
        _log.warning("[browser] Unknown provider '%s', falling back to anthropic", provider)
        from llm.gateway import create_gateway_chat_anthropic
        return create_gateway_chat_anthropic(model, api_key, base_url)


# ── Persistent session (reused across tasks) ──────────────────────────────
_persistent_session = None
_persistent_profile = None
_cancel_flag = False
_paused = False
_browser_active = False
_step_updates = []  # List of step updates (screenshots + status) for SSE polling
_step_lock = threading.Lock()  # Guards _step_updates (written in worker thread, read from SSE thread)
_hitl_guidance: str = ""  # User correction typed during a HITL pause

# ── Single persistent worker loop ────────────────────────────────────────
# browser-use's internal watchdogs (StorageStateWatchdog, ScreenshotWatchdog,
# etc.) bind their asyncio Tasks to whichever loop they were created on.
# If we create a new event loop per task (the old approach), those tasks are
# "attached to a different loop" on the next call → RuntimeError + crash.
# Solution: one persistent daemon thread + event loop for all browser work.
_worker_loop: asyncio.AbstractEventLoop | None = None
_worker_thread: threading.Thread | None = None


def _ensure_worker_loop() -> asyncio.AbstractEventLoop:
    """Return the persistent browser worker event loop, starting it if needed."""
    global _worker_loop, _worker_thread
    if (_worker_loop is not None
            and not _worker_loop.is_closed()
            and _worker_thread is not None
            and _worker_thread.is_alive()):
        return _worker_loop

    loop = asyncio.new_event_loop()
    _worker_loop = loop

    def _run():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    _worker_thread = threading.Thread(target=_run, daemon=True, name="browser-worker")
    _worker_thread.start()
    _log.info("[browser] Worker event loop started")
    return loop


# Single-slot mutex: only one browser task may run at a time.
# Chrome's CDP WebSocket cannot handle concurrent agents sharing one process —
# they corrupt each other's JSON frames. Second callers get an immediate error
# instead of silently corrupting the session.
_browser_lock: asyncio.Lock | None = None  # created lazily (needs a running loop)


def _get_browser_lock() -> asyncio.Lock:
    global _browser_lock
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    return _browser_lock

# ── Bot-block detection ───────────────────────────────────────────────────
# DataDome (used by Yelp, Ticketmaster etc.) serves its block page on the SAME
# URL with the SAME page title — so title/URL checks miss it. We must inspect
# DOM content for provider-specific fingerprints.
#
# Checked in order: title → URL → DOM content (most expensive, last).
_BOT_BLOCK_TITLES = [
    "access denied", "blocked", "robot check", "captcha", "are you a human",
    "just a moment", "security check", "datadome", "ddos-guard",
    "ray id", "please wait", "attention required",
    "robot or human", "verify you are human", "verify you're human",
]
_BOT_BLOCK_URLS = [
    "datadome.co", "captcha", "recaptcha", "hcaptcha", "challenge",
    "ddos-guard.net", "imperva", "perimeterx", "akamai",
]
# JS snippets — each returns a truthy string (provider name) or empty string.
# Evaluated cheaply via page.evaluate(); first match wins.
_BOT_BLOCK_DOM_CHECKS = [
    # DataDome: iframe from captcha-delivery.com, or dd_ cookie, or specific div
    "document.querySelector('iframe[src*=\"captcha-delivery.com\"]') ? 'DataDome' : ''",
    "document.querySelector('#dataDomeCaptcha,#dd-captcha,[id^=\"datadome\"]') ? 'DataDome' : ''",
    "document.cookie.includes('datadome') ? 'DataDome' : ''",
    # Cloudflare: cf-mitigated header can't be read from JS, but the challenge page has a specific form
    "document.querySelector('#challenge-form,#cf-challenge-running,.cf-browser-verification') ? 'Cloudflare' : ''",
    # Imperva / Incapsula
    "document.querySelector('#incapsula-error,[src*=\"incapsula.com\"]') ? 'Imperva' : ''",
    # PerimeterX / HUMAN
    "document.querySelector('#px-captcha,._pxCaptcha,[id^=\"px-\"]') ? 'PerimeterX' : ''",
    # Generic: body text contains strong bot-block signal
    "(document.body?.innerText||'').toLowerCase().includes('captcha-delivery') ? 'DataDome' : ''",
    # Walmart / Kasada: "activate and hold" button challenge
    "(document.body?.innerText||'').toLowerCase().includes('activate and hold') ? 'Kasada' : ''",
    # Generic hold/press challenge
    "(document.body?.innerText||'').toLowerCase().includes('hold the button') ? 'BotWall' : ''",
]

_bot_block_error: str = ""  # Set when bot-block detected; surfaced in run_browser_task result
_bot_block_reason: str = ""  # Non-empty while a bot-wall HITL pause is active (shown in UI)
_bot_block_resume_at: float = 0.0  # Cooldown: skip bot-block checks until this monotonic time

# ── Browser confirm gate ──────────────────────────────────────────────────
# Maps confirm_id → (asyncio.Event, result_holder) for pending confirm requests.
_pending_confirms: dict[str, tuple[asyncio.Event, list[bool]]] = {}


def resolve_browser_confirm(confirm_id: str, allowed: bool) -> None:
    """Called by REST endpoints to resolve a pending browser confirm gate."""
    if confirm_id in _pending_confirms:
        event, result = _pending_confirms[confirm_id]
        result.append(allowed)
        event.set()

# Max consecutive steps with no screenshot (proxy for tab-detach cascade).
# DataDome kills the tab → browser-use creates a new one → also killed → repeat.
# After this many blank steps we abort rather than loop indefinitely.
_MAX_BLANK_STEPS = 4


def cancel_browser_task():
    """Cancel the currently running browser task."""
    global _cancel_flag
    _cancel_flag = True


def pause_browser():
    """Pause the browser agent — user takes over."""
    global _paused
    _paused = True
    _log.info("[browser] Paused by user (take over)")


def resume_browser():
    """Resume the browser agent — user hands back.

    Clears bot-block state and sets a 5-second cooldown so the agent
    doesn't immediately re-detect the same wall. Safe to call from
    REST API or from the _should_stop() DOM action handler.
    """
    global _paused, _bot_block_reason, _bot_block_resume_at
    _paused = False
    _bot_block_reason = ""
    _bot_block_resume_at = _time.monotonic() + 5
    _log.info("[browser] Resumed by user (hand back)")


def is_browser_active():
    """Check if a browser task is currently running."""
    return _browser_active


def is_browser_paused():
    """Check if the browser agent is paused."""
    return _paused


def send_hitl_guidance(message: str) -> bool:
    """Send a correction from the user to the paused browser agent.

    Returns True if the agent was paused and guidance was accepted,
    False if no agent is paused (caller should handle as a new task).
    """
    global _hitl_guidance, _paused
    if not (_browser_active and _paused):
        return False
    _hitl_guidance = message.strip()
    _log.info("[browser] HITL guidance received: %s", _hitl_guidance[:80])
    return True


def get_step_updates(cursor: int = 0):
    """Get step updates from cursor position onward (non-destructive).

    Returns (updates_list, new_cursor) so multiple readers can poll independently.
    """
    with _step_lock:
        updates = _step_updates[cursor:]
        return updates, len(_step_updates)


_STEALTH_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


async def _apply_stealth(session) -> None:
    """Apply playwright-stealth fingerprint patches via CDP addScriptToEvaluateOnNewDocument.

    Patches canvas, WebGL, navigator.plugins, navigator.languages,
    chrome.runtime, sec-ch-ua headers etc. so every new page automatically
    gets all patches applied before any JS runs.

    Falls back silently — best-effort hardening, not a hard requirement.
    """
    try:
        from playwright_stealth import Stealth
        stealth = Stealth(navigator_user_agent_override=_STEALTH_UA)
        script = stealth.script_payload
        if script:
            await session._cdp_add_init_script(script)
            _log.info("[browser] playwright-stealth init script registered (%d bytes)", len(script))
    except Exception as e:
        _log.debug("[browser] Stealth apply skipped: %s", e)


async def _verify_browser_session(session) -> None:
    """Post-connection smoke test: HITL pill injected, CDP responsive."""
    try:
        page = session.get_current_page()
        if asyncio.iscoroutine(page):
            page = await page
        if not page:
            _log.warning("[browser-verify] No page available for verification")
            return
        try:
            result = await asyncio.wait_for(
                page.evaluate("() => document.readyState"),
                timeout=2.0,
            )
            _log.info("[browser-verify] CDP responsive: readyState=%s", result)
        except asyncio.TimeoutError:
            _log.warning("[browser-verify] CDP unresponsive — page.evaluate timed out")
        try:
            has_pill = await asyncio.wait_for(
                page.evaluate("() => document.getElementById('gator-hitl') !== null"),
                timeout=2.0,
            )
            if has_pill:
                _log.info("[browser-verify] HITL pill injected OK")
            else:
                _log.warning("[browser-verify] HITL pill NOT found — will retry on next step")
        except Exception as e:
            _log.warning("[browser-verify] HITL pill check failed: %s", e)
    except Exception as e:
        _log.warning("[browser-verify] Verification failed (non-fatal): %s", e)



# ── Native browser launcher ───────────────────────────────────────────────
# Launches the user's installed Chrome or Edge with a dedicated Gator profile
# and --remote-debugging-port so browser-use can connect via CDP.
# This avoids the Chromium binary bundled with Playwright and uses the real
# browser the user already has — better fingerprint, real UA, familiar UX.

_NATIVE_CDP_PORT = 9222
_native_browser_proc: "subprocess.Popen | None" = None  # type: ignore[name-defined]

_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
]


def _find_native_browser(prefer: str = "auto") -> str | None:
    """Return path to Chrome or Edge exe, or None if neither found."""
    candidates = []
    if prefer == "edge":
        candidates = _EDGE_PATHS + _CHROME_PATHS
    elif prefer == "chrome":
        candidates = _CHROME_PATHS + _EDGE_PATHS
    else:  # auto: Chrome first, Edge fallback
        candidates = _CHROME_PATHS + _EDGE_PATHS
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def playwright_chromium_installed() -> bool:
    """Return True if Playwright's Chromium binary is present on disk.

    The build doesn't bundle it, so distributed users won't have it unless they
    ran `playwright install`. Used to label the Settings engine picker accurately
    instead of always claiming a download is needed.
    """
    import glob
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if base:
        root = base
    else:
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        root = os.path.join(local, "ms-playwright")
    return bool(glob.glob(os.path.join(root, "chromium-*", "chrome-win*", "chrome.exe")))


def _cdp_port_ready(port: int, timeout: float = 10.0) -> bool:
    """Poll until the CDP /json/version endpoint responds, or timeout."""
    import urllib.request
    import urllib.error
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return True
        except Exception:
            _time.sleep(0.3)
    return False


def _ensure_native_browser(exe: str, port: int, profile_dir: str | None, profile_name: str = "Default") -> bool:
    """Launch native browser with remote debugging if not already listening on port.

    Args:
        exe: path to Chrome/Edge executable
        port: CDP port number
        profile_dir: path to user-data-dir, or None for personal profile mode
                     (uses Chrome's default profile)
        profile_name: Chrome profile directory name for personal mode e.g. "Default", "Profile 1"
                      Bypasses the profile picker when multiple profiles exist.
    """
    global _native_browser_proc
    import subprocess

    # Already listening?
    if _cdp_port_ready(port, timeout=0.5):
        _log.info("[browser] Native browser already listening on port %d", port)
        return True

    # Kill stale proc if it exited
    if _native_browser_proc is not None and _native_browser_proc.poll() is not None:
        _native_browser_proc = None

    if profile_dir:
        # Gator profile: isolated, all stealth flags
        os.makedirs(profile_dir, exist_ok=True)
        cmd = [
            exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ]
    else:
        # Personal profile: minimal flags only — avoids Chrome's
        # "unsupported command-line flag" warning bar.
        # --profile-directory bypasses the profile picker when multiple profiles exist.
        cmd = [
            exe,
            f"--remote-debugging-port={port}",
            f"--profile-directory={profile_name}",
        ]

    _log.info("[browser] Launching native browser: %s (profile=%s/%s)",
              os.path.basename(exe), "gator" if profile_dir else "personal", profile_name if not profile_dir else "isolated")
    _native_browser_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not _cdp_port_ready(port, timeout=20.0):  # 20s — allows time for profile load
        _log.error("[browser] Native browser did not open CDP port %d in time", port)
        return False
    _log.info("[browser] Native browser ready on CDP port %d", port)
    return True


async def _browser_task_impl(task: str, start_url: str, headless: bool) -> dict:
    """Actual browser-use implementation."""
    global _persistent_session, _persistent_profile, _cancel_flag, _hitl_script_id, _bot_block_error, _bot_block_reason, _bot_block_resume_at
    _cancel_flag = False
    _bot_block_error = ""
    _bot_block_reason = ""
    _bot_block_resume_at = 0.0
    try:
        from browser_use import Agent
        from browser_use.browser.profile import BrowserProfile
        from browser_use.browser.session import BrowserSession
        from browser_use.llm.anthropic.chat import ChatAnthropic
        import shared

        cfg = shared.cfg

        # Read API key from the active LLM profile (llm_profiles system).
        # Falls back to legacy cfg["api_key"] / env var for backwards compat.
        from llm.registry import get_active_profile
        _profile = get_active_profile()
        api_key = (
            _profile.get("api_key")
            or cfg.get("api_key")
            or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        # Ensure gateway_headers() picks up the user ID from the profile
        _profile_user = _profile.get("user_id", "")
        if _profile_user and not os.environ.get("GATEWAY_USER_ID"):
            os.environ["GATEWAY_USER_ID"] = _profile_user
        # Use the profile's Anthropic URL (for prompt caching) or base_url
        _profile_base_url = _profile.get("anthropic_url") or _profile.get("base_url", "")

        # Browser mode: fast / balanced (default) / thorough
        mode = cfg.get("browser_mode", "balanced")
        # Model defaults — user can override via config 'browser_model_fast' / 'browser_model_thorough'
        _default_fast = cfg.get("browser_model_fast", "Claude-Haiku-4.5")
        _default_thorough = cfg.get("browser_model_thorough", "Claude-Sonnet-4.6")
        _MODES = {
            "fast":      {"use_vision": False,  "use_judge": False, "flash_mode": True,  "enable_planning": False, "max_actions": 10, "wait_network": 0.5, "wait_action": 0.1, "wait_load": 0.1, "model": _default_fast},
            "balanced":  {"use_vision": "auto", "use_judge": False, "flash_mode": True,  "enable_planning": False, "max_actions": 5,  "wait_network": 2,   "wait_action": 0.3, "wait_load": 0.5, "model": _default_fast},
            "thorough":  {"use_vision": True,   "use_judge": True,  "flash_mode": False, "enable_planning": True,  "max_actions": 3,  "wait_network": 8,   "wait_action": 1.0, "wait_load": 1.0, "model": _default_thorough},
        }
        m = _MODES.get(mode, _MODES["balanced"])
        _log.info("[browser] mode=%s model=%s", mode, m["model"])

        llm = _create_browser_llm(cfg, api_key, m["model"], _profile_base_url)

        # ── Proxy config (optional) ──────────────────────────────────────────
        # Set 'browser_proxy' in config as "http://user:pass@host:port"
        # For residential proxies (Bright Data, Oxylabs, etc.) this is the
        # single most effective anti-bot measure — datacenter IP = instant flag.
        proxy_url = cfg.get("browser_proxy", "").strip()
        proxy_settings = None
        if proxy_url:
            from browser_use.browser.profile import ProxySettings
            proxy_settings = ProxySettings(server=proxy_url)
            _log.info("[browser] Using proxy: %s", proxy_url.split("@")[-1])  # log host only

        # ── browser-use cloud (optional) ────────────────────────────────────
        # Set 'browser_use_cloud: true' in config to route through browser-use's
        # hosted residential browsers (requires BROWSER_USE_API_KEY env var).
        use_cloud = bool(cfg.get("browser_use_cloud", False))

        # ── Native browser (optional) ────────────────────────────────────────
        # Set 'browser_native: true' in config to use the user's installed Chrome
        # or Edge instead of Playwright's Chromium. Connects via CDP on port 9222.
        # Set 'browser_prefer: "chrome"' or '"edge"' to control which is preferred.
        # The browser opens in a dedicated Gator profile so it doesn't mix with
        # the user's normal browser data.
        use_native = bool(cfg.get("browser_native", True))
        native_exe = None
        cdp_url = None
        if use_native:
            browser_profile = cfg.get("browser_profile", "")
            if not browser_profile:
                return {
                    "ok": False,
                    "needs_profile_choice": True,
                    "error": (
                        "Before using the native browser, choose a profile mode:\n\n"
                        "**Personal** — Uses your existing Chrome logins and cookies. "
                        "Best for interactive tasks where you're already logged in.\n\n"
                        "**Gator** — Uses a separate, isolated browser profile. "
                        "Best for background tasks and clean sessions.\n\n"
                        "Set this in Settings \u2192 Browser Engine \u2192 Profile, or tell me which you'd prefer."
                    ),
                }

            prefer = cfg.get("browser_prefer", "auto")
            # For personal mode, which Chrome profile to use (bypasses profile picker)
            profile_name = cfg.get("browser_profile_name", "Default")
            native_exe = _find_native_browser(prefer)
            if native_exe:
                if browser_profile == "personal":
                    profile_dir = None
                else:
                    profile_dir = os.path.join(
                        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "AIGator", "BrowserProfile",
                    )
                ready = await asyncio.get_event_loop().run_in_executor(
                    None, _ensure_native_browser, native_exe, _NATIVE_CDP_PORT, profile_dir, profile_name
                )
                if ready:
                    cdp_url = f"http://127.0.0.1:{_NATIVE_CDP_PORT}"
                    _log.info("[browser] Using native browser via CDP: %s (profile=%s)", cdp_url, browser_profile)
                else:
                    _log.error("[browser] Native browser failed to start on CDP port %d", _NATIVE_CDP_PORT)
                    # Detect most likely cause: Chrome already running (personal mode conflict)
                    _chrome_conflict = (browser_profile == "personal")
                    if _chrome_conflict:
                        _err = (
                            "Chrome couldn't start with the debug port — Chrome is likely already open. "
                            "To use Personal mode: close Chrome first, then retry. "
                            "Or switch to **Gator (isolated)** profile in Settings → Browser Engine "
                            "which works even when Chrome is already running."
                        )
                    else:
                        _err = (
                            "Chrome/Edge could not be started for native browser mode. "
                            "Try switching to **Gator (isolated)** profile in Settings → Browser Engine, "
                            "or switch the engine to Playwright."
                        )
                    return {"ok": False, "error": _err}
            else:
                _log.error("[browser] No Chrome/Edge executable found on this machine")
                return {
                    "ok": False,
                    "error": (
                        "No Chrome or Edge installation found. Native browser mode requires "
                        "Chrome or Edge to be installed. Install one, or switch to Playwright "
                        "in Settings → Browser Engine."
                    ),
                }

        # Reuse browser session if available, matching headless/proxy/cloud/native/mode
        _mode_key = f"{headless}:{mode}:{proxy_url}:{use_cloud}:{cdp_url}"
        if (_persistent_session and _persistent_profile
                and getattr(_persistent_profile, '_mode_key', None) == _mode_key):
            session = _persistent_session
            _log.info("[browser] Reusing existing browser session")
        else:
            # Kill old session if exists
            if _persistent_session:
                await _safe_reset_session(_persistent_session, "mode-change")
                _persistent_session = None

            if cdp_url:
                # Connect to the already-running native browser via CDP.
                # No viewport override — let the browser use its natural window size
                # so content fits without OS-level scrolling.
                profile = BrowserProfile(
                    cdp_url=cdp_url,
                    wait_between_actions=m["wait_action"],
                    captcha_solver=False,  # Don't tell agent CAPTCHAs auto-solve — they don't
                )
                _log.info("[browser] Connecting to native browser at %s", cdp_url)
            else:
                profile_kwargs = dict(
                    headless=headless,
                    wait_between_actions=m["wait_action"],
                    captcha_solver=False,  # Don't tell agent CAPTCHAs auto-solve — they don't
                    # ── Stealth: reduce automation fingerprint ──────────────────
                    # Removes navigator.webdriver=true and the "Chrome is controlled" infobar
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-infobars',
                        '--test-type',          # Suppresses "unsupported command-line flag" InfoBar
                        '--no-first-run',
                        '--no-default-browser-check',
                        '--disable-crash-reporter',
                        '--lang=en-US',
                    ],
                    # Realistic desktop UA — avoids "HeadlessChrome" in the UA string
                    user_agent=_STEALTH_UA,
                    use_cloud=use_cloud,
                )
                if proxy_settings:
                    profile_kwargs["proxy"] = proxy_settings
                profile = BrowserProfile(**profile_kwargs)

            profile._mode_key = _mode_key  # Tag for session reuse check
            session = BrowserSession(browser_profile=profile)
            _persistent_session = session
            _persistent_profile = profile
            _log.info("[browser] Created new browser session (native=%s, cloud=%s, proxy=%s)",
                      use_native, use_cloud, bool(proxy_settings))
            await _verify_browser_session(session)

        full_task = task
        if start_url:
            full_task = f"Go to {start_url}. Then: {task}"

        _SPEED_PROMPT = "Be concise and direct. Use multi-action sequences when possible. Don't explain your actions — just do them. Extract data efficiently."

        global _paused
        _paused = False

        # Profiling
        _step_times = []
        _task_start = _time.monotonic()
        _last_step = [_task_start]
        _blank_step_count = [0]  # consecutive steps with no screenshot (tab-detach proxy)

        def _step_callback(browser_state, agent_output, step_num):
            now = _time.monotonic()
            elapsed = now - _last_step[0]
            total = now - _task_start
            actions = []
            if agent_output and hasattr(agent_output, 'action'):
                acts = agent_output.action if isinstance(agent_output.action, list) else [agent_output.action]
                for a in acts:
                    actions.append(type(a).__name__ if a else '?')
            _step_times.append({"step": step_num, "elapsed_s": round(elapsed, 2), "total_s": round(total, 2), "actions": actions})
            _log.info("[browser-profile] Step %d: %.1fs (total %.1fs) actions=%s", step_num, elapsed, total, actions)
            _last_step[0] = now

            action_names = [a.replace('ActionModel', 'working') for a in actions]

            # Capture screenshot for browser pane; track blank-step cascade
            try:
                if browser_state and hasattr(browser_state, 'screenshot'):
                    screenshot_b64 = browser_state.screenshot
                    if screenshot_b64:
                        _log.info("[browser] Step %d screenshot: %s (%d bytes)", step_num, type(screenshot_b64).__name__, len(screenshot_b64))
                        _blank_step_count[0] = 0  # reset on successful screenshot
                        with _step_lock:
                            _step_updates.append({
                                "step": step_num,
                                "status": f"Step {step_num} \u00B7 {', '.join(action_names) or 'thinking'}",
                                "screenshot": screenshot_b64 if len(screenshot_b64) < 500000 else None,
                            })
                    else:
                        _blank_step_count[0] += 1
                        _log.info("[browser] Step %d screenshot: None (blank count=%d)", step_num, _blank_step_count[0])
                        if _blank_step_count[0] >= _MAX_BLANK_STEPS:
                            _log.warning("[browser] %d consecutive blank steps — tab-detach cascade, aborting", _MAX_BLANK_STEPS)
                            global _cancel_flag, _bot_block_error
                            _bot_block_error = (
                                f"Bot-detection cascade: {_MAX_BLANK_STEPS} consecutive steps had no browser content. "
                                "The site is likely closing tabs as fast as they open. "
                                "Enable a residential proxy or try the native Chrome/Edge engine."
                            )
                            _cancel_flag = True
                            raise KeyboardInterrupt("Tab-detach cascade abort")
            except KeyboardInterrupt:
                raise
            except Exception:
                pass

            # HITL pill injected via _should_stop callback (page.evaluate)

            # Check cancellation (pause/resume handled in _should_stop)
            if _cancel_flag:
                _log.info("[browser] Cancelled at step %d", step_num)
                raise KeyboardInterrupt("Browser task cancelled")

        async def _read_hitl_action():
            """Read and clear gatorAction from DOM. Returns action string."""
            try:
                page = await _persistent_session.get_current_page()
                if page:
                    action = await page.evaluate(_HITL_EVAL_JS)
                    return (action or '').strip()
            except Exception:
                pass
            return ''

        async def _check_bot_block() -> bool:
            """Pause for HITL if the current page is a bot-block wall.

            Checks in order:
            1. Page title keywords  (cheap)
            2. URL patterns         (cheap)
            3. DOM content checks   (needed for DataDome which serves on the real domain)

            Returns False always — the pause loop in _should_stop() will block
            the agent until the user solves the CAPTCHA and clicks Resume.
            """
            global _bot_block_error, _bot_block_reason

            _bot_block_reason_local = ""

            page = None  # Lazy-loaded for DOM checks and attribute setting
            try:
                # Use session methods — browser-use's Page object doesn't have
                # .title() or .url; those live on the session directly.
                title = (await _persistent_session.get_current_page_title() or "").lower()
                url = (await _persistent_session.get_current_page_url() or "").lower()
                _log.debug("[bot-check] title=%r url=%s", title[:60], url[:80])

                # 1. Title
                for pat in _BOT_BLOCK_TITLES:
                    if pat in title:
                        _bot_block_reason_local = f"Bot-detection wall (page title: \"{title}\")"
                        break

                # 2. URL
                if not _bot_block_reason_local:
                    for pat in _BOT_BLOCK_URLS:
                        if pat in url:
                            _bot_block_reason_local = f"Bot-detection wall (URL: {url[:80]})"
                            break

                # 3. DOM content — catches DataDome (same URL, same title, injected iframe)
                #    Need the actual page object for evaluate() calls
                if not _bot_block_reason_local:
                    page = await _persistent_session.get_current_page()
                    if page:
                        for js in _BOT_BLOCK_DOM_CHECKS:
                            try:
                                provider = (await page.evaluate(f"() => {{ return {js} }}") or "").strip()
                                if provider:
                                    _bot_block_reason_local = f"{provider} bot-detection wall (DOM fingerprint on {url[:60]})"
                                    break
                            except Exception:
                                pass

                # If a bot wall was detected, pause for HITL
                if _bot_block_reason_local:
                    _log.warning("[browser] Bot-block detected — pausing for HITL: %s", _bot_block_reason_local)
                    _bot_block_reason = "Solve the CAPTCHA in the browser, then click Resume."
                    _bot_block_error = (
                        f"{_bot_block_reason_local}. "
                        "The site blocks automated browsers. "
                        "Enable a residential proxy in Settings, or try the native Chrome/Edge engine."
                    )
                    pause_browser()
                    with _step_lock:
                        _step_updates.append({
                            "step": -1,
                            "bot_block": True,
                            "status": _bot_block_reason,
                            "detail": _bot_block_reason_local,
                        })
                    # Set toolbar to orange state directly (more reliable than
                    # MutationObserver which may not fire across CDP contexts)
                    _BOT_BLOCK_UI_JS = """() => {
                        var pill = document.getElementById('gator-hitl');
                        if (pill) {
                            var dot = pill.querySelector('span');
                            if (dot) { dot.style.background='#f97316'; dot.style.animation='gp 1.5s infinite'; }
                            var lbl = pill.querySelectorAll('span')[1];
                            if (lbl) lbl.textContent = '\\uD83D\\uDC0A Bot wall \\u2014 solve CAPTCHA';
                            var btn = pill.querySelector('button');
                            if (btn) btn.textContent = 'Resume';
                            pill.style.borderColor = '#f97316';
                        }
                        document.documentElement.dataset.gatorBotBlock = 'true';
                    }"""
                    try:
                        page = page or await _persistent_session.get_current_page()
                        if page:
                            await page.evaluate(_BOT_BLOCK_UI_JS)
                            _log.info("[bot-check] Toolbar set to orange bot-block state")
                        else:
                            _log.warning("[bot-check] No page for bot-block UI update")
                    except Exception as _attr_exc:
                        _log.warning("[bot-check] Failed to set bot-block UI: %s", _attr_exc)

            except Exception as _bb_exc:
                _log.warning("[bot-check] EXCEPTION: %s", _bb_exc, exc_info=True)
            return False

        _stealth_applied = False

        async def _should_stop():
            nonlocal _stealth_applied
            global _hitl_script_id, _hitl_guidance, _bot_block_reason, _bot_block_resume_at
            try:
                # Check for bot-block page before any other logic.
                # If detected, _check_bot_block() calls pause_browser() — the
                # pause loop below will block until the user solves the CAPTCHA.
                # Skip if already paused or within cooldown after resume (gives the
                # agent 5 seconds to navigate away from the bot-block page).
                if not _paused and _time.monotonic() > _bot_block_resume_at:
                    await _check_bot_block()
                else:
                    _log.debug("[bot-check] Skipped: paused=%s cooldown_remaining=%.1f",
                               _paused, max(0, _bot_block_resume_at - _time.monotonic()))

                # Register init scripts once — auto-fires on every new page load.
                # Done here (not at session creation) because the CDP connection
                # isn't ready until after the first agent step starts.
                if not _hitl_script_id and _persistent_session:
                    _hitl_script_id = await _persistent_session._cdp_add_init_script(_HITL_TOOLBAR_INIT)
                    _log.info("[browser] HITL init script registered (id=%s)", _hitl_script_id)
                    await _inject_hitl_toolbar()  # Also inject into the already-open page

                if not _stealth_applied and _persistent_session:
                    await _apply_stealth(_persistent_session)
                    _stealth_applied = True

                action = await _read_hitl_action()
                if action:
                    _log.info("[browser] HITL action: '%s'", action)
                if action == 'pause':
                    pause_browser()
                elif action == 'resume':
                    resume_browser()  # clears bot_block_reason + sets cooldown
                elif action == 'cancel':
                    cancel_browser_task()
                    return True

                # If paused, block here (async — event loop stays alive for DOM reads)
                if _paused:
                    _log.info("[browser] HITL: agent paused — waiting for resume/cancel")
                    # Sync pill to paused state — covers the case where pause came from
                    # the chat card REST API (pill doesn't know about that path)
                    if not _bot_block_reason:
                        try:
                            _sync_page = await _persistent_session.get_current_page()
                            if _sync_page:
                                await _sync_page.evaluate(
                                    "() => {"
                                    " document.documentElement.dataset.gatorPaused='true';"
                                    " var pill=document.getElementById('gator-hitl');"
                                    " if(!pill)return;"
                                    " var dot=pill.querySelector('span');"
                                    " if(dot){dot.style.background='#eab308';dot.style.animation='none';}"
                                    " var lbl=pill.querySelectorAll('span')[1];"
                                    " if(lbl)lbl.textContent='\\uD83D\\uDC0A Paused';"
                                    " var btn=pill.querySelector('button');"
                                    " if(btn)btn.textContent='Resume';"
                                    " pill.style.borderColor='#eab308';"
                                    "}"
                                )
                        except Exception:
                            pass
                    while _paused and not _cancel_flag:
                        await asyncio.sleep(1)
                        # Check for user guidance sent via chat (course correction)
                        if _hitl_guidance:
                            guidance = _hitl_guidance
                            _hitl_guidance = ""
                            # Extend the running agent task with the correction
                            agent.task = agent.task + f"\n\n[User correction]: {guidance}"
                            _log.info("[browser] HITL: guidance applied, auto-resuming")
                            resume_browser()  # clears bot_block_reason + sets cooldown
                            break
                        action = await _read_hitl_action()
                        if action == 'resume':
                            resume_browser()  # clears bot_block_reason + sets cooldown
                            _log.info("[browser] HITL: agent resumed")
                        elif action == 'cancel':
                            cancel_browser_task()
                            return True
                    # Pause loop exited — clear pill DOM state regardless of which
                    # resume path triggered it (pill button or REST API)
                    if not _cancel_flag:
                        try:
                            _clear_page = await _persistent_session.get_current_page()
                            if _clear_page:
                                await _clear_page.evaluate(
                                    "() => { delete document.documentElement.dataset.gatorBotBlock;"
                                    " delete document.documentElement.dataset.gatorPaused; }"
                                )
                        except Exception:
                            pass
            except Exception as e:
                _log.warning("[browser] HITL eval error: %s", e, exc_info=True)
            return _cancel_flag

        agent = Agent(
            task=full_task,
            llm=llm,
            browser_session=session,
            max_actions_per_step=m["max_actions"],
            use_vision=m["use_vision"],
            use_judge=m["use_judge"],
            flash_mode=m["flash_mode"],
            enable_planning=m["enable_planning"],
            extend_system_message=_SPEED_PROMPT if mode != "thorough" else None,
            register_new_step_callback=_step_callback,
            register_should_stop_callback=_should_stop,
            max_clickable_elements_length=15000,
        )

        _log.info("[browser] Starting task: %s (headless=%s, mode=%s)", task[:80], headless, mode)

        # Run agent — extract result immediately, ignore cleanup errors
        result = None
        final_text = ""
        cancelled = False
        try:
            result = await agent.run()
        except KeyboardInterrupt:
            cancelled = True
            _log.info("[browser] Task cancelled by user")
        except Exception as run_err:
            _log.warning("[browser] agent.run() error (may still have results): %s", run_err)

        _total_time = _time.monotonic() - _task_start
        _log.info("[browser-profile] TOTAL: %.1fs across %d steps", _total_time, len(_step_times))
        for s in _step_times:
            _log.info("[browser-profile]   Step %d: %.1fs %s", s["step"], s["elapsed_s"], s["actions"])

        # Extract result — agent may have succeeded before cleanup crashed
        if result:
            try:
                if hasattr(result, "final_result"):
                    fr = result.final_result() if callable(result.final_result) else result.final_result
                    final_text = str(fr) if fr else ""
                if not final_text:
                    final_text = str(result)
            except Exception as extract_err:
                _log.warning("[browser] Result extraction error: %s", extract_err)

        # On success: keep session alive for reuse (saves 3-5s Chrome launch)
        # On cancel/failure: kill session to prevent stale state
        if cancelled or not final_text:
            if _persistent_session:
                await _safe_reset_session(_persistent_session, "cancel/failure")
                _persistent_session = None
                _persistent_profile = None
            _hitl_script_id = None
        else:
            # Clear HITL script ID so it re-registers on next task
            _hitl_script_id = None

        if cancelled:
            err = _bot_block_error or "Browser task cancelled by user"
            return {"ok": False, "error": err}
        if final_text:
            return {"ok": True, "result": final_text}
        return {"ok": False, "error": "Browser task completed but no result extracted"}

    except Exception as exc:
        _log.exception("[browser] Task setup failed: %s", exc)
        _hitl_script_id = None
        if _persistent_session:
            await _safe_reset_session(_persistent_session, "exception")
            _persistent_session = None
            _persistent_profile = None
        return {"ok": False, "error": _friendly_browser_error(str(exc))}


def _friendly_browser_error(err_text: str) -> str:
    """Translate known cryptic browser errors into actionable guidance.

    The most common one for distributed users: Playwright's Chromium binary is
    not installed (the build doesn't bundle it). Nudge them to native Edge/Chrome,
    which needs no download, instead of surfacing the raw Playwright stack message.
    """
    if "Executable doesn't exist" in err_text or "playwright install" in err_text:
        return (
            "The Playwright browser isn't installed on this machine. "
            "Switch to the Chrome / Edge engine in Settings → Browser Engine "
            "(recommended — it uses a browser you already have, no download needed). "
            "Advanced users can instead run: python -m playwright install chromium"
        )
    return err_text


async def run_browser_task(task: str, start_url: str = "", headless: bool | None = None, timeout: int | None = None) -> dict:
    """Run a browser automation task in a worker thread.

    headless=None (default) reads from config 'browser_display':
      'pane' → headless=True (screenshots in Gator's Browser pane)
      'external' → headless=False (visible Chrome window + pane mirror)
    """
    global _browser_active, _step_updates
    import shared

    lock = _get_browser_lock()
    if lock.locked():
        _log.warning("[browser] Rejected concurrent browser task — one is already running: %s", task[:60])
        return {
            "ok": False,
            "error": (
                "A browser task is already running. Only one browser session can run at a time. "
                "Please wait for the current task to finish, or cancel it first."
            ),
        }

    # MVP: always use external browser — headless has site compatibility issues
    headless = False
    if timeout is None:
        timeout = int(shared.cfg.get("browser_timeout", 300))

    async with lock:
        # Set active EARLY so /api/browser/stream doesn't exit before thread starts
        _browser_active = True
        _step_updates = []
        _log.info("[browser] display=%s (headless=%s)", "pane" if headless else "external", headless)
        try:
            # Submit to the PERSISTENT worker loop so that browser-use's internal
            # watchdog tasks (StorageStateWatchdog, ScreenshotWatchdog, etc.) always
            # run on the same loop they were created on. Creating a new loop per task
            # (the old approach) caused "Future attached to a different loop" errors.
            worker_loop = _ensure_worker_loop()
            future = asyncio.run_coroutine_threadsafe(
                _browser_task_impl(task, start_url, headless),
                worker_loop,
            )
            return await asyncio.wait_for(
                asyncio.wrap_future(future),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            _log.warning("[browser] Task timed out after %ds", timeout)
            cancel_browser_task()
            future.cancel()
            # Eagerly clear session so the next task doesn't try to reuse
            # a session that _browser_task_impl hasn't had a chance to clean up yet.
            global _persistent_session, _persistent_profile, _hitl_script_id
            _persistent_session = None
            _persistent_profile = None
            _hitl_script_id = None
            return {"ok": False, "error": f"Browser task timed out after {timeout} seconds"}
        finally:
            _browser_active = False


def _kill_orphaned_chrome():
    """Kill any Chrome processes left over from previous browser-use sessions.

    browser-use launches Chrome with --remote-debugging-port which creates
    orphaned processes if the server crashes or is killed without cleanup.
    """
    import subprocess
    try:
        # Only kill Chrome instances launched by browser-use (they have --remote-debugging-port)
        result = subprocess.run(
            ['wmic', 'process', 'where',
             "name='chrome.exe' and commandline like '%--remote-debugging-port%'",
             'get', 'processid'],
            capture_output=True, text=True, timeout=5,
        )
        pids = [line.strip() for line in result.stdout.split('\n') if line.strip().isdigit()]
        if pids:
            for pid in pids:
                subprocess.run(['taskkill', '/F', '/PID', pid],
                               capture_output=True, timeout=5)
            _log.info("[browser] Killed %d orphaned Chrome processes", len(pids))
    except Exception as e:
        _log.debug("[browser] Orphan cleanup: %s", e)


async def _safe_reset_session(session, label: str = "", timeout: float = 8.0):
    """Reset a browser session with a hard timeout + taskkill fallback.

    session.reset(force=True) can hang indefinitely on Windows when the CDP
    WebSocket is broken (observed 349s+ hangs). We give it `timeout` seconds
    then fall back to forcefully killing the Chrome process.
    """
    if session is None:
        return
    try:
        await asyncio.wait_for(session.reset(force=True), timeout=timeout)
        _log.info("[browser] Session reset OK%s", f" ({label})" if label else "")
    except asyncio.TimeoutError:
        _log.warning("[browser] session.reset timed out after %.0fs%s — force-killing Chrome",
                     timeout, f" ({label})" if label else "")
        _kill_orphaned_chrome()
    except Exception as e:
        _log.warning("[browser] session.reset error%s: %s — force-killing Chrome",
                     f" ({label})" if label else "", e)
        _kill_orphaned_chrome()


async def shutdown_browser():
    """Force-close any open browser session. Call from app lifespan shutdown."""
    global _persistent_session, _persistent_profile, _cancel_flag, _worker_loop
    _cancel_flag = True

    # Kill Chrome immediately — this unblocks the worker thread (which is
    # waiting on CDP) so the event loop drains cleanly before we try session.reset.
    # On Windows, session.reset(force=True) can hang if the CDP WebSocket is
    # already broken; killing the process first avoids that hang entirely.
    _kill_orphaned_chrome()

    # Reset session on the worker loop (where it was created) to avoid
    # "Future attached to a different loop" errors during shutdown.
    if _persistent_session and _worker_loop is not None and _worker_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(
            _safe_reset_session(_persistent_session, "shutdown"),
            _worker_loop,
        )
        try:
            future.result(timeout=10)
        except Exception:
            pass
        _persistent_session = None
        _persistent_profile = None

    # Stop the worker loop after session cleanup
    if _worker_loop is not None and _worker_loop.is_running():
        _worker_loop.call_soon_threadsafe(_worker_loop.stop)

    # Close native browser process if we launched it
    global _native_browser_proc
    if _native_browser_proc is not None and _native_browser_proc.poll() is None:
        _native_browser_proc.terminate()
        _native_browser_proc = None

    _log.info("[browser] Session closed on shutdown")
