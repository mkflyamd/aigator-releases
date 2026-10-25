"""The create tools save into a folder that does not exist yet instead of failing with ENOENT."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import app  # noqa: E402,F401
from skills.docx import tools as docx_tools  # noqa: E402
from skills.excel import tools as excel_tools  # noqa: E402
from skills.ppt import tools as ppt_tools  # noqa: E402


def test_create_pptx_makes_the_folder(tmp_path):
    target = tmp_path / "new_run" / "deck.pptx"
    out = ppt_tools._tool_create_pptx(str(target), [{"layout": "title_only", "title": "Hi"}])
    assert out.get("ok") and target.is_file(), out


def test_create_docx_makes_the_folder(tmp_path):
    target = tmp_path / "new_run" / "doc.docx"
    out = docx_tools._tool_create_docx(str(target), [{"type": "paragraph", "text": "Hi"}])
    assert not out.get("error") and target.is_file(), out


def test_create_excel_makes_the_folder(tmp_path):
    target = tmp_path / "new_run" / "book.xlsx"
    out = excel_tools._tool_create_excel(str(target), [{"name": "S", "rows": [["a", 1]]}])
    assert not out.get("error") and target.is_file(), out
