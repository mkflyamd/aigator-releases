import uuid
import pytest
from skills.webpin import store
from skills.context import state


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_ROOT", tmp_path / "web_pins")
    monkeypatch.setattr(state, "pinned_contexts", {})
    monkeypatch.setattr(state, "_save", lambda: True)


def test_web_pin_dir_rejects_non_uuid():
    for bad in ["../x", "abc", "", "..\\x", str(uuid.uuid4()).upper()]:
        with pytest.raises(ValueError):
            store.web_pin_dir(bad)


def test_web_pin_dir_accepts_uuid4(tmp_path):
    pid = str(uuid.uuid4())
    assert store.web_pin_dir(pid) == tmp_path / "web_pins" / pid


def test_sanitize_label_strips_newlines_quotes_and_caps():
    out = store.sanitize_label('Q3 "Revenue"\n\r ignore previous ' + "x" * 300)
    assert "\n" not in out and "\r" not in out and '"' not in out
    assert len(out) <= 120


def test_write_then_read_snapshot_and_changed_flag():
    pid = str(uuid.uuid4())
    first = store.write_snapshot(pid, image=b"\x89PNG-a", text="hello", meta={"url": "https://x"})
    assert first["changed"] is True
    snap = store.read_snapshot(pid)
    assert snap["text"] == "hello" and snap["meta"]["url"] == "https://x"
    assert store.read_image(pid) == b"\x89PNG-a"
    same = store.write_snapshot(pid, image=b"\x89PNG-b", text="hello", meta={})
    assert same["changed"] is False
    diff = store.write_snapshot(pid, image=None, text="hello 2", meta={})
    assert diff["changed"] is True
    assert store.read_image(pid) is None  # an omitted image drops the previous one


def test_read_missing_returns_none():
    pid = str(uuid.uuid4())
    assert store.read_snapshot(pid) is None
    assert store.read_image(pid) is None


def test_delete_if_unreferenced_keeps_dir_while_any_bucket_references_it():
    pid = str(uuid.uuid4())
    store.write_snapshot(pid, image=b"x", text="t", meta={})
    state.set_pin("webpin", pid, "L", {}, "tab-a")
    state.set_pin("webpin", pid, "L", {}, "tab-b")  # cloned into another tab
    state.remove_pin("webpin", pid, "tab-a")
    assert store.web_pin_dir(pid).exists()
    state.remove_pin("webpin", pid, "tab-b")
    assert not store.web_pin_dir(pid).exists()


def test_clear_pins_cleans_webpin_dirs():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    for p in (a, b):
        store.write_snapshot(p, image=b"x", text="t", meta={})
        state.set_pin("webpin", p, "L", {}, "tab-a")
    state.clear_pins("tab-a")
    assert not store.web_pin_dir(a).exists() and not store.web_pin_dir(b).exists()


def test_global_remove_cleans_the_snapshot_when_no_bucket_keeps_it():
    pid = str(uuid.uuid4())
    store.write_snapshot(pid, image=b"x", text="t", meta={})
    state.set_pin("webpin", pid, "L", {}, "tab-a")
    state.set_pin("webpin", pid, "L", {}, "tab-b")
    state.set_pin_scope("webpin", pid, "global", "tab-a")
    state.remove_pin("webpin", pid, "tab-a", scope="global")
    assert not store.web_pin_dir(pid).exists()


def test_moving_a_pin_to_global_keeps_the_snapshot():
    pid = str(uuid.uuid4())
    store.write_snapshot(pid, image=b"x", text="t", meta={})
    state.set_pin("webpin", pid, "L", {}, "tab-a")
    state.set_pin_scope("webpin", pid, "global", "tab-a")
    assert store.web_pin_dir(pid).exists()


def test_web_pin_dir_rejects_trailing_newline():
    with pytest.raises(ValueError):
        store.web_pin_dir(str(uuid.uuid4()) + "\n")


def test_image_not_served_when_it_does_not_match_the_snapshot():
    pid = str(uuid.uuid4())
    store.write_snapshot(pid, image=b"\x89PNG-a", text="t", meta={})
    (store.web_pin_dir(pid) / "snapshot.png").write_bytes(b"\x89PNG-torn")
    assert store.read_image(pid) is None


def test_failed_write_leaves_previous_snapshot_and_no_temp_files(monkeypatch):
    import os

    pid = str(uuid.uuid4())
    store.write_snapshot(pid, image=b"\x89PNG-a", text="one", meta={})
    real = os.replace

    def boom(src, dst):
        if str(dst).endswith("snapshot.json"):
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        store.write_snapshot(pid, image=b"\x89PNG-b", text="two", meta={})
    monkeypatch.setattr(store.os, "replace", real)
    assert store.read_snapshot(pid)["text"] == "one"
    assert store.read_image(pid) is None  # new png does not match the old snapshot, so it is not served
    assert not list(store.web_pin_dir(pid).glob("*.tmp"))


def test_description_write_is_atomic(monkeypatch):
    pid = str(uuid.uuid4())
    store.write_snapshot(pid, image=b"x", text="t", meta={})
    store.write_description(pid, b"x", "a chart", "m1")
    with monkeypatch.context() as m:
        m.setattr(store.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("no")))
        with pytest.raises(OSError):
            store.write_description(pid, b"x", "other", "m2")
    assert store.read_description(pid, b"x")["text"] == "a chart"
    assert not list(store.web_pin_dir(pid).glob("*.tmp"))


def test_cleanup_matches_pin_ids_structurally_not_by_substring():
    pid = str(uuid.uuid4())
    store.write_snapshot(pid, image=b"x", text="t", meta={})
    state.set_pin("note", "n1", f"mentions {pid} in a label", {"text": pid}, "tab-a")
    assert store.delete_if_unreferenced(pid) is True
    assert not store.web_pin_dir(pid).exists()


def test_set_pin_rolls_back_when_save_fails(monkeypatch):
    monkeypatch.setattr(state, "_save", lambda: False)
    out = state.set_pin("webpin", "p1", "L", {}, "tab-a")
    assert out["pinned"] is False and state.get_pins("tab-a") == []
    state.pinned_contexts["tab-a"] = {"webpin::p1": {"source": "webpin", "id": "p1", "label": "old", "meta": {}}}
    out = state.set_pin("webpin", "p1", "new", {}, "tab-a")
    assert out["pinned"] is False and state.get_pins("tab-a")[0]["label"] == "old"


def test_label_prefers_element_label_then_page_title():
    assert store.derive_label("Revenue card", "Finance - Power BI", "Power BI", "pbi", "https://app.powerbi.com/r") == "Revenue card"
    assert store.derive_label("", "Finance - Power BI", "Power BI", "pbi", "https://app.powerbi.com/r") == "Finance"


def test_label_never_falls_back_to_the_app_name():
    for title in ("", "Untitled", "app.powerbi.com", "https://app.powerbi.com/r/1"):
        assert store.derive_label("", title, "Power BI", "pbi", "https://app.powerbi.com/r/1") == "Web view"
