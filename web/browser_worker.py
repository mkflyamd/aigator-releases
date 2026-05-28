"""Browser worker — runs as a separate process for proper window rendering.

Called by browser_agent.py via subprocess. Outputs result as JSON to stdout.
This gives the browser its own process with full window management.

Usage:
    python browser_worker.py '{"task":"search for X","start_url":"","headless":false,"mode":"balanced"}'
"""
import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import asyncio
import json
import sys
import logging
import time as _time

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("browser_worker")


async def run(task: str, start_url: str, headless: bool, mode: str, cfg: dict):
    from browser_use import Agent

    api_key = cfg.get("api_key", os.environ.get("ANTHROPIC_API_KEY", ""))

    # Create LLM
    _MODELS = {
        "fast": cfg.get("browser_model_fast", "Claude-Haiku-4.5"),
        "balanced": cfg.get("browser_model_fast", "Claude-Haiku-4.5"),
        "thorough": cfg.get("browser_model_thorough", "Claude-Sonnet-4.6"),
    }
    model = _MODELS.get(mode, _MODELS["balanced"])

    from llm.gateway import create_gateway_chat_anthropic
    base_url = cfg.get("llm_base_url", "")
    llm = create_gateway_chat_anthropic(model, api_key, base_url)

    _MODE_SETTINGS = {
        "fast":     {"use_vision": False,  "flash_mode": True,  "max_actions": 10, "wait": 0.1},
        "balanced": {"use_vision": "auto", "flash_mode": True,  "max_actions": 5,  "wait": 0.3},
        "thorough": {"use_vision": True,   "flash_mode": False, "max_actions": 3,  "wait": 1.0},
    }
    m = _MODE_SETTINGS.get(mode, _MODE_SETTINGS["balanced"])

    full_task = task
    if start_url:
        full_task = f"Go to {start_url}. Then: {task}"

    _task_start = _time.monotonic()

    # Simplest possible Agent setup — no custom BrowserProfile/BrowserSession.
    # Let browser-use handle everything (this is how the quickstart docs work).
    agent = Agent(
        task=full_task,
        llm=llm,
    )

    _log.info("[browser-worker] Starting: %s (mode=%s, model=%s)", task[:80], mode, model)

    result = None
    try:
        result = await agent.run()
    except Exception as e:
        _log.warning("[browser-worker] agent.run error: %s", e)

    total = _time.monotonic() - _task_start
    _log.info("[browser-worker] Done in %.1fs", total)

    # Extract result
    final_text = ""
    if result:
        try:
            if hasattr(result, "final_result"):
                fr = result.final_result() if callable(result.final_result) else result.final_result
                final_text = str(fr) if fr else ""
            if not final_text:
                final_text = str(result)
        except Exception:
            pass

    # Cleanup
    try:
        if hasattr(agent, 'browser_session') and agent.browser_session:
            await agent.browser_session.reset(force=True)
    except Exception:
        pass

    return {"ok": bool(final_text), "result": final_text or "(no output)", "time": round(total, 1)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "No args provided"}))
        sys.exit(1)

    args = json.loads(sys.argv[1])

    # Load config
    sys.path.insert(0, os.path.dirname(__file__))
    from config import load_config
    cfg = load_config()
    if cfg.get("api_key"):
        os.environ["ANTHROPIC_API_KEY"] = cfg["api_key"]
    if cfg.get("gateway_user_id"):
        os.environ["GATEWAY_USER_ID"] = cfg["gateway_user_id"]
    if cfg.get("llm_gateway_url"):
        os.environ["LLM_GATEWAY_URL"] = cfg["llm_gateway_url"]
    if cfg.get("llm_gateway_key_header"):
        os.environ["GATEWAY_KEY_HEADER"] = cfg["llm_gateway_key_header"]
    if cfg.get("llm_gateway_user_field"):
        os.environ["GATEWAY_USER_FIELD"] = cfg["llm_gateway_user_field"]

    result = asyncio.run(run(
        task=args["task"],
        start_url=args.get("start_url", ""),
        headless=args.get("headless", False),
        mode=args.get("mode", "balanced"),
        cfg=cfg,
    ))

    # Output result as JSON on last line (for subprocess capture)
    print("__RESULT__" + json.dumps(result))
