"""Per-provider OAuth storage — provider config + token cache as JSON under
~/.config/aigator/oauth/{provider_id}.json. Restrictive perms on POSIX."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

_DIR = Path.home() / ".config" / "aigator" / "oauth"
# Reentrant — update_token holds the lock while calling save() which re-enters.
_LOCK = threading.RLock()
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _file_for(provider_id: str) -> Path:
    if not _SAFE_ID.match(provider_id):
        raise ValueError(f"invalid provider id: {provider_id!r}")
    return _DIR / f"{provider_id}.json"


def load(provider_id: str) -> dict:
    path = _file_for(provider_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save(provider_id: str, data: dict) -> None:
    path = _file_for(provider_id)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            # chmod BEFORE replace — otherwise the file briefly exists at the final
            # path under the umask-derived mode (e.g. 0o644) before chmod runs.
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass  # Windows — ACLs apply instead
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def delete(provider_id: str) -> None:
    path = _file_for(provider_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def update_token(provider_id: str, token: dict) -> None:
    """Merge a token block into the stored provider record under key 'token'."""
    with _LOCK:
        data = load(provider_id)
        data["token"] = token
        save(provider_id, data)
