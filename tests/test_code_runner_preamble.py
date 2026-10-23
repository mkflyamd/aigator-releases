"""A model-written script can import python-pptx as its first line."""

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from skills.code_runner.tools import _PREAMBLE_IMPORTS  # noqa: E402


def _run(code):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)


def test_pptx_imports_in_a_fresh_interpreter_after_the_preamble():
    assert _run(f"{_PREAMBLE_IMPORTS}\nimport pptx").returncode == 0


def test_the_preamble_stays_on_one_line():
    assert "\n" not in _PREAMBLE_IMPORTS
