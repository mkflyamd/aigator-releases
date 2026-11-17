"""Parallel install, uninstall and create requests (threadpool routes) must leave files and index in agreement."""

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

SKILL_MD = "---\nname: demo\ndescription: A test\n---\n# Demo\nDo stuff."


def _hammer(workers):
    barrier = threading.Barrier(len(workers))
    errors = []

    def run(fn):
        try:
            barrier.wait()
            for _ in range(15):
                fn()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


def test_install_and_uninstall_leave_index_and_directory_in_agreement(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m

    _hammer(
        [
            lambda: m.install_skill_md("demo", SKILL_MD, "1.0", "Community"),
            lambda: m.uninstall_skill("demo"),
            lambda: m.install_skill_md("demo", SKILL_MD, "1.0", "Community"),
        ]
    )

    listed = any(e["id"] == "demo" for e in m.load_installed())
    assert listed == (tmp_path / "demo" / "SKILL.md").exists()


def test_create_and_uninstall_leave_index_and_directory_in_agreement(tmp_path, monkeypatch):
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import marketplace.installer as m

    _hammer(
        [
            lambda: m.create_user_skill("demo", "A test", "Do stuff."),
            lambda: m.uninstall_skill("demo"),
        ]
    )

    listed = any(e["id"] == "demo" for e in m.load_installed())
    assert listed == (tmp_path / "mine" / "demo" / "SKILL.md").exists()
