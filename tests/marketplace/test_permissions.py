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
    assert "Starts the MCP server 'srv' on your computer (not sandboxed): npx x" in summary["lines"]


def test_summary_cuts_long_hook_commands_and_notes_invalid_declaration():
    files = {
        "SKILL.md": _skill_md("permissions: yes\n"),
        "hooks.json": json.dumps({"hooks": [{"event": "e", "command": "x" * 500}]}).encode(),
    }
    summary = P.summarize_package(files)
    assert len(summary["hooks"][0]) == 300
    assert "invalid" in "\n".join(summary["lines"]).lower()


def _lines_for_servers(monkeypatch, servers):
    from marketplace import installer

    monkeypatch.setattr(installer, "_discover_plugin_mcp_manifest_from_files", lambda files: servers)
    return [l for l in P.summarize_package({"SKILL.md": _skill_md("")})["lines"] if "MCP server" in l]


def test_summary_cuts_a_long_mcp_command_with_a_visible_marker(monkeypatch):
    payload = "A" * 40
    (line,) = _lines_for_servers(monkeypatch, {
        "docs": {"command": "powershell", "args": ["-enc", payload * 20]},
    })
    shown = line.split("(not sandboxed): ", 1)[1]
    assert shown.startswith("powershell -enc AAAA")
    assert shown.endswith("\u2026") and len(shown) == 201
    assert "'docs'" in line


def test_summary_shows_the_url_of_a_remote_mcp_server(monkeypatch):
    (line,) = _lines_for_servers(monkeypatch, {"remote": {"type": "http", "url": "https://mcp.example.com/sse"}})
    assert "'remote'" in line and "https://mcp.example.com/sse" in line
    assert "Starts" not in line


def test_summary_mcp_command_has_control_characters_removed(monkeypatch):
    (line,) = _lines_for_servers(monkeypatch, {
        "srv": {"command": "node", "args": ["a\nStarts the MCP server 'fake'", "b\u202ec"]},
    })
    assert "\n" not in line and "\u202e" not in line and "\r" not in line


def test_summary_still_names_a_server_with_no_readable_command(monkeypatch):
    (line,) = _lines_for_servers(monkeypatch, {"odd": "not a dict"})
    assert "'odd'" in line and "not sandboxed" in line


def test_summary_survives_broken_hooks_json():
    summary = P.summarize_package({"SKILL.md": _skill_md(""), "hooks.json": b"{not json"})
    assert summary["hooks"] == []


def test_readable_paths_keeps_real_folders_and_drops_the_rest(tmp_path):
    keep = tmp_path / "reports"
    keep.mkdir()
    perms = P.Permissions(filesystem=(str(keep), str(tmp_path / "does-not-exist")))
    assert P.readable_paths(perms) == [keep.resolve()]


def test_readable_paths_drops_secrets_folder(tmp_path, monkeypatch):
    from sandbox import paths

    secret = tmp_path / "secret-store"
    secret.mkdir()
    ok = tmp_path / "reports"
    ok.mkdir()
    monkeypatch.setattr(paths, "is_secrets_path", lambda p: Path(p).resolve() == secret.resolve())
    perms = P.Permissions(filesystem=(str(secret), str(ok)))
    assert P.readable_paths(perms) == [ok.resolve()]


def test_summary_detects_nested_tools_and_bin():
    files = {
        "skills/x/SKILL.md": _skill_md(""),
        "skills/x/tools.py": b"TOOL_DEFS = []\n",
        "skills/x/bin/run.sh": b"#!/bin/sh\n",
    }
    summary = P.summarize_package(files)
    assert summary["has_tools"] is True
    assert summary["bin"] == ["skills/x/bin/run.sh"]
    text = "\n".join(summary["lines"])
    assert "Adds tools" in text
    assert "skills/x/bin/run.sh" in text
