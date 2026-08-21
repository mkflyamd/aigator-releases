import pathlib
import sys
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from routes import utils


def test_native_dialog_warmup_is_skipped_outside_windows(monkeypatch):
    monkeypatch.setattr(utils.sys, "platform", "linux")

    with patch.dict(sys.modules, {"tkinter": None}):
        utils.warmup_native_dialogs()
