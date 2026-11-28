import pytest

from remote.state import State


def test_missing_file_is_empty(tmp_path):
    st = State(tmp_path / "s.json")
    assert st.last_id("teams") is None
    assert st.is_own_post("teams", "1") is False


def test_last_id_survives_a_new_instance(tmp_path):
    State(tmp_path / "s.json").set_last_id("teams", "100")
    assert State(tmp_path / "s.json").last_id("teams") == "100"


def test_posted_ids_survive_and_are_capped(tmp_path):
    st = State(tmp_path / "s.json")
    for i in range(300):
        st.record_post("teams", str(i))
    again = State(tmp_path / "s.json")
    assert again.is_own_post("teams", "299")
    assert not again.is_own_post("teams", "0")


def test_channels_are_independent(tmp_path):
    st = State(tmp_path / "s.json")
    st.set_last_id("teams", "1")
    st.record_post("teams", "9")
    assert st.last_id("slack") is None
    assert not st.is_own_post("slack", "9")


def test_corrupt_file_is_treated_as_empty(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert State(p).last_id("teams") is None


def test_disarmed_flag_persists_across_instances_and_clears(tmp_path):
    path = tmp_path / "s.json"
    assert State(path).disarmed("teams") is False
    State(path).set_disarmed("teams", True)
    assert State(path).disarmed("teams") is True
    assert State(path).disarmed("slack") is False
    State(path).set_disarmed("teams", False)
    assert State(path).disarmed("teams") is False


def test_a_file_that_cannot_be_read_right_now_is_never_overwritten_with_an_empty_one(tmp_path, monkeypatch):
    from pathlib import Path

    from remote import state as state_module

    monkeypatch.setattr(state_module, "READ_RETRY_SECONDS", 0)
    st = State(tmp_path / "s.json")
    st.set_master({"armed_at": 1.0, "deadline": 2.0})
    real = Path.read_text

    def locked(self, *args, **kwargs):
        raise PermissionError("held by another process")

    monkeypatch.setattr(Path, "read_text", locked)
    assert st.master() is None
    with pytest.raises(OSError):
        st.set_last_id("teams", "5")
    monkeypatch.setattr(Path, "read_text", real)
    assert st.master() == {"armed_at": 1.0, "deadline": 2.0}


def test_a_read_that_fails_once_is_retried(tmp_path, monkeypatch):
    from pathlib import Path

    from remote import state as state_module

    monkeypatch.setattr(state_module, "READ_RETRY_SECONDS", 0)
    st = State(tmp_path / "s.json")
    st.set_master({"armed_at": 1.0, "deadline": 2.0})
    real, calls = Path.read_text, []

    def flaky(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("held")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky)
    st.set_last_id("teams", "5")
    monkeypatch.setattr(Path, "read_text", real)
    assert st.master() == {"armed_at": 1.0, "deadline": 2.0} and st.last_id("teams") == "5"
