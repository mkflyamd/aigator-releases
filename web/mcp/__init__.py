# Extend __path__ so that `from mcp.client.*` and `from mcp.shared.*` resolve
# to the installed MCP Python SDK, not this local package.  The SDK directory is
# appended (not prepended) so local modules like generic_client and manager still
# take precedence over any SDK module with the same name.
import pathlib as _pathlib
import sys as _sys

def _find_sdk_mcp_dir():
    _this_dir = _pathlib.Path(__file__).parent.resolve()
    for _entry in _sys.path:
        if not _entry:
            continue
        _p = _pathlib.Path(_entry).resolve() / "mcp"
        if _p.is_dir() and _p != _this_dir and (_p / "__init__.py").exists():
            return str(_p)
    return None

_sdk_mcp = _find_sdk_mcp_dir()
if _sdk_mcp and _sdk_mcp not in __path__:
    __path__.append(_sdk_mcp)

del _pathlib, _sys, _find_sdk_mcp_dir, _sdk_mcp
