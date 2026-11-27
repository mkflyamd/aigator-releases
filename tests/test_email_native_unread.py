"""Rail badge: Email can show the desktop Outlook Inbox unread count.

Outlook desktop keeps its own read state, which can differ from the server copy
Graph reports. The rail should show the number next to Inbox in Outlook when
Outlook is running, and let the client fall back to Graph when it is not.
"""

import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from routes import email
from skills import _office_com


class _FakeFolder:
    UnreadItemCount = 5


class _FakeNamespace:
    def __init__(self):
        self.requested = None

    def GetDefaultFolder(self, which):
        self.requested = which
        return _FakeFolder()


class _FakeApp:
    def __init__(self):
        self.ns = _FakeNamespace()

    def GetNamespace(self, name):
        assert name == "MAPI"
        return self.ns


def _install_fake_win32com(monkeypatch, get_active):
    client = types.SimpleNamespace(GetActiveObject=get_active)
    win32com = types.ModuleType("win32com")
    win32com.client = client
    pythoncom = types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)


def test_reads_inbox_unread_from_running_outlook(monkeypatch):
    app = _FakeApp()
    seen = []
    _install_fake_win32com(monkeypatch, lambda prog: seen.append(prog) or app)
    assert _office_com.get_outlook_inbox_unread() == 5
    assert seen == ["Outlook.Application"]
    assert app.ns.requested == 6  # olFolderInbox


def test_returns_none_when_outlook_is_not_running(monkeypatch):
    def not_running(prog):
        raise OSError("Operation unavailable")

    _install_fake_win32com(monkeypatch, not_running)
    assert _office_com.get_outlook_inbox_unread() is None


def test_returns_none_when_com_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "win32com", None)
    assert _office_com.get_outlook_inbox_unread() is None


def test_route_reports_count_or_null(monkeypatch):
    monkeypatch.setattr(email, "get_outlook_inbox_unread", lambda: 5)
    assert email.tp_email_native_unread() == {"count": 5}
    monkeypatch.setattr(email, "get_outlook_inbox_unread", lambda: None)
    assert email.tp_email_native_unread() == {"count": None}
