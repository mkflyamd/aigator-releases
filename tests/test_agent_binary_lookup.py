import generic_agent as ga


def _fake_which(on_path, on_registry_path):
    def which(name, path=None):
        if path is None:
            return on_path.get(name)
        return on_registry_path.get(name)

    return which


def test_agent_installed_after_the_server_started_is_found(monkeypatch):
    monkeypatch.setattr(ga.shutil, "which", _fake_which({}, {"crush": "C:\\winget\\crush.exe"}))
    monkeypatch.setattr(ga, "_windows_registry_path", lambda: "C:\\winget")
    assert ga.find_agent_binary("crush") == "C:\\winget\\crush.exe"
    assert ga.is_installed("crush")


def test_process_path_wins_over_the_registry(monkeypatch):
    monkeypatch.setattr(
        ga.shutil,
        "which",
        _fake_which({"crush": "C:\\now\\crush.exe"}, {"crush": "C:\\winget\\crush.exe"}),
    )
    monkeypatch.setattr(ga, "_windows_registry_path", lambda: "C:\\winget")
    assert ga.find_agent_binary("crush") == "C:\\now\\crush.exe"


def test_missing_agent_stays_missing(monkeypatch):
    monkeypatch.setattr(ga.shutil, "which", _fake_which({}, {}))
    monkeypatch.setattr(ga, "_windows_registry_path", lambda: "C:\\winget")
    monkeypatch.setattr(ga, "_wsl_capable", lambda agent: False)
    assert ga.find_agent_binary("crush") is None
    assert not ga.is_installed("crush")


def test_opencode_found_through_the_registry_path(monkeypatch):
    monkeypatch.setattr(ga.shutil, "which", _fake_which({}, {"opencode": "C:\\npm\\opencode.cmd"}))
    monkeypatch.setattr(ga, "_windows_registry_path", lambda: "C:\\npm")
    assert ga.build_opencode_bare_command("C:\\w")[0] == "C:\\npm\\opencode.cmd"
