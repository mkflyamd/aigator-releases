import json
from pathlib import Path

from marketplace import permissions as P


def _skill_md(front: str) -> bytes:
    return f"---\nname: demo\ndescription: d\n{front}---\nBody\n".encode()


def test_missing_block_means_nothing_declared():
    perms = P.declared_permissions({"SKILL.md": _skill_md("")})
    assert perms == P.Permissions()
    assert not perms.wants_network


def test_valid_block_in_frontmatter():
    front = "permissions:\n  filesystem: ['~/Documents/reports']\n  network: ['api.example.com']\n"
    perms = P.declared_permissions({"SKILL.md": _skill_md(front)})
    assert perms.filesystem == ("~/Documents/reports",)
    assert perms.network == ("api.example.com",)
    assert perms.wants_network


def test_plugin_json_wins_over_skill_md():
    files = {
        ".claude-plugin/plugin.json": json.dumps({"permissions": {"network": ["a.example.com"]}}).encode(),
        "skills/x/SKILL.md": _skill_md("permissions:\n  network: ['b.example.com']\n"),
    }
    assert P.declared_permissions(files).network == ("a.example.com",)


def test_union_across_skill_md_files_is_deduped():
    files = {
        "skills/a/SKILL.md": _skill_md("permissions:\n  network: ['a.example.com']\n"),
        "skills/b/SKILL.md": _skill_md("permissions:\n  network: ['a.example.com', 'b.example.com']\n"),
    }
    assert P.declared_permissions(files).network == ("a.example.com", "b.example.com")


def test_malformed_blocks_are_invalid_and_grant_nothing():
    for bad in (
        "permissions: yes\n",
        "permissions:\n  network: 'api.example.com'\n",
        "permissions:\n  network: [1]\n",
        "permissions:\n  network: ['']\n",
        "permissions:\n  network: ['" + "a" * 201 + "']\n",
        "permissions:\n  network: [" + ",".join(f"'h{i}'" for i in range(21)) + "]\n",
    ):
        perms = P.declared_permissions({"SKILL.md": _skill_md(bad)})
        assert perms.invalid, bad
        assert not perms.wants_network
        assert P.readable_paths(perms) == []


def test_one_invalid_skill_makes_the_package_invalid():
    files = {
        "skills/a/SKILL.md": _skill_md("permissions:\n  network: ['a.example.com']\n"),
        "skills/b/SKILL.md": _skill_md("permissions: yes\n"),
    }
    assert P.declared_permissions(files).invalid


def test_to_dict_from_dict_round_trip_and_bad_stored_data():
    perms = P.Permissions(filesystem=("~/x",), network=("h.example.com",))
    assert P.Permissions.from_dict(perms.to_dict()) == perms
    assert P.Permissions.from_dict(None) == P.Permissions()
    assert P.Permissions.from_dict({"network": "nope"}).invalid


def test_digest_is_stable_and_content_sensitive():
    a = {"SKILL.md": b"one", "tools.py": b"two"}
    assert P.files_digest(a) == P.files_digest(dict(reversed(list(a.items()))))
    assert P.files_digest(a) != P.files_digest({"SKILL.md": b"one", "tools.py": b"changed"})
    assert P.files_digest(a) != P.files_digest({"SKILL.md": b"one"})


def test_summary_for_a_plain_skill_with_nothing():
    summary = P.summarize_package({"SKILL.md": _skill_md("")})
    assert summary["has_tools"] is False
    assert summary["hooks"] == [] and summary["bin"] == [] and summary["mcp_servers"] == []
    text = "\n".join(summary["lines"])
    assert "none declared" in text
    assert summary["digest"] == P.files_digest({"SKILL.md": _skill_md("")})


def test_summary_names_tools_hooks_bin_and_mcp(monkeypatch):
    from marketplace import installer

    monkeypatch.setattr(installer, "_discover_plugin_mcp_manifest_from_files",
                        lambda files: {"srv": {"command": "npx", "args": ["x"]}})
    files = {
        "SKILL.md": _skill_md("permissions:\n  network: ['api.example.com']\n"),
        "tools.py": b"TOOL_DEFS = []\n",
        "hooks.json": json.dumps({"hooks": [{"event": "pre_email_send", "command": "python check.py"}]}).encode(),
        "bin/run.sh": b"#!/bin/sh\n",
    }
    summary = P.summarize_package(files)
    assert summary["has_tools"] is True
    assert summary["hooks"] == ["python check.py"]
    assert summary["bin"] == ["bin/run.sh"]
    assert summary["mcp_servers"] == ["srv"]
    text = "\n".join(summary["lines"])
    assert "api.example.com" in text
    assert "not limited to" in text
    assert "python check.py" in text
    assert "restricted sandbox" in text
    assert "bin/run.sh" in text
    assert "srv" in text and "not sandboxed" in text


def test_summary_cuts_long_hook_commands_and_notes_invalid_declaration():
    files = {
        "SKILL.md": _skill_md("permissions: yes\n"),
        "hooks.json": json.dumps({"hooks": [{"event": "e", "command": "x" * 500}]}).encode(),
    }
    summary = P.summarize_package(files)
    assert len(summary["hooks"][0]) == 300
    assert "invalid" in "\n".join(summary["lines"]).lower()


def test_summary_survives_broken_hooks_json():
    summary = P.summarize_package({"SKILL.md": _skill_md(""), "hooks.json": b"{not json"})
    assert summary["hooks"] == []


def test_readable_paths_keeps_real_folders_and_drops_the_rest(tmp_path):
    keep = tmp_path / "reports"
    keep.mkdir()
    perms = P.Permissions(filesystem=(str(keep), str(tmp_path / "does-not-exist")))
    assert P.readable_paths(perms) == [keep.resolve()]


def test_readable_paths_drops_secrets_folder():
    import secure_store

    secrets = Path(secure_store.__file__).resolve().parent
    perms = P.Permissions(filesystem=(str(Path.home() / ".gator"),))
    assert all(not str(p).startswith(str(Path.home() / ".gator" / "secrets")) for p in P.readable_paths(perms))
    assert secrets  # keeps the import used
