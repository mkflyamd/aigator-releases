"""Loads the per-extension-type scoped system prompt."""
from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(extension_type: str) -> str:
    path = _DIR / f"{extension_type}.md"
    if not path.exists():
        raise FileNotFoundError(f"No prompt for extension_type={extension_type!r}")
    return path.read_text(encoding="utf-8")
