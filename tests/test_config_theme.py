import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web"))


def test_theme_is_patchable():
    from config import PATCHABLE_CONFIG_KEYS
    assert "theme" in PATCHABLE_CONFIG_KEYS


def test_unknown_key_not_patchable():
    from config import PATCHABLE_CONFIG_KEYS
    assert "colour_scheme" not in PATCHABLE_CONFIG_KEYS
