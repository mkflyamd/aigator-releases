"""Issue #161: File-routing primitives — Teams attachment resolution and
cross-drive file move/copy.

Tests verify:
  - TOOL_DEFS exports the five expected tool names
  - TOOL_HANDLERS maps each tool to a callable
  - Tool input_schema have the required fields documented in the issue
  - drive_id parameter exists on read_onedrive_file and list_onedrive_files
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import importlib.util


def _load_tools():
    spec = importlib.util.spec_from_file_location(
        "onedrive_tools",
        str(pathlib.Path(__file__).parent.parent / "web" / "skills" / "onedrive" / "tools.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_new_tool_defs_present():
    mod = _load_tools()
    names = {t["name"] for t in mod.TOOL_DEFS}
    assert "resolve_teams_attachment" in names, "resolve_teams_attachment tool missing"
    assert "move_onedrive_file" in names, "move_onedrive_file tool missing"
    assert "copy_onedrive_file" in names, "copy_onedrive_file tool missing"
    assert "get_onedrive_item" in names, "get_onedrive_item tool missing"


def test_new_tool_handlers_callable():
    mod = _load_tools()
    for name in ("resolve_teams_attachment", "move_onedrive_file",
                 "copy_onedrive_file", "get_onedrive_item"):
        assert name in mod.TOOL_HANDLERS, f"TOOL_HANDLERS missing {name}"
        assert callable(mod.TOOL_HANDLERS[name]), f"{name} handler not callable"


def test_resolve_teams_attachment_schema():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "resolve_teams_attachment")
    props = tool["input_schema"]["properties"]
    required = tool["input_schema"].get("required", [])
    assert "chat_id" in props
    assert "message_id" in props
    assert "chat_id" in required
    assert "message_id" in required


def test_move_onedrive_file_schema():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "move_onedrive_file")
    props = tool["input_schema"]["properties"]
    required = tool["input_schema"].get("required", [])
    for field in ("source_drive_id", "source_item_id", "dest_drive_id", "dest_folder_id"):
        assert field in props, f"move_onedrive_file missing prop {field}"
        assert field in required, f"move_onedrive_file {field} not required"


def test_copy_onedrive_file_schema():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "copy_onedrive_file")
    props = tool["input_schema"]["properties"]
    required = tool["input_schema"].get("required", [])
    for field in ("source_drive_id", "source_item_id", "dest_drive_id", "dest_folder_id"):
        assert field in props, f"copy_onedrive_file missing prop {field}"
        assert field in required, f"copy_onedrive_file {field} not required"
    assert "new_name" in props, "copy_onedrive_file missing optional new_name"


def test_get_onedrive_item_schema():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "get_onedrive_item")
    props = tool["input_schema"]["properties"]
    required = tool["input_schema"].get("required", [])
    assert "drive_id" in props
    assert "item_id" in props
    assert "drive_id" in required
    assert "item_id" in required


def test_read_onedrive_file_accepts_drive_id():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "read_onedrive_file")
    props = tool["input_schema"]["properties"]
    assert "drive_id" in props, "read_onedrive_file missing drive_id param"


def test_list_onedrive_files_accepts_drive_id():
    mod = _load_tools()
    tool = next(t for t in mod.TOOL_DEFS if t["name"] == "list_onedrive_files")
    props = tool["input_schema"]["properties"]
    assert "drive_id" in props, "list_onedrive_files missing drive_id param"
