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

    with patch.object(updater_mod, "VERSION_FILE", version_file):
        import web.routes.health as health_mod

        importlib.reload(health_mod)
        assert health_mod.APP_VERSION == "2.3.4"


def test_app_version_fallback_when_missing(tmp_path):
    import updater as updater_mod

    with patch.object(updater_mod, "VERSION_FILE", tmp_path / "nonexistent.txt"):
        import web.routes.health as health_mod

        importlib.reload(health_mod)
        assert health_mod.APP_VERSION == "0.0.0"


def test_frozen_version_file_uses_pyinstaller_resources(tmp_path):
    version_file = tmp_path / "version.txt"
    version_file.write_text("4.5.6", encoding="utf-8")

    with patch.object(sys, "frozen", True, create=True), patch.object(
        sys, "_MEIPASS", str(tmp_path), create=True
    ):
        import updater as updater_mod

        importlib.reload(updater_mod)
        assert updater_mod.VERSION_FILE == version_file
        assert updater_mod.get_current_version() == "4.5.6"

    importlib.reload(updater_mod)
