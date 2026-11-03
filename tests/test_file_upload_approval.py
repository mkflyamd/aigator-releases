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
    with patch.object(od, "_od_provider", return_value=p):
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


def test_allow_for_this_tab_covers_later_uploads_of_that_file(report, provider):
    req_id = _upload(report)["request_id"]
    approvals.decide(req_id, "tab1", True, scope="task")
    task_grants.add("tab1", [str(report.resolve())], [], [])
    assert _upload(report)["status"] == "uploaded"
    assert _upload(report)["status"] == "uploaded"


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
