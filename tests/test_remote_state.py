import json

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


def _lane(project_id="p1", **over):
    lane = {
        "project_id": project_id,
        "name": "Budget",
        "agent": "claude",
        "repo_path": "C:/repo/budget",
        "pty_id": "pty-1",
        "short": "budget",
        "vendor_session_id": "vendor-1",
        "created_at": 1.0,
        "last_activity": 2.0,
        "state": "live",
        "failure": "",
    }
    lane.update(over)
    return lane


def test_a_lane_survives_a_new_instance(tmp_path):
    State(tmp_path / "s.json").put_lane("teams", _lane(state="sleeping"))
    assert State(tmp_path / "s.json").lanes("teams") == {"p1": _lane(state="sleeping")}


def test_a_project_never_has_two_lanes(tmp_path):
    st = State(tmp_path / "s.json")
    st.put_lane("teams", _lane(pty_id="pty-1"))
    st.put_lane("teams", _lane(pty_id="pty-2", short="budget-2"))
    lanes = State(tmp_path / "s.json").lanes("teams")
    assert list(lanes) == ["p1"]
    assert lanes["p1"]["pty_id"] == "pty-2"


def test_lanes_are_kept_per_channel_and_per_project(tmp_path):
    st = State(tmp_path / "s.json")
    st.put_lane("teams", _lane("p1"))
    st.put_lane("teams", _lane("p2", pty_id="pty-2", short="other"))
    st.put_lane("slack", _lane("p1", pty_id="pty-3"))
    assert sorted(st.lanes("teams")) == ["p1", "p2"]
    assert list(st.lanes("slack")) == ["p1"]


def test_a_dropped_lane_stays_dropped_after_a_restart(tmp_path):
    st = State(tmp_path / "s.json")
    st.put_lane("teams", _lane())
    st.drop_lane("teams", "p1")
    st.drop_lane("teams", "never-existed")
    assert State(tmp_path / "s.json").lanes("teams") == {}


def test_an_unchanged_lane_is_not_written_again(tmp_path):
    path = tmp_path / "s.json"
    st = State(path)
    st.put_lane("teams", _lane())
    before = path.stat().st_mtime_ns
    st.put_lane("teams", _lane())
    assert path.stat().st_mtime_ns == before


def test_a_malformed_lane_is_ignored_rather_than_trusted(tmp_path):
    path = tmp_path / "s.json"
    good = _lane("p2", pty_id="pty-2", short="other")
    path.write_text(
        json.dumps(
            {
                "teams": {
                    "lanes": {
                        "p1": _lane(state="bogus"),
                        "p3": _lane("p3", pty_id=""),
                        "p4": _lane("elsewhere"),
                        "p2": good,
                        "p5": "nope",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert State(path).lanes("teams") == {"p2": good}


def test_lanes_do_not_disturb_the_other_stored_values(tmp_path):
    st = State(tmp_path / "s.json")
    st.set_last_id("teams", "100")
    st.put_lane("teams", _lane())
    assert State(tmp_path / "s.json").last_id("teams") == "100"
