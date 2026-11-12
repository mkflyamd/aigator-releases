"""`async def` routes run on the event loop, so a blocking network call in one freezes the whole app.

Microsoft Graph calls (sync httpx client, 60s read timeout, retries with time.sleep) must run in
FastAPI's threadpool: make the route a plain `def`, or wrap the call in `await asyncio.to_thread(...)`.
This scan flags any `async def` in web/routes/ that calls a Graph client, a known-blocking HTTP
primitive, or a sync function that does (followed by plain-name calls across web/).
"""

import ast
import builtins
import pathlib

WEB = pathlib.Path(__file__).parent.parent / "web"
ROUTES = WEB / "routes"

CLIENT_FACTORIES = {"get_graph_client", "get_cal_client", "get_skill_client", "GraphClient"}
BLOCKING_MODULE_CALLS = {
    "requests": {"get", "post", "put", "patch", "delete", "head", "request"},
    "httpx": {"get", "post", "put", "patch", "delete", "head", "request", "stream"},
    "urllib.request": {"urlopen"},
    "time": {"sleep"},
}
THREAD_OFFLOADERS = {"to_thread", "run_in_threadpool", "run_in_executor"}


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _own_nodes(func):
    """Walk a function body without descending into nested defs or lambdas (they run later, elsewhere)."""
    stack = [n for n in func.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))]
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                stack.append(child)


def _client_names(func):
    names = set()
    for node in _own_nodes(func):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            callee = _dotted(node.value.func) or ""
            if callee.split(".")[-1] in CLIENT_FACTORIES:
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _direct_blocking(func):
    """Return a description of each blocking call made directly by `func`, or []."""
    clients = _client_names(func)
    found = []
    for node in _own_nodes(func):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        dotted = _dotted(target)
        if dotted:
            module, _, attr = dotted.rpartition(".")
            if attr in BLOCKING_MODULE_CALLS.get(module, ()):
                found.append((node.lineno, dotted))
                continue
            if module in clients:
                found.append((node.lineno, f"Graph client .{attr}()"))
                continue
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Call):
            factory = _dotted(target.value.func) or ""
            if factory.split(".")[-1] in CLIENT_FACTORIES:
                found.append((node.lineno, f"Graph client .{target.attr}()"))
    return found


def _plain_calls(func):
    return {
        n.func.id
        for n in _own_nodes(func)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not hasattr(builtins, n.func.id)
    }


def _parse(path):
    return ast.parse(path.read_bytes(), filename=str(path))


def _sync_blocking_functions():
    """Names of sync functions anywhere under web/ that (transitively, via plain-name calls) block."""
    defs = {}
    for path in WEB.rglob("*.py"):
        if "tests" in path.relative_to(WEB).parts:
            continue
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.FunctionDef):
                defs.setdefault(node.name, []).append(node)
    blocking = {name for name, nodes in defs.items() if any(_direct_blocking(n) for n in nodes)}
    changed = True
    while changed:
        changed = False
        for name, nodes in defs.items():
            if name not in blocking and any(_plain_calls(n) & blocking for n in nodes):
                blocking.add(name)
                changed = True
    return blocking


def _violations():
    blocking = _sync_blocking_functions()
    out = []
    for path in sorted(ROUTES.glob("*.py")):
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for lineno, what in _direct_blocking(node):
                out.append(f"{path.name}:{lineno} {node.name} calls {what}")
            local_defs = {
                n.name for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not node
            }
            for call in _own_nodes(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id in blocking
                    and call.func.id not in local_defs
                    and not hasattr(builtins, call.func.id)
                ):
                    out.append(f"{path.name}:{call.lineno} {node.name} calls blocking {call.func.id}()")
    return out


def test_scan_sees_the_known_blocking_shapes():
    src = (
        "async def route():\n"
        "    gc = get_graph_client()\n"
        "    gc.get('/me')\n"
        "async def ok():\n"
        "    gc = get_graph_client()\n"
        "    await asyncio.to_thread(gc.get, '/me')\n"
        "    await asyncio.to_thread(lambda: gc.get('/me'))\n"
    )
    funcs = {n.name: n for n in ast.parse(src).body}
    assert _direct_blocking(funcs["route"])
    assert not _direct_blocking(funcs["ok"])


def test_async_routes_do_not_block_the_event_loop():
    violations = _violations()
    assert not violations, (
        "async routes call blocking network code on the event loop (one slow Microsoft Graph call "
        "freezes the whole app). Make the route a plain `def`, or use `await asyncio.to_thread(...)`:\n  "
        + "\n  ".join(violations)
    )
