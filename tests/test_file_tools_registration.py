from pathlib import Path
from unittest.mock import MagicMock, patch

from skills.onedrive import tools as od

SKILLS = Path(__file__).resolve().parent.parent / "web" / "skills"


def _def(name):
    return next(t for t in od.TOOL_DEFS if t["name"] == name)


def test_new_tools_are_registered_everywhere():
    for name in ("file_transfer", "file_upload"):
        assert name in {t["name"] for t in od.TOOL_DEFS}
        assert callable(od.TOOL_HANDLERS[name])
        assert od.TOOL_STATUS[name]


def test_file_transfer_schema():
    s = _def("file_transfer")["input_schema"]
    assert set(s["required"]) == {"source_drive_id", "source_item_id", "dest_drive_id", "dest_folder_id"}
    assert s["properties"]["mode"]["enum"] == ["move", "copy"]
    assert "new_name" in s["properties"]


def test_file_upload_schema():
    s = _def("file_upload")["input_schema"]
    assert set(s["required"]) == {"local_path", "dest_drive_id", "dest_folder_id"}
    assert "name" in s["properties"]
    assert "on_conflict" not in s["properties"]


def test_existing_tools_still_registered():
    names = {t["name"] for t in od.TOOL_DEFS}
    for n in ("read_onedrive_file", "list_onedrive_files", "search_onedrive_files", "download_onedrive_file",
              "resolve_teams_attachment", "move_onedrive_file", "copy_onedrive_file", "get_onedrive_item"):
        assert n in names and n in od.TOOL_HANDLERS


def test_no_delete_tool_exists():
    assert not [t["name"] for t in od.TOOL_DEFS if "delete" in t["name"].lower() or "remove" in t["name"].lower()]


def test_file_transfer_handler_moves_through_the_provider():
    gc = MagicMock()
    gc.get.side_effect = lambda path, params=None, **kw: (
        {"id": "mine"} if path == "/me/drive" else {"id": "mine", "driveType": "business"}
    )
    moved = {"item_id": "i1", "drive_id": "d2", "name": "a.docx", "web_url": "u"}
    with patch("skills._m365.helpers.get_skill_client", return_value=gc), \
         patch.object(od, "_tool_get_onedrive_item", return_value={"item_id": "i1", "drive_id": "mine", "name": "a.docx", "size": 1, "web_url": "u0"}), \
         patch.object(od, "_tool_move_onedrive_file", return_value=moved):
        out = od.TOOL_HANDLERS["file_transfer"](
            source_drive_id="mine", source_item_id="i1", dest_drive_id="d2", dest_folder_id="f2")
    assert out["status"] == "moved" and out["method"] == "native_move" and out["original_remains"] is False


def test_file_transfer_rejects_unknown_mode():
    out = od.TOOL_HANDLERS["file_transfer"](
        source_drive_id="d1", source_item_id="i1", dest_drive_id="d2", dest_folder_id="f2", mode="delete")
    assert out["status"] == "failed"


def test_file_upload_missing_local_file_is_a_clean_error(tmp_path):
    with patch("skills._m365.helpers.get_skill_client", return_value=MagicMock()):
        out = od.TOOL_HANDLERS["file_upload"](
            local_path=str(tmp_path / "missing.docx"), dest_drive_id="d2", dest_folder_id="f2")
    assert out["error_code"] == "not_found" and out["error"]


def test_skill_guide_covers_move_copy_lock_and_upload():
    text = (SKILLS / "onedrive" / "SKILL.md").read_text(encoding="utf-8")
    for needle in ("file_transfer", "file_upload", "original_remains", "resolve_teams_attachment", "never deletes", "dest.web_url"):
        assert needle in text, needle
    assert "file_transfer" in (SKILLS / "m365-onedrive" / "SKILL.md").read_text(encoding="utf-8")
