from pathlib import Path
from unittest.mock import patch
import importlib
import sys


def test_app_version_reads_version_txt(tmp_path):
    version_file = tmp_path / "version.txt"
    version_file.write_text("2.3.4")

    # health.py does `import updater` (bare name, resolved via web/ on sys.path).
    # We must patch the same module object that health.py references.
    import updater as updater_mod
    with patch.object(updater_mod, 'VERSION_FILE', version_file):
        import web.routes.health as health_mod
        importlib.reload(health_mod)
        assert health_mod.APP_VERSION == "2.3.4"


def test_app_version_fallback_when_missing(tmp_path):
    import updater as updater_mod
    with patch.object(updater_mod, 'VERSION_FILE', tmp_path / "nonexistent.txt"):
        import web.routes.health as health_mod
        importlib.reload(health_mod)
        assert health_mod.APP_VERSION == "0.0.0"
