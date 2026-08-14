"""Embed an icon into a Windows exe via the UpdateResource API.

rcedit silently fails to embed icons on some Electron builds (reports exit 0
but never writes the resource). This script uses the Windows UpdateResourceW
API directly, which reliably embeds the icon.

Usage:  python brand_icon.py <exe_path> <ico_path> [product_name]
"""

import ctypes
import struct
import sys


def brand_icon(exe_path: str, ico_path: str, product_name: str = "AI Gator") -> bool:
    with open(ico_path, "rb") as f:
        ico_data = f.read()

    # Parse ICO header
    _reserved, ico_type, count = struct.unpack("<HHH", ico_data[:6])
    if ico_type != 1:
        print(f"Not an ICO file (type={ico_type})", file=sys.stderr)
        return False

    entries = []
    offset = 6
    for _ in range(count):
        w, h, _colors, _r, planes, bpp, size, data_offset = struct.unpack(
            "<BBBBHHII", ico_data[offset : offset + 16]
        )
        entries.append((w, h, bpp, size, data_offset))
        offset += 16

    kernel32 = ctypes.windll.kernel32
    kernel32.BeginUpdateResourceW.restype = ctypes.c_void_p
    kernel32.BeginUpdateResourceW.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
    kernel32.UpdateResourceW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint16,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    kernel32.EndUpdateResourceW.argtypes = [ctypes.c_void_p, ctypes.c_int]

    hUpdate = kernel32.BeginUpdateResourceW(exe_path, False)
    if not hUpdate:
        print(
            f"BeginUpdateResource failed: error {ctypes.GetLastError()}",
            file=sys.stderr,
        )
        return False

    # Build RT_GROUP_ICON (type 14) — uses "#" string format for integer IDs
    grp = struct.pack("<HHH", 0, 1, count)
    for i, (w, h, bpp, size, _) in enumerate(entries):
        wb = 0 if w == 256 else w
        hb = 0 if h == 256 else h
        grp += struct.pack("<BBBBHHII", wb, hb, 0, 0, 1, bpp, size, i + 1)

    buf = ctypes.create_string_buffer(grp)
    ok = kernel32.UpdateResourceW(hUpdate, "#14", "#1", 0x0409, buf, len(grp))
    if not ok:
        print(
            f"UpdateResource (group) failed: error {ctypes.GetLastError()}",
            file=sys.stderr,
        )

    for i, (w, h, bpp, size, data_offset) in enumerate(entries):
        raw = ico_data[data_offset : data_offset + size]
        buf2 = ctypes.create_string_buffer(raw)
        ok = kernel32.UpdateResourceW(hUpdate, "#3", f"#{i + 1}", 0x0409, buf2, size)
        if not ok:
            print(
                f"UpdateResource (icon {i + 1}) failed: error {ctypes.GetLastError()}",
                file=sys.stderr,
            )

    ok = kernel32.EndUpdateResourceW(hUpdate, False)
    if not ok:
        print(
            f"EndUpdateResource failed: error {ctypes.GetLastError()}", file=sys.stderr
        )
        return False

    # Set version strings via rcedit (this part works — only --set-icon fails)
    try:
        import subprocess

        rcedit = None
        import os

        for p in [os.path.join(os.environ.get("TEMP", ""), "aigator-rcedit-x64.exe")]:
            if os.path.exists(p):
                rcedit = p
                break
        if rcedit:
            subprocess.run(
                [
                    rcedit,
                    exe_path,
                    "--set-version-string",
                    "ProductName",
                    product_name,
                    "--set-version-string",
                    "FileDescription",
                    product_name,
                ],
                capture_output=True,
            )
    except Exception:
        pass

    # Verify
    kernel32.LoadLibraryExW.restype = ctypes.c_void_p
    kernel32.LoadLibraryExW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.FindResourceW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
    ]
    hMod = kernel32.LoadLibraryExW(exe_path, None, 0x22)
    if hMod:
        found = kernel32.FindResourceW(hMod, "#1", "#14")
        kernel32.FreeLibrary(ctypes.c_void_p(hMod))
        if found:
            print("Icon embedded successfully")
            return True
        else:
            print("Icon resource NOT found after update", file=sys.stderr)
            return False
    return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: brand_icon.py <exe_path> <ico_path> [product_name]", file=sys.stderr
        )
        sys.exit(2)
    exe = sys.argv[1]
    ico = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else "AI Gator"
    ok = brand_icon(exe, ico, name)
    sys.exit(0 if ok else 1)
