import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from pathlib import Path

import proc_utils as p


def test_reports_new_document_file(tmp_path):
    dirs = [tmp_path]
    before = p.snapshot_outputs(dirs)
    (tmp_path / "deck.pptx").write_bytes(b"PK fake")
    changed = p.diff_outputs(before, dirs)
    assert [c["path"] for c in changed] == [str(tmp_path / "deck.pptx")]
    assert changed[0]["mime_type"].endswith("presentationml.presentation")


def test_ignores_non_reportable_extensions(tmp_path):
    dirs = [tmp_path]
    before = p.snapshot_outputs(dirs)
    (tmp_path / "notes.txt").write_text("ignore me")
    (tmp_path / "script.py").write_text("print(1)")
    assert p.diff_outputs(before, dirs) == []


def test_unchanged_files_not_reported(tmp_path):
    (tmp_path / "old.pdf").write_bytes(b"%PDF-1.4")
    dirs = [tmp_path]
    before = p.snapshot_outputs(dirs)
    # no change since `before`
    assert p.diff_outputs(before, dirs) == []


def test_modified_file_is_reported(tmp_path):
    f = tmp_path / "report.xlsx"
    f.write_bytes(b"PK one")
    dirs = [tmp_path]
    before = p.snapshot_outputs(dirs)
    # bump mtime via an actual content change
    import os, time
    os.utime(f, ns=(time.time_ns(), time.time_ns() + 1_000_000_000))
    changed = p.diff_outputs(before, dirs)
    assert [c["path"] for c in changed] == [str(f)]


def test_skips_heavy_dirs(tmp_path):
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    dirs = [tmp_path]
    before = p.snapshot_outputs(dirs)
    (nm / "bundled.pdf").write_bytes(b"%PDF")
    # a file buried in node_modules must not be reported
    assert p.diff_outputs(before, dirs) == []


def test_watched_dirs_includes_cwd_and_dedups(tmp_path):
    dirs = p.watched_output_dirs(str(tmp_path))
    norm = {str(d).lower() for d in dirs}
    assert str(tmp_path.resolve()).lower() in norm
    # no duplicates
    assert len(norm) == len(dirs)
