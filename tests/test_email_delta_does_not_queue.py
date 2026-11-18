"""A delta poll that arrives while another delta sync is running must not wait for it."""

import threading

from routes import email


def test_delta_poll_during_a_running_sync_gets_a_plain_fetch_without_waiting(monkeypatch):
    calls = []
    inside = threading.Event()
    release = threading.Event()

    def first_sync(skip, top, filter, delta, folder):
        calls.append(delta)
        inside.set()
        release.wait(5)
        return "first"

    monkeypatch.setattr(email, "_email_inbox", first_sync)
    first = threading.Thread(target=email.tp_email_inbox, kwargs={"delta": True})
    first.start()
    assert inside.wait(5)

    monkeypatch.setattr(email, "_email_inbox", lambda skip, top, filter, delta, folder: calls.append(delta) or "second")
    answered = []
    second = threading.Thread(target=lambda: answered.append(email.tp_email_inbox(delta=True)))
    second.start()
    second.join(2)
    release.set()
    first.join(5)

    assert not second.is_alive(), "the second poll waited behind the running delta sync"
    assert answered == ["second"]
    assert calls == [True, False], "the waiting poll must fall back to a plain fetch"


def test_the_lock_is_released_after_a_sync_even_when_it_fails(monkeypatch):
    def boom(skip, top, filter, delta, folder):
        raise RuntimeError("graph down")

    monkeypatch.setattr(email, "_email_inbox", boom)
    try:
        email.tp_email_inbox(delta=True)
    except RuntimeError:
        pass
    assert email._EMAIL_DELTA_LOCK.acquire(blocking=False)
    email._EMAIL_DELTA_LOCK.release()
