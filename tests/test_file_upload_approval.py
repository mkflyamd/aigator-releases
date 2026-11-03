from unittest.mock import MagicMock, patch

import pytest

from sandbox import approvals, task_grants
from skills._files import local_access
from skills.onedrive import tools as od

ARGS = {"dest_drive_id": "d2", "dest_folder_id": "f2"}


@pytest.fixture(autouse=True)
def _clean_state():
    approvals._reset()
    task_grants._reset()
    yield
    approvals._reset()
    task_grants._reset()


@pytest.fixture
def provider():
    p = MagicMock()
    p.upload.return_value = {"status": "uploaded", "web_url": "u"}
    folder = {"name": "Reports", "web_url": "https://contoso.sharepoint.com/Reports"}
    with patch.object(od, "_od_provider", return_value=p),             patch.object(od, "_tool_get_onedrive_item", return_value=folder):
        yield p


@pytest.fixture
def report(tmp_path):
    f = tmp_path / "report.docx"
    f.write_bytes(b"x")
    return f


def _upload(path, ctx="tab1"):
    return od.TOOL_HANDLERS["file_upload"](local_path=str(path), _context_id=ctx, **ARGS)


def test_a_file_the_user_never_approved_asks_first_and_is_not_read(report, provider):
    out = _upload(report)
    assert out["approval_required"] is True
    assert out["_sandbox_approval"]["tool"] == "file_upload"
    assert out["_sandbox_approval"]["read_paths"] == [str(report.resolve())]
    assert out["_sandbox_approval"]["write_paths"] == []
    provider.upload.assert_not_called()


def test_the_same_call_uploads_once_the_user_allowed_it(report, provider):
    req_id = _upload(report)["request_id"]
    approvals.decide(req_id, "tab1", True, scope="once")
    assert _upload(report)["status"] == "uploaded"
    provider.upload.assert_called_once()
    assert _upload(report)["approval_required"] is True  # a once-approval is used up


def test_a_denied_request_is_not_retried_into_an_upload(report, provider):
    req_id = _upload(report)["request_id"]
    approvals.decide(req_id, "tab1", False)
    out = _upload(report)
    assert "denied" in out["error"] and "approval_required" not in out
    provider.upload.assert_not_called()


def test_an_upload_approval_cannot_be_widened_to_the_tab(report, provider):
    req_id = _upload(report)["request_id"]
    assert approvals.decide(req_id, "tab1", True, scope="task").scope == "once"
    assert _upload(report)["status"] == "uploaded"
    assert task_grants.covers("tab1", [str(report.resolve())], [], []) is False


def test_a_code_run_grant_does_not_stand_in_for_an_upload_approval(report, provider):
    task_grants.add("tab1", [str(report.resolve().parent)], [], [])
    assert _upload(report)["approval_required"] is True
    provider.upload.assert_not_called()


def test_an_approval_holds_only_for_the_destination_it_was_shown(report, provider):
    req_id = _upload(report)["request_id"]
    approvals.decide(req_id, "tab1", True)
    other = od.TOOL_HANDLERS["file_upload"](
        local_path=str(report), _context_id="tab1", dest_drive_id="d2", dest_folder_id="elsewhere")
    assert other["approval_required"] is True
    provider.upload.assert_not_called()
    assert _upload(report)["status"] == "uploaded"


def test_the_card_names_the_destination_folder(report, provider):
    folder = {"name": "Reports 2026", "web_url": "https://contoso.sharepoint.com/Reports%202026"}
    with patch.object(od, "_tool_get_onedrive_item", return_value=folder):
        card = _upload(report)["_sandbox_approval"]
    assert card["destination"] == "Reports 2026 - https://contoso.sharepoint.com/Reports%202026"


def test_no_approval_is_requested_when_the_destination_cannot_be_identified(report, provider):
    with patch.object(od, "_tool_get_onedrive_item", return_value={"error": "boom"}):
        out = _upload(report)
    assert "destination" in out["error"] and "approval_required" not in out
    assert approvals.lookup("tab1", [str(report.resolve())], [], [], tool="file_upload", command="d2/f2")[1] is None
    provider.upload.assert_not_called()


def test_the_upload_reads_the_path_that_was_checked(tmp_path, provider):
    real = tmp_path / "real.docx"
    real.write_bytes(b"x")
    link = tmp_path / "link.docx"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlinks are not available here")
    approvals.decide(_upload(link)["request_id"], "tab1", True)
    assert _upload(link)["status"] == "uploaded"
    assert provider.upload.call_args.args[0] == str(real.resolve())
    assert provider.upload.call_args.args[2] == "link.docx"


def test_an_approval_in_one_tab_does_not_apply_to_another(report, provider):
    req_id = _upload(report, ctx="tab1")["request_id"]
    approvals.decide(req_id, "tab1", True)
    assert _upload(report, ctx="tab2")["approval_required"] is True
    provider.upload.assert_not_called()


def test_files_under_the_ai_gator_outputs_folder_need_no_approval(tmp_path, provider, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    made = outputs / "run1" / "summary.docx"
    made.parent.mkdir()
    made.write_bytes(b"x")
    monkeypatch.setattr(local_access, "OUTPUTS_DIR", outputs)
    assert _upload(made)["status"] == "uploaded"


def test_a_missing_file_is_left_to_the_tool_to_report(tmp_path, provider):
    provider.upload.return_value = {"error": "not found", "error_code": "not_found"}
    assert _upload(tmp_path / "gone.docx")["error_code"] == "not_found"
