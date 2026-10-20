"""The script that runs inside the sandbox and executes a marketplace skill's tools.py."""
from marketplace.skill_audit import MARKER

RUNNER_NAME = "_aigator_tool_runner.py"
ARGS_NAME = "_aigator_args.json"
RESULT_NAME = "_aigator_result.json"

_TEMPLATE = r'''
import asyncio
import importlib.util
import inspect
import json
import os
import sys

MARKER = "@@MARKER@@"
ARGS_FILE = "@@ARGS@@"
RESULT_FILE = "@@RESULT@@"
_seen = set()


def _audit(event, args):
    try:
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or not address:
                return
            dest = str(address[0]) + (":" + str(address[1]) if len(address) > 1 else "")
        elif event == "socket.getaddrinfo":
            dest = str(args[0]) + ":" + str(args[1])
        else:
            return
        if dest in _seen or len(_seen) >= 50:
            return
        _seen.add(dest)
        sys.stderr.write(MARKER + dest.replace("\r", " ").replace("\n", " ") + "\n")
        sys.stderr.flush()
    except Exception:
        pass


sys.addaudithook(_audit)


def _write(obj):
    with open(RESULT_FILE, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, default=str)


def _load(skill_dir):
    sys.dont_write_bytecode = True
    sys.path.insert(0, skill_dir)
    spec = importlib.util.spec_from_file_location("_skill_tools", os.path.join(skill_dir, "tools.py"))
    if spec is None or spec.loader is None:
        raise ImportError("could not build a module spec for tools.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_skill_tools"] = module
    spec.loader.exec_module(module)
    return module


def _contract_issues(module):
    defs = getattr(module, "TOOL_DEFS", [])
    handlers = getattr(module, "TOOL_HANDLERS", {})
    status = getattr(module, "TOOL_STATUS", {})
    names = {d["name"] for d in defs}
    issues = []
    if names - set(handlers):
        issues.append("tools defined but no handler: " + str(sorted(names - set(handlers))))
    if set(handlers) - names:
        issues.append("handlers with no tool definition: " + str(sorted(set(handlers) - names)))
    if names - set(status):
        issues.append("tools missing status message: " + str(sorted(names - set(status))))
    return issues


def _describe(module):
    issues = _contract_issues(module)
    if issues:
        return {"ok": False, "error": "tool contract mismatch (" + "; ".join(issues) + ")"}
    defs = [dict(d) for d in getattr(module, "TOOL_DEFS", [])]
    status = {str(k): str(v) for k, v in getattr(module, "TOOL_STATUS", {}).items()}
    return {"ok": True, "defs": defs, "status": status}


async def _await(value):
    return await value


def _invoke(handler, args):
    params = list(inspect.signature(handler).parameters.values())
    first = params[0] if len(params) == 1 else None
    single_dict = (
        first is not None
        and first.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY)
        and first.annotation in (dict, "dict")
    )
    if single_dict:
        result = handler(args)
    else:
        kwargs = {k: v for k, v in args.items() if k != "_context_id"}
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            accepted = {p.name for p in params}
            kwargs = {k: v for k, v in kwargs.items() if k in accepted}
        result = handler(**kwargs)
    if inspect.isawaitable(result):
        result = asyncio.run(_await(result))
    return result


def main():
    mode, skill_dir = sys.argv[1], sys.argv[2]
    try:
        module = _load(skill_dir)
        if mode == "describe":
            _write(_describe(module))
            return
        name = sys.argv[3]
        handler = getattr(module, "TOOL_HANDLERS", {}).get(name)
        if handler is None:
            _write({"ok": False, "error": "unknown tool " + name})
            return
        with open(ARGS_FILE, encoding="utf-8") as fh:
            args = json.load(fh)
        if not isinstance(args, dict):
            args = {}
        result = _invoke(handler, args)
        if not isinstance(result, dict):
            _write({"ok": False, "error": "the tool returned something that is not a JSON object"})
            return
        _write({"ok": True, "result": result})
    except BaseException as exc:
        _write({"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:500]})


main()
'''

RUNNER_SOURCE = (
    _TEMPLATE.replace("@@MARKER@@", MARKER)
    .replace("@@ARGS@@", ARGS_NAME)
    .replace("@@RESULT@@", RESULT_NAME)
)
