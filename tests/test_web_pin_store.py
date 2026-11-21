import uuid
import pytest
from skills.webpin import store
from skills.context import state


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_ROOT", tmp_path / "web_pins")
    monkeypatch.setattr(state, "pinned_contexts", {})
    monkeypatch.setattr(state, "_save", lambda: None)


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
    assert store.read_image(pid) == b"\x89PNG-b"  # image=None keeps the previous image


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


def test_web_pin_dir_rejects_trailing_newline():
    with pytest.raises(ValueError):
        store.web_pin_dir(str(uuid.uuid4()) + "\n")
