"""Shared utilities for Gator Chat skills.

Lightweight helpers — not a base class. Adopt gradually per-skill.
"""

import asyncio
import functools


# ── Error Handling Decorator ─────────────────────────────────────────────────

def skill_handler(fn):
    """Wrap a tool handler with consistent error handling.

    Supports both sync and async handlers. Replaces the try/except Exception
    boilerplate in every handler.
    Usage:
        @skill_handler
        def _tool_read_excel(file_path, cell, sheet_name=""):
            ...  # no try/except needed
            return {"ok": True, ...}

        @skill_handler
        async def _tool_fetch_async(url):
            ...
            return {"ok": True, ...}
    """
    if asyncio.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                return {"error": str(e)}
        return async_wrapper
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                return {"error": str(e)}
        return wrapper


# ── COM Target Resolution ────────────────────────────────────────────────────

def resolve_com_target(file_path: str, app_type: str):
    """Resolve a COM target from file_path.

    Returns (app, target, error_msg).
    - app: the COM application object
    - target: the workbook/document/presentation
    - error_msg: None on success, str on failure

    Usage:
        app, wb, err = resolve_com_target(file_path, "excel")
        if err:
            return {"error": err}
        # use wb...
    """
    from skills._office_com import (
        get_excel_app, get_excel_workbook,
        get_word_app, get_word_document,
        get_ppt_app, get_ppt_presentation,
    )

    _registry = {
        "excel": (get_excel_app, get_excel_workbook),
        "word":  (get_word_app, get_word_document),
        "ppt":   (get_ppt_app, get_ppt_presentation),
    }

    if app_type not in _registry:
        return None, None, f"Unknown app type: {app_type}"

    get_app, get_target = _registry[app_type]
    app, err = get_app()
    if err:
        return None, None, err
    target, err = get_target(app, file_path)
    if err:
        return None, None, err
    return app, target, None


# ── Batch Wrapper ────────────────────────────────────────────────────────────

def batch_wrapper(operations: list, execute_one):
    """Execute multiple operations via a single-operation callable.

    execute_one: callable(op_dict) → result_dict
        Called for each operation. Should return {"ok": True, ...} or {"error": ...}.

    Usage:
        def _do_one(op):
            return _tool_update_docx(file_path=fp, action=op["action"], ...)
        return batch_wrapper(operations, _do_one)
    """
    if not operations:
        return {"error": "operations array is required for batch mode"}

    results = []
    for i, op in enumerate(operations):
        r = execute_one(op)
        results.append({"op": i + 1, **r})
        if r.get("error"):
            break

    succeeded = sum(1 for r in results if r.get("ok"))
    return {
        "ok": True,
        "message": f"Batch: {succeeded}/{len(operations)} operations completed",
        "results": results,
    }


# ── Contract Validation ─────────────────────────────────────────────────────

def validate_tool_contract(module, module_name: str) -> bool:
    """Verify TOOL_DEFS, TOOL_HANDLERS, and TOOL_STATUS are consistent.

    Call during startup in _load_skill_modules(). Prints warnings for mismatches.
    Returns True if contract is valid.
    """
    defs = getattr(module, "TOOL_DEFS", [])
    handlers = getattr(module, "TOOL_HANDLERS", {})
    status = getattr(module, "TOOL_STATUS", {})

    def_names = {d["name"] for d in defs}
    handler_names = set(handlers.keys())
    status_names = set(status.keys())

    missing_handlers = def_names - handler_names
    missing_status = def_names - status_names
    orphan_handlers = handler_names - def_names

    issues = []
    if missing_handlers:
        issues.append(f"tools defined but no handler: {missing_handlers}")
    if orphan_handlers:
        issues.append(f"handlers with no tool definition: {orphan_handlers}")
    if missing_status:
        issues.append(f"tools missing status message: {missing_status}")

    if issues:
        import logging
        logging.warning("Skill %s tool contract issues: %s", module_name, "; ".join(issues))
    return not bool(issues)
