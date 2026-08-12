"""Stamp a Windows .lnk shortcut with an explicit AppUserModelID.

Windows resolves a running app's taskbar icon and toast-notification icon by
matching the process's AppUserModelID (set via app.setAppUserModelId in
shell/main.js) to a Start-Menu shortcut that declares the SAME AppID and
carries the icon. WScript.Shell cannot set the AppID, so we set the
System.AppUserModel.ID property via the shell property store (pywin32).

Usage:  python set_shortcut_appid.py <path-to.lnk> <AppUserModelID>

Best-effort: exits 0 on success, non-zero (with a message) on failure. The
caller (WakeGator.ps1) treats failure as non-fatal.
"""
import sys

# PKEY_AppUserModel_ID = {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}, pid 5
_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
_PID = 5


# GETPROPERTYSTOREFLAGS (propsys.h). pywin32 doesn't expose these as named
# constants, so use the raw values.
_GPS_DEFAULT = 0x00000000
_GPS_READWRITE = 0x00000002


def set_appid(lnk_path: str, app_id: str) -> None:
    import pythoncom
    from win32com.propsys import propsys  # type: ignore

    # Load the shell link's property store in read/write mode.
    store = propsys.SHGetPropertyStoreFromParsingName(
        lnk_path,
        None,
        _GPS_READWRITE,
        propsys.IID_IPropertyStore,
    )
    key = propsys.PSGetPropertyKeyFromName("System.AppUserModel.ID")
    value = propsys.PROPVARIANTType(app_id, pythoncom.VT_LPWSTR)
    store.SetValue(key, value)
    store.Commit()


def _verify(lnk_path: str, app_id: str) -> bool:
    try:
        from win32com.propsys import propsys  # type: ignore
        store = propsys.SHGetPropertyStoreFromParsingName(
            lnk_path, None, _GPS_DEFAULT, propsys.IID_IPropertyStore
        )
        key = propsys.PSGetPropertyKeyFromName("System.AppUserModel.ID")
        return store.GetValue(key).GetValue() == app_id
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: set_shortcut_appid.py <path.lnk> <AppUserModelID>", file=sys.stderr)
        return 2
    lnk_path, app_id = sys.argv[1], sys.argv[2]
    try:
        set_appid(lnk_path, app_id)
    except Exception as e:  # pragma: no cover - platform/COM dependent
        print(f"failed to set AppUserModelID: {e}", file=sys.stderr)
        return 1
    if not _verify(lnk_path, app_id):
        print("AppUserModelID did not persist", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
