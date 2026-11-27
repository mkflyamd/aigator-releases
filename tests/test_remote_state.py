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
