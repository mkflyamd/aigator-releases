"""Whether the user is away from the machine: the screen is locked, or there has been no keyboard or mouse input
for AWAY_IDLE_SECONDS. A probe that cannot tell says the user is at the machine, so the longer delay applies."""

from __future__ import annotations

import sys

AWAY_IDLE_SECONDS = 120.0
LOCKED_MIN_IDLE_SECONDS = 5.0
_DESKTOP_SWITCHDESKTOP = 0x0100
_ERROR_ACCESS_DENIED = 5


def is_away() -> bool:
    if sys.platform != "win32":
        return False
    for probe in (_screen_locked, lambda: _idle_seconds() >= AWAY_IDLE_SECONDS):
        try:
            if probe():
                return True
        except Exception:
            continue
    return False


def _screen_locked() -> bool:
    """Locked only when the input desktop is refused with "access denied" and nobody has touched the machine for a
    few seconds. Any other failure (a sandboxed process, session 0, a remote session, the UAC prompt) is not a lock."""
    desktop, error = _open_input_desktop()
    if desktop:
        _close_desktop(desktop)
        return False
    return error == _ERROR_ACCESS_DENIED and _idle_seconds() >= LOCKED_MIN_IDLE_SECONDS


def _open_input_desktop() -> tuple[int | None, int]:
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    desktop = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    return desktop, ctypes.get_last_error()


def _close_desktop(desktop: int) -> None:
    import ctypes

    user32 = ctypes.WinDLL("user32")
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    user32.CloseDesktop(desktop)


def _idle_seconds() -> float:
    import ctypes
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError("GetLastInputInfo failed")
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0
