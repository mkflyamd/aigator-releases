import zipfile
import io

import pytest

from marketplace import installer
from marketplace.permissions import files_digest
from skills._sharing import bundle
from skills._sharing.errors import ShareError

SKILL_MD = b"---\nname: Weekly Report\ndescription: Summarise the week\n---\n\n# Weekly Report\n"


def test_zip_is_deterministic_regardless_of_dict_order():
    a = {"SKILL.md": SKILL_MD, "notes/ref.md": b"ref"}
    b = {"notes/ref.md": b"ref", "SKILL.md": SKILL_MD}
    assert bundle.build_zip(a) == bundle.build_zip(b)


def test_zip_round_trips_through_the_installer_reader():
    files = {"SKILL.md": SKILL_MD, "notes/ref.md": b"ref"}
    out = installer.preview_package(local_zip_bytes=bundle.build_zip(files))
    assert out["ok"] is True
    assert out["files"] == files


def test_zip_entries_use_fixed_timestamp_and_mode():
    data = bundle.build_zip({"SKILL.md": SKILL_MD})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        info = zf.getinfo("SKILL.md")
    assert info.date_time == (1980, 1, 1, 0, 0, 0)
    assert info.compress_type == zipfile.ZIP_STORED
    assert info.external_attr >> 16 == 0o644


def test_bundle_sha256_is_hex_sha256():
    assert bundle.bundle_sha256(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@pytest.mark.parametrize(
    "paths, expected",
    [
        (["SKILL.md"], False),
        (["SKILL.md", "reference/notes.md"], False),
        (["SKILL.md", "tools.py"], True),
        (["SKILL.md", "scripts/run.sh"], True),
        (["SKILL.md", "bin/tool"], True),
        (["SKILL.md", "helper.ps1"], True),
    ],
)
def test_has_scripts(paths, expected):
    assert bundle.has_scripts({p: b"x" for p in paths}) is expected


def test_read_skill_dir_reads_files_and_skips_junk(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_bytes(SKILL_MD)
    (skill / "notes").mkdir()
    (skill / "notes" / "ref.md").write_bytes(b"ref")
    (skill / "__pycache__").mkdir()
    (skill / "__pycache__" / "x.pyc").write_bytes(b"junk")
    (skill / ".git").mkdir()
    (skill / ".git" / "HEAD").write_bytes(b"ref")
    assert bundle.read_skill_dir(skill) == {"SKILL.md": SKILL_MD, "notes/ref.md": b"ref"}


def test_read_skill_dir_skips_symlinks(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_bytes(SKILL_MD)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    try:
        (skill / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks need privileges on this machine")
    assert "link.txt" not in bundle.read_skill_dir(skill)


def test_read_skill_dir_requires_skill_md(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "notes.md").write_bytes(b"x")
    with pytest.raises(ShareError) as err:
        bundle.read_skill_dir(skill)
    assert err.value.code == "invalid"


def test_read_skill_dir_refuses_oversized_skill(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    skill.mkdir()
    monkeypatch.setattr("marketplace.github_fetcher.MAX_TOTAL_BYTES", 10)
    (skill / "SKILL.md").write_bytes(SKILL_MD)
    with pytest.raises(ShareError) as err:
        bundle.read_skill_dir(skill)
    assert err.value.code == "too_large"


def test_build_manifest_records_digests_and_recomputable_facts():
    files = {"SKILL.md": SKILL_MD, "tools.py": b"x = 1\n"}
    zip_bytes = bundle.build_zip(files)
    manifest = bundle.build_manifest(
        "weekly-report", 2, files, zip_bytes, author="Mayuresh Kulkarni", created_at="2026-11-16T10:00:00Z"
    )
    assert manifest == {
        "schema": 1,
        "name": "weekly-report",
        "title": "Weekly Report",
        "description": "Summarise the week",
        "version": 2,
        "author": "Mayuresh Kulkarni",
        "created_at": "2026-11-16T10:00:00Z",
        "bundle": "bundle.zip",
        "bundle_sha256": bundle.bundle_sha256(zip_bytes),
        "files_digest": files_digest(files),
        "has_scripts": True,
        "requested_tools": {"filesystem": [], "network": [], "invalid": False},
    }
