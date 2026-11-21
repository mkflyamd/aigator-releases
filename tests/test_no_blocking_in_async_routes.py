"""`async def` routes run on the event loop, so a blocking network call in one freezes the whole app.

Microsoft Graph calls (sync httpx client, 60s read timeout, retries with time.sleep) must run in
FastAPI's threadpool: make the route a plain `def`, or wrap the call in `await asyncio.to_thread(...)`.
This scan flags any `async def` in web/routes/ and web/app.py that calls a Graph client, a token
fetch, a model call, a subprocess wait, a known-blocking HTTP primitive, a handler picked out of a
`*HANDLERS` dict, or a sync function that does (followed by plain-name calls across web/).
"""

import ast
import builtins
import pathlib

WEB = pathlib.Path(__file__).parent.parent / "web"
SCANNED = [*sorted((WEB / "routes").glob("*.py")), WEB / "app.py"]

CLIENT_FACTORIES = {"get_graph_client", "get_cal_client", "get_skill_client", "make_teams_gc", "GraphClient"}
BLOCKING_ATTR_CALLS = {"get_auth", "get_teams_token", "simple_complete"}
BLOCKING_MODULE_CALLS = {
    "subprocess": {"run", "call", "check_call", "check_output"},
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


def _aliases(tree):
    """Map every imported local name to its real dotted name (`import httpx as _httpx`, `from time import sleep`)."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    out[a.asname] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _resolve(dotted, aliases):
    head, sep, rest = dotted.partition(".")
    return aliases[head] + sep + rest if head in aliases else dotted


def _client_names(func):
    names = set()
    for node in _own_nodes(func):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            callee = _dotted(node.value.func) or ""
            if callee.split(".")[-1] in CLIENT_FACTORIES:
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _handler_names(func):
    """Local names bound to a handler looked up in a `*HANDLERS` dict (`h = TOOL_HANDLERS.get(name)`)."""
    names = set()
    for node in _own_nodes(func):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if isinstance(value, ast.Call):
            value = value.func.value if isinstance(value.func, ast.Attribute) else None
        elif isinstance(value, ast.Subscript):
            value = value.value
        if value is not None and "handlers" in (_dotted(value) or "").lower():
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _direct_blocking(func, aliases=None):
    """Return a description of each blocking call made directly by `func`, or []."""
    aliases = aliases or {}
    clients = _client_names(func)
    handlers = _handler_names(func)
    found = []
    for node in _own_nodes(func):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        dotted = _dotted(target)
        called = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if called in BLOCKING_ATTR_CALLS:
            found.append((node.lineno, dotted or called))
            continue
        if called in ("wait", "communicate") and "proc" in (_dotted(target.value) or "").lower():
            found.append((node.lineno, f"{dotted} (waits on a subprocess)"))
            continue
        if isinstance(target, ast.Name) and target.id in handlers:
            found.append((node.lineno, f"{target.id}() (a sync handler picked from a dict)"))
            continue
        if dotted:
            resolved = _resolve(dotted, aliases)
            module, _, attr = resolved.rpartition(".")
            if attr in BLOCKING_MODULE_CALLS.get(module, ()):
                found.append((node.lineno, dotted))
                continue
            module, _, attr = dotted.rpartition(".")
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
    aliases = {}
    for path in WEB.rglob("*.py"):
        if "tests" in path.relative_to(WEB).parts:
            continue
        tree = _parse(path)
        file_aliases = _aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                defs.setdefault(node.name, []).append(node)
                aliases[id(node)] = file_aliases
    blocking = {
        name for name, nodes in defs.items() if any(_direct_blocking(n, aliases[id(n)]) for n in nodes)
    }
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
    for path in SCANNED:
        tree = _parse(path)
        file_aliases = _aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for lineno, what in _direct_blocking(node, file_aliases):
                out.append(f"{path.name}:{lineno} {node.name} calls {what}")
            local_defs = {
                n.name for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not node
            }
            local_defs |= {
                t.id for n in _own_nodes(node) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)
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


def test_scan_resolves_import_aliases():
    src = "\n".join(
        [
            "import httpx as _httpx",
            "from time import sleep",
            "async def aliased():",
            "    _httpx.post('https://example.invalid')",
            "async def bare():",
            "    sleep(1)",
            "async def clean():",
            "    await asyncio.sleep(1)",
        ]
    )
    tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
    aliases = _aliases(tree)
    assert _direct_blocking(funcs["aliased"], aliases)
    assert _direct_blocking(funcs["bare"], aliases)
    assert not _direct_blocking(funcs["clean"], aliases)


def test_scan_sees_token_fetches_model_calls_subprocesses_and_dict_dispatch():
    src = "\n".join(
        [
            "async def token():",
            "    skype_token, _ = _rc.get_auth()",
            "async def model():",
            "    provider.simple_complete('hi')",
            "async def run():",
            "    subprocess.run(['gh'])",
            "async def stop():",
            "    _ffmpeg_proc.wait(timeout=5)",
            "async def dispatch():",
            "    handler = TOOL_HANDLERS.get(name)",
            "    return handler(**args)",
            "async def clean():",
            "    await asyncio.to_thread(_rc.get_auth)",
            "    await asyncio.sleep(1)",
            "    await event.wait()",
        ]
    )
    tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body}
    for name in ("token", "model", "run", "stop", "dispatch"):
        assert _direct_blocking(funcs[name], _aliases(tree)), name
    assert not _direct_blocking(funcs["clean"], _aliases(tree))


def test_async_routes_do_not_block_the_event_loop():
    violations = _violations()
    assert not violations, (
        "async routes call blocking network code on the event loop (one slow Microsoft Graph call "
        "freezes the whole app). Make the route a plain `def`, or use `await asyncio.to_thread(...)`:\n  "
        + "\n  ".join(violations)
    )
