"""Truncated tool output must stay navigable and GitHub PR reads must be complete and bounded."""

import json
from unittest.mock import patch

import pytest

import tool_result_truncation as trunc
from skills.file_ops.tools import TOOL_DEFS, _tool_grep_files, _tool_read_file
from skills.github import api as gh_api
from skills.github import tools as gh_tools

BUDGET = trunc.MAX_TOOL_RESULT_BYTES


def _size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


# ── read_file paging ─────────────────────────────────────────────────────────


def test_read_file_offset_limit_returns_requested_lines(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("\n".join(f"line {i}" for i in range(1, 1001)), encoding="utf-8")
    r = _tool_read_file(path=str(f), offset=10, limit=5)
    assert r["content"].splitlines() == [f"line {i}" for i in range(10, 15)]
    assert r["start_line"] == 10
    assert r["end_line"] == 14
    assert r["total_lines"] == 1000
    assert r["next_offset"] == 15


def test_read_file_last_page_has_no_next_offset(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("a\nb\nc", encoding="utf-8")
    r = _tool_read_file(path=str(f), offset=2, limit=50)
    assert r["content"].splitlines() == ["b", "c"]
    assert "next_offset" not in r


def test_read_file_page_is_byte_capped_and_resumable(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("\n".join("x" * 99 for _ in range(2000)), encoding="utf-8")
    r = _tool_read_file(path=str(f), offset=1, limit=2000)
    assert _size(r) < BUDGET
    assert r["next_offset"] == r["end_line"] + 1


def test_read_file_single_huge_line_is_cut_not_dropped(tmp_path):
    f = tmp_path / "one.json"
    f.write_text("y" * 200_000, encoding="utf-8")
    r = _tool_read_file(path=str(f), offset=1, limit=10)
    assert _size(r) < BUDGET
    assert r["content"].startswith("yyy")
    assert r["line_truncated"] is True


def test_read_file_without_paging_args_is_unchanged(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    assert _tool_read_file(path=str(f))["content"] == "hello"


def test_read_file_schema_advertises_paging():
    props = next(t for t in TOOL_DEFS if t["name"] == "read_file")["input_schema"]["properties"]
    assert "offset" in props and "limit" in props


# ── grep_files output bounds ─────────────────────────────────────────────────


def test_grep_long_line_is_windowed_around_the_match(tmp_path):
    f = tmp_path / "one.json"
    f.write_text("a" * 100_000 + "NEEDLE" + "b" * 100_000, encoding="utf-8")
    r = _tool_grep_files(pattern="NEEDLE", path=str(f))
    assert r["count"] == 1
    m = r["matches"][0]
    assert "NEEDLE" in m["line"]
    assert len(m["line"]) < 1000
    assert m["line_truncated"] is True
    assert _size(r) < BUDGET


def test_grep_total_bytes_are_capped(tmp_path):
    f = tmp_path / "many.txt"
    f.write_text("\n".join("hit " + "z" * 400 for _ in range(100)), encoding="utf-8")
    r = _tool_grep_files(pattern="hit", path=str(f))
    assert _size(r) < BUDGET
    assert r["truncated"] is True


def test_grep_short_lines_unchanged(tmp_path):
    f = tmp_path / "s.txt"
    f.write_text("def hello():\n    pass\n", encoding="utf-8")
    m = _tool_grep_files(pattern="def hello", path=str(f))["matches"][0]
    assert m["line"] == "def hello():"
    assert "line_truncated" not in m


# ── overflow file is navigable end to end ────────────────────────────────────


def test_overflowed_dict_result_can_be_searched(tmp_path, monkeypatch):
    monkeypatch.setattr(trunc, "_outputs_dir", lambda: tmp_path)
    result = {
        "files": [{"filename": f"f{i}.py", "additions": i, "patch": "p" * 200} for i in range(600)],
        "merged_at": "2026-10-01T14:33:26Z",
    }
    stub = trunc.truncate_tool_result(result, tool_name="github_get_pr")
    text = stub["result"]
    path = next(l for l in text.splitlines() if l.startswith("Full output saved to:")).split(": ", 1)[1]

    found = _tool_grep_files(pattern="merged_at", path=path)
    assert found["count"] == 1
    assert "2026-10-01" in found["matches"][0]["line"]
    assert _size(found) < BUDGET

    page = _tool_read_file(path=path, offset=1, limit=40)
    assert _size(page) < BUDGET
    assert page["total_lines"] > 40


def test_stub_hint_mentions_paging_args_that_exist():
    assert {"offset", "limit"} <= set(
        next(t for t in TOOL_DEFS if t["name"] == "read_file")["input_schema"]["properties"]
    )


# ── GitHub REST mapping ──────────────────────────────────────────────────────


def test_pr_get_comments_reads_the_conversation_not_inline_comments():
    calls = []

    def fake(path, *a, **k):
        calls.append(path)
        return []

    with patch.object(gh_api, "_rest", fake):
        gh_api._rest_tool(
            "pull_request_read",
            {"method": "get_comments", "owner": "o", "repo": "r", "pullNumber": 7},
        )
        gh_api._rest_tool(
            "pull_request_read",
            {"method": "get_review_comments", "owner": "o", "repo": "r", "pullNumber": 7},
        )
    assert calls[0].startswith("/repos/o/r/issues/7/comments")
    assert calls[1].startswith("/repos/o/r/pulls/7/comments")


def test_pr_lists_are_paginated():
    pages = {1: [{"filename": f"a{i}"} for i in range(100)], 2: [{"filename": "last"}]}

    def fake(path, *a, **k):
        assert "per_page=100" in path
        page = int(path.split("&page=")[1])
        return pages.get(page, [])

    with patch.object(gh_api, "_rest", fake):
        out = gh_api._rest_tool(
            "pull_request_read",
            {"method": "get_files", "owner": "o", "repo": "r", "pullNumber": 7},
        )
    assert len(out["files"]) == 101


# ── github_get_pr result shape ───────────────────────────────────────────────


def _fake_pr_api(tool_name, inputs):
    method = inputs["method"]
    if method == "get":
        return {
            "number": 7,
            "title": "T",
            "state": "closed",
            "merged": True,
            "merged_at": "2026-10-01T14:33:27Z",
            "closed_at": "2026-10-01T14:33:27Z",
            "draft": False,
            "html_url": "https://github.com/o/r/pull/7",
            "created_at": "2026-09-13T00:00:00Z",
            "user": {"login": "author", "id": 1, "avatar_url": "x" * 300},
            "base": {"ref": "main", "repo": {"huge": "r" * 5000}},
            "head": {"ref": "feature", "repo": {"huge": "r" * 5000}},
            "labels": [{"name": "Merged", "color": "abc", "description": "d" * 300}],
            "body": "B" * 10_000,
            "additions": 5,
            "deletions": 2,
            "changed_files": 3,
            "_links": {"self": "x" * 3000},
        }
    if method == "get_reviews":
        return {"reviews": [{"user": {"login": "rev", "id": 2}, "state": "APPROVED", "body": "R" * 5000}]}
    if method == "get_check_runs":
        return {"check_runs": [{"name": "build", "conclusion": "success", "status": "completed", "output": {"x": "o" * 3000}}]}
    if method == "get_comments":
        return {
            "comments": [
                {"user": {"login": f"u{i}", "id": i}, "created_at": "2026-09-20T00:00:00Z", "body": "C" * 6000}
                for i in range(60)
            ]
        }
    if method == "get_review_comments":
        return {"comments": [{"user": {"login": "x"}, "path": "a.py", "body": "inline"}]}
    if method == "get_files":
        return {"files": [{"filename": f"f{i}.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "d" * 3000} for i in range(150)]}
    raise AssertionError(method)


@pytest.fixture
def pr():
    with patch.object(gh_tools, "github_api", _fake_pr_api):
        return gh_tools._github_get_pr("o", "r", 7)


def test_pr_result_reports_merge_state(pr):
    assert pr["merged"] is True
    assert pr["merged_at"] == "2026-10-01T14:33:27Z"
    assert pr["state"] == "closed"
    assert [l["name"] for l in pr["labels"]] == ["Merged"]


def test_pr_result_keeps_fields_the_pane_reads(pr):
    for key in ("number", "title", "state", "draft", "html_url", "created_at", "additions", "deletions", "changed_files"):
        assert key in pr
    assert pr["user"]["login"] == "author"
    assert pr["base"]["ref"] == "main" and pr["head"]["ref"] == "feature"
    assert pr["labels"][0]["color"] == "abc"
    assert pr["checks"][0]["name"] == "build" and pr["checks"][0]["conclusion"] == "success"
    assert pr["reviews"][0]["user"]["login"] == "rev" and pr["reviews"][0]["state"] == "APPROVED"
    assert {"user", "created_at", "body"} <= set(pr["comments"][0])


def test_pr_result_drops_bulk_and_caps_text(pr):
    assert "_links" not in pr
    assert all("patch" not in f for f in pr["files_changed"])
    assert len(pr["body"]) < 2500
    assert all(len(c["body"]) < 1700 for c in pr["comments"])
    assert len(pr["files_changed"]) == 100 and pr["files_changed_total"] == 150
    assert len(pr["comments"]) == 30 and pr["comments_total"] == 60
    assert len(pr["review_comments"]) == 1


def test_pr_result_keeps_the_latest_comments(pr):
    assert pr["comments"][-1]["user"]["login"] == "u59"


def test_pr_result_leads_with_status_so_the_inline_preview_shows_it(pr):
    head = list(pr)[:8]
    assert {"state", "merged", "merged_at", "labels"} <= set(head)


def test_pr_result_is_much_smaller_than_the_raw_payload(pr):
    assert _size(pr) < 100_000
