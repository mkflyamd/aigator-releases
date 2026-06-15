"""Thin wrapper -- delegates to the canonical GraphClient in skills/m365-email/."""
import importlib.util
from pathlib import Path

_canonical = Path(__file__).parent.parent.parent / "m365-email" / "graph_client.py"
_spec = importlib.util.spec_from_file_location("_gc_canonical", str(_canonical))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

GraphClient = _mod.GraphClient
GRAPH_BASE = _mod.GRAPH_BASE
DEFAULT_CLIENT_ID = _mod.DEFAULT_CLIENT_ID
DEFAULT_SCOPES = _mod.DEFAULT_SCOPES
TOKEN_FILE = _mod.TOKEN_FILE
