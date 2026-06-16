import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

import importlib
from pathlib import Path


def test_install_plugin_creates_versioned_path(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import marketplace.installer as m; importlib.reload(m)
    result = m.install_plugin(
        plugin_id="rocm-toolkit",
        version="1.2.0",
        marketplace="gator-native",
        skill_md="---\nname: rocm\n---\nDo GPU stuff.",
        tier="Native",
    )
    assert result["ok"] is True
    expected = tmp_path / "cache" / "gator-native" / "rocm-toolkit" / "1.2.0" / "SKILL.md"
    assert expected.exists()


def test_install_plugin_records_source_and_marketplace_url(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import marketplace.installer as m; importlib.reload(m)
    m.install_plugin(
        plugin_id="my-plugin",
        version="0.1.0",
        marketplace="anthropic-community",
        skill_md="---\nname: mine\n---\ncontent",
        tier="Community",
        marketplace_url="https://github.com/example/my-plugin",
    )
    entries = m.load_installed()
    entry = next(e for e in entries if e["id"] == "my-plugin")
    assert entry["source"] == "anthropic-community"
    assert entry["marketplace_url"] == "https://github.com/example/my-plugin"


def test_install_plugin_does_not_overwrite_existing_version(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import marketplace.installer as m; importlib.reload(m)

    m.install_plugin("pkg", "1.0.0", "gator-native", "---\nname: p\n---\nv1", "Native")
    versioned = tmp_path / "cache" / "gator-native" / "pkg" / "1.0.0" / "SKILL.md"
    original_mtime = versioned.stat().st_mtime

    # Install again — should NOT overwrite
    m.install_plugin("pkg", "1.0.0", "gator-native", "---\nname: p\n---\nv1-changed", "Native")
    assert versioned.stat().st_mtime == original_mtime


def test_install_plugin_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import marketplace.installer as m; importlib.reload(m)
    result = m.install_plugin(
        "../../escape", "1.0.0", "gator-native", "---\nname: bad\n---\ncontent", "Community"
    )
    assert result["ok"] is False


def test_install_plugin_recovers_from_partial_install(tmp_path, monkeypatch):
    """If a previous install crashed after mkdir but before SKILL.md write,
    a retry must actually write the file (not silently treat dir as installed)."""
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import marketplace.installer as m; importlib.reload(m)

    # Simulate partial prior install: directory exists, SKILL.md missing
    partial = tmp_path / "cache" / "gator-native" / "pkg" / "1.0.0"
    partial.mkdir(parents=True)
    assert not (partial / "SKILL.md").exists()

    result = m.install_plugin("pkg", "1.0.0", "gator-native", "---\nname: p\n---\nbody", "Native")
    assert result["ok"] is True
    assert (partial / "SKILL.md").read_text(encoding="utf-8").endswith("body")


def test_install_plugin_records_has_tools(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import marketplace.installer as m; importlib.reload(m)
    m.install_plugin(
        "tooled", "1.0.0", "gator-native", "---\nname: t\n---\n", "Native", has_tools=True,
    )
    entry = next(e for e in m.load_installed() if e["id"] == "tooled")
    assert entry["has_tools"] is True


def test_install_plugin_concurrent_installs_preserve_all_entries(tmp_path, monkeypatch):
    """Two threads installing different plugins must both end up in the index
    (read-modify-write race would silently drop one)."""
    import threading
    monkeypatch.setattr("marketplace.installer.PLUGINS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path / "skills")
    import marketplace.installer as m; importlib.reload(m)

    ids = [f"plugin-{i}" for i in range(20)]
    def worker(pid):
        m.install_plugin(pid, "1.0.0", "gator-native", f"---\nname: {pid}\n---\n", "Native")
    threads = [threading.Thread(target=worker, args=(pid,)) for pid in ids]
    for t in threads: t.start()
    for t in threads: t.join()

    installed_ids = {e["id"] for e in m.load_installed()}
    assert installed_ids == set(ids)
