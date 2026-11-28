"""Whether the user is away from the machine: the screen is locked, or there has been no keyboard or mouse input
for AWAY_IDLE_SECONDS. A probe that cannot tell says the user is at the machine."""

from __future__ import annotations

import sys

AWAY_IDLE_SECONDS = 120.0
_DESKTOP_SWITCHDESKTOP = 0x0100


def is_away() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return _screen_locked() or _idle_seconds() >= AWAY_IDLE_SECONDS
    except Exception:
        return False


def _screen_locked() -> bool:
    """The input desktop is the lock screen's while locked, and a normal process cannot open it."""
    import ctypes

    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    desktop = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return True
    user32.CloseDesktop(desktop)
    return False


def _idle_seconds() -> float:
    import ctypes
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError("GetLastInputInfo failed")
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0
