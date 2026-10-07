"""Windows AppContainer launcher: ctypes only, no admin, no new dependency.

Ported from the 2026-10-05 spike (.superpowers/spike-appcontainer/ac.py).

Grant model (plan Task 4): one per-user AppContainer profile (PROFILE_NAME) is
reused. Runtime directories get a persistent inheritable read+execute ACE for
its SID, granted once and recorded in the ledger (re-granting ~30k files costs
~8.5 s each way). The run folder and user-approved extras are granted for one
run and revoked in `finally`; runs are serialized so one run's grants are
never visible to another. Every per-run grant is written to the ledger before
icacls runs; sweep_stale_grants() (server startup) revokes leftovers of a
crashed run. icacls works without admin because the user owns these paths
(per-user install). System32 is covered by ALL APPLICATION PACKAGES.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import stat
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

from . import RawArg, SandboxRequest, SandboxResult, SandboxRunError, SandboxUnavailable

_log = logging.getLogger(__name__)

PROFILE_NAME = "AIGator.CodeRunner"
SHELL_PROFILE_SUFFIX = ".Shell"  # run_shell's profile, so a persistent grant on the scratch folder is not shared with run_python
INTERNET_CLIENT_SID = "S-1-15-3-1"

PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
EXTENDED_STARTUPINFO_PRESENT = 0x80000
CREATE_UNICODE_ENVIRONMENT = 0x400
CREATE_SUSPENDED = 0x4
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x100
HANDLE_FLAG_INHERIT = 0x1
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF
SE_GROUP_ENABLED = 0x4
GENERIC_READ = 0x80000000
FILE_SHARE_READ_WRITE = 0x3
OPEN_EXISTING = 3
HRESULT_ALREADY_EXISTS = ctypes.c_long(0x800700B7).value

_RUN_LOCK = threading.Lock()
_LEDGER_LOCK = threading.Lock()
_API: SimpleNamespace | None = None


def ledger_path() -> Path:
    return Path.home() / ".gator" / "sandbox" / "grants.json"


# ── Pure helpers (unit-tested on every OS) ──────────────────────────────────

def ace_spec(sid: str, perm: str, is_dir: bool) -> str:
    return f"*{sid}:(OI)(CI){perm}" if is_dir else f"*{sid}:{perm}"


def acl_grants(req: SandboxRequest) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
    """(persistent runtime grants, per-run grants)."""
    runtime = [(Path(p), "RX") for p in req.runtime_paths]
    per_run = (
        [(Path(p), "RX") for p in req.read_paths]
        + [(Path(p), "M") for p in req.write_paths]
        + [(Path(req.cwd), "M")]
    )
    return runtime, per_run


def _env_block(env: dict[str, str]) -> str:
    """CreateProcessW environment block: KEY=VALUE NUL, sorted case-insensitively, double-NUL terminated."""
    body = "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper()))
    return (body or "\0") + "\0"


def _cmdline(argv: list[str]) -> str:
    return " ".join(str(a) if isinstance(a, RawArg) else subprocess.list2cmdline([a]) for a in argv)


def _icacls_exe() -> str:
    root = os.environ.get("SystemRoot")
    return os.path.join(root, "System32", "icacls.exe") if root else "icacls"


def _check_icacls_path(path: str) -> None:
    """icacls expands * and ? in its path argument; refuse them (the extended-length prefix is not a wildcard)."""
    bare = path[4:] if path.startswith("\\\\?\\") else path
    if "*" in bare or "?" in bare:
        raise ValueError(f"wildcard characters are not allowed in a sandbox path: {path!r}")


def _covered_by(path: Path, dirs: list[str]) -> bool:
    """True when path is one of dirs or inside one (already persistently readable)."""
    target = os.path.normcase(os.path.abspath(str(path)))
    for d in dirs:
        base = os.path.normcase(os.path.abspath(d)).rstrip("\\/")
        if target == base or target.startswith(base + os.sep):
            return True
    return False


def _is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(isjunction and isjunction(str(path)))


def _remove_entry(path: Path) -> None:
    """Delete one file or link without following it (read-only files are made writable first)."""
    try:
        os.unlink(path)
    except PermissionError:
        if not _is_link(path):  # never chmod through a link
            try:
                os.chmod(path, stat.S_IWRITE)
                os.unlink(path)
                return
            except OSError:
                pass
        os.rmdir(path)  # a directory link (junction) is removed itself, never its target
    except OSError:
        os.rmdir(path)


def _empty_dir(directory: Path) -> int:
    removed = 0
    try:
        children = list(directory.iterdir())
    except OSError:
        return 0
    for child in children:
        try:
            if _is_link(child) or not child.is_dir():
                _remove_entry(child)
            else:
                removed += _empty_dir(child)
                child.rmdir()
            removed += 1
        except OSError:
            pass
    return removed


def clear_container_storage(folder: Path) -> int:
    """Empty the AppContainer storage folder (Packages/<profile>/AC under LOCALAPPDATA), keeping the folder itself.

    Without this the shared profile's storage is a channel between runs (run A copies
    approved data there, run B with network approved sends it out). Best effort: links
    are removed, never followed; errors are ignored. Residual: the profile's registry
    storage key is not cleared. Returns the number of entries removed.
    """
    return _empty_dir(Path(folder))


# ── Win32 API (loaded lazily so this module imports on every OS) ────────────

def _api() -> SimpleNamespace:
    global _API
    if _API is not None:
        return _API
    import ctypes.wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    HANDLE, PVOID = wt.HANDLE, ctypes.c_void_p

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", PVOID), ("Attributes", wt.DWORD)]

    class SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [("AppContainerSid", PVOID), ("Capabilities", PVOID),
                    ("CapabilityCount", wt.DWORD), ("Reserved", wt.DWORD)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                    ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                    ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                    ("lpReserved2", PVOID), ("hStdInput", HANDLE), ("hStdOutput", HANDLE), ("hStdError", HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", PVOID)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", HANDLE), ("hThread", HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", PVOID), ("bInheritHandle", wt.BOOL)]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("Basic", BASIC_LIMIT), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, PVOID, PVOID, wt.BOOL, wt.DWORD, PVOID, wt.LPCWSTR, PVOID, PVOID]
    k32.CreateProcessW.restype = wt.BOOL
    k32.CreatePipe.argtypes = [ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), PVOID, wt.DWORD]
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, PVOID, wt.DWORD, wt.DWORD, HANDLE]
    k32.CreateFileW.restype = HANDLE
    k32.ReadFile.argtypes = [HANDLE, PVOID, wt.DWORD, ctypes.POINTER(wt.DWORD), PVOID]
    k32.CloseHandle.argtypes = [HANDLE]
    k32.WaitForSingleObject.argtypes = [HANDLE, wt.DWORD]
    k32.WaitForSingleObject.restype = wt.DWORD
    k32.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(wt.DWORD)]
    k32.ResumeThread.argtypes = [HANDLE]
    k32.ResumeThread.restype = wt.DWORD
    k32.TerminateProcess.argtypes = [HANDLE, wt.UINT]
    k32.SetHandleInformation.argtypes = [HANDLE, wt.DWORD, wt.DWORD]
    k32.CreateJobObjectW.argtypes = [PVOID, wt.LPCWSTR]
    k32.CreateJobObjectW.restype = HANDLE
    k32.SetInformationJobObject.argtypes = [HANDLE, ctypes.c_int, PVOID, wt.DWORD]
    k32.AssignProcessToJobObject.argtypes = [HANDLE, HANDLE]
    k32.TerminateJobObject.argtypes = [HANDLE, wt.UINT]
    k32.InitializeProcThreadAttributeList.argtypes = [PVOID, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    k32.UpdateProcThreadAttribute.argtypes = [PVOID, wt.DWORD, ctypes.c_size_t, PVOID, ctypes.c_size_t, PVOID, PVOID]
    k32.DeleteProcThreadAttributeList.argtypes = [PVOID]
    k32.LocalFree.argtypes = [PVOID]
    userenv.CreateAppContainerProfile.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, PVOID, wt.DWORD, ctypes.POINTER(PVOID)]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [wt.LPCWSTR, ctypes.POINTER(PVOID)]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    userenv.DeleteAppContainerProfile.argtypes = [wt.LPCWSTR]
    userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    userenv.GetAppContainerFolderPath.argtypes = [wt.LPCWSTR, ctypes.POINTER(PVOID)]
    userenv.GetAppContainerFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [PVOID]
    ole32.CoTaskMemFree.restype = None
    adv.ConvertSidToStringSidW.argtypes = [PVOID, ctypes.POINTER(wt.LPWSTR)]
    adv.ConvertStringSidToSidW.argtypes = [wt.LPCWSTR, ctypes.POINTER(PVOID)]
    adv.FreeSid.argtypes = [PVOID]

    _API = SimpleNamespace(
        wt=wt, k32=k32, adv=adv, userenv=userenv, ole32=ole32, HANDLE=HANDLE, PVOID=PVOID,
        SID_AND_ATTRIBUTES=SID_AND_ATTRIBUTES, SECURITY_CAPABILITIES=SECURITY_CAPABILITIES,
        STARTUPINFOEXW=STARTUPINFOEXW, PROCESS_INFORMATION=PROCESS_INFORMATION,
        SECURITY_ATTRIBUTES=SECURITY_ATTRIBUTES, EXTENDED_LIMIT=EXTENDED_LIMIT,
    )
    return _API


def _sid_str(psid) -> str:
    a = _api()
    s = a.wt.LPWSTR()
    if not a.adv.ConvertSidToStringSidW(psid, ctypes.byref(s)):
        raise ctypes.WinError(ctypes.get_last_error())
    value = s.value
    a.k32.LocalFree(s)
    return value


def ensure_profile(name: str):
    """Create (or reuse) the AppContainer profile; returns (psid, sid_string). Free psid with FreeSid."""
    a = _api()
    psid = a.PVOID()
    hr = a.userenv.CreateAppContainerProfile(name, name, "AI Gator code sandbox", None, 0, ctypes.byref(psid))
    if hr == HRESULT_ALREADY_EXISTS:
        hr = a.userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(psid))
    if hr != 0:
        raise OSError(f"AppContainer profile failed hr=0x{hr & 0xFFFFFFFF:08X}")
    return psid, _sid_str(psid)


def delete_profile(name: str) -> int:
    return _api().userenv.DeleteAppContainerProfile(name) & 0xFFFFFFFF


def _container_folder(sid: str) -> Path | None:
    """The AppContainer storage folder the API returns (%LOCALAPPDATA%\\Packages\\<profile>\\AC), or None."""
    a = _api()
    ptr = a.PVOID()
    try:
        hr = a.userenv.GetAppContainerFolderPath(sid, ctypes.byref(ptr))
        if hr != 0 or not ptr.value:
            _log.warning("sandbox: AppContainer folder lookup failed hr=0x%08X", hr & 0xFFFFFFFF)
            return None
        return Path(ctypes.wstring_at(ptr.value))
    except Exception as exc:
        _log.warning("sandbox: AppContainer folder lookup failed (%s)", type(exc).__name__)
        return None
    finally:
        if ptr.value:
            a.ole32.CoTaskMemFree(ptr)


def _container_dir_ok(folder: Path) -> bool:
    """Only Packages/<this profile>/AC, with neither it nor its parent a link, may be emptied."""
    return (
        folder.name.lower() == "ac"
        and folder.parent.name.lower() in (PROFILE_NAME.lower(), (PROFILE_NAME + SHELL_PROFILE_SUFFIX).lower())
        and folder.parent.parent.name.lower() == "packages"
        and not _is_link(folder)
        and not _is_link(folder.parent)
    )


def _scrub_container(sid: str) -> None:
    """Best effort: clear the shared profile's persistent storage between runs. Never raises."""
    try:
        folder = _container_folder(sid)
        if folder is None:
            return
        if not _container_dir_ok(folder):  # never delete from an unexpected location
            _log.warning("sandbox: unexpected AppContainer folder layout or link; storage not cleared")
            return
        clear_container_storage(folder)
    except Exception as exc:
        _log.warning("sandbox: could not clear AppContainer storage (%s)", type(exc).__name__)


# ── icacls and the grant ledger ─────────────────────────────────────────────

def _icacls(path: Path, *args: str) -> tuple[int, str]:
    _check_icacls_path(str(path))
    r = subprocess.run(
        [_icacls_exe(), str(path), *args], capture_output=True, text=True, errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _grant(path: Path, sid: str, perm: str) -> tuple[int, str]:
    return _icacls(path, "/grant", ace_spec(sid, perm, Path(path).is_dir()), "/Q")


def _revoke(path: Path, sid: str) -> tuple[int, str]:
    return _icacls(path, "/remove:g", f"*{sid}", "/Q")


def _ledger_load() -> dict:
    try:
        data = json.loads(ledger_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError):
        _log.warning("sandbox grant ledger unreadable; starting a new one")
        data = {}
    if not isinstance(data, dict):
        data = {}
    runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    per_run = data.get("per_run") if isinstance(data.get("per_run"), list) else []
    scratch = data.get("scratch") if isinstance(data.get("scratch"), dict) else {}
    return {"runtime": runtime, "per_run": per_run, "scratch": scratch}


def _ledger_save(data: dict) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _ledger_add_per_run(sid: str, path: Path) -> None:
    with _LEDGER_LOCK:
        data = _ledger_load()
        entry = [sid, str(path)]
        if entry not in data["per_run"]:
            data["per_run"].append(entry)
            _ledger_save(data)


def _ledger_remove_per_run(sid: str, path: Path) -> None:
    with _LEDGER_LOCK:
        data = _ledger_load()
        entry = [sid, str(path)]
        if entry in data["per_run"]:
            data["per_run"].remove(entry)
            _ledger_save(data)


def _ensure_runtime_grants(sid: str, paths: list[Path]) -> None:
    with _LEDGER_LOCK:
        data = _ledger_load()
        done = set(data["runtime"].get(sid, []))
        changed = False
        for path in paths:
            key = os.path.normcase(str(path))
            if key in done:
                continue
            rc, out = _grant(path, sid, "RX")
            if rc == 0:
                done.add(key)
                changed = True
            else:
                # Not owned by the user (for example C:\Program Files\nodejs): rely on
                # the default ALL APPLICATION PACKAGES access. A missing grant can only
                # reduce access, never widen it.
                _log.info("sandbox: runtime path not granted (%s); relying on existing access", path)
        if changed:
            data["runtime"][sid] = sorted(done)
            _ledger_save(data)


def _ensure_scratch_grant(sid: str, path: Path) -> bool:
    """Persistent modify grant on the app-owned scratch folder; True when the SID has it.

    A per-run grant would rewrite every file under it (tens of seconds once node_modules is there). The key
    includes the folder's creation time so a deleted and recreated folder is granted again."""
    try:
        key = f"{os.path.normcase(str(path))}|{Path(path).stat().st_ctime_ns}"
    except OSError:
        return False
    with _LEDGER_LOCK:
        data = _ledger_load()
        if key in data["scratch"].get(sid, []):
            return True
        rc, _out = _grant(path, sid, "M")
        if rc != 0:
            return False
        data["scratch"][sid] = [key]
        _ledger_save(data)
        return True


def _revoke_ok(sid: str, path: Path) -> bool:
    """Revoke the SID's ACE on path; True when it is gone (or the path no longer exists)."""
    try:
        if not Path(path).exists():
            return True
        rc, _out = _revoke(path, sid)
    except Exception as exc:
        _log.warning("sandbox: revoke failed for a per-run grant (%s); entry kept for the next sweep", type(exc).__name__)
        return False
    if rc != 0:
        _log.warning("sandbox: revoke failed for a per-run grant (icacls rc=%s); entry kept for the next sweep", rc)
    return rc == 0


def _sweep_locked() -> tuple[int, int]:
    """(cleared, remaining) per-run ledger entries. The caller holds _RUN_LOCK (not reentrant)."""
    with _LEDGER_LOCK:
        data = _ledger_load()
        entries = list(data["per_run"])
        kept = [[sid, path] for sid, path in entries if not _revoke_ok(sid, Path(path))]
        if entries:
            data["per_run"] = kept
            _ledger_save(data)
        return len(entries) - len(kept), len(kept)


def sweep_stale_grants() -> int:
    """Revoke per-run grants left by a crashed run. Returns the number of entries cleared.

    An entry whose revoke failed stays in the ledger so a later sweep retries it."""
    with _RUN_LOCK:
        return _sweep_locked()[0]


def revoke_runtime_grants() -> int:
    """Remove the persistent runtime ACEs (tests and manual cleanup)."""
    with _RUN_LOCK, _LEDGER_LOCK:
        data = _ledger_load()
        count = 0
        for sid, paths in data["runtime"].items():
            for path in paths:
                if Path(path).exists():
                    _revoke(Path(path), sid)
                    count += 1
        data["runtime"] = {}
        for sid, keys in data["scratch"].items():
            for key in keys:
                path = key.rsplit("|", 1)[0]
                if Path(path).exists():
                    _revoke(Path(path), sid)
                    count += 1
        data["scratch"] = {}
        _ledger_save(data)
        return count


# ── Process launch ──────────────────────────────────────────────────────────

def _run_error(started: bool, message: str) -> RuntimeError:
    """SandboxUnavailable while nothing has run; SandboxRunError once the process may have executed."""
    return SandboxRunError(message) if started else SandboxUnavailable(message)


def _valid(handle) -> bool:
    return handle.value not in (None, 0, INVALID_HANDLE_VALUE)


def _run_contained(argv: list[str], cwd: Path, env: dict[str, str], psid, timeout: int, network: bool) -> SandboxResult:
    a = _api()
    k32, wt, HANDLE = a.k32, a.wt, a.HANDLE
    sa = a.SECURITY_ATTRIBUTES(ctypes.sizeof(a.SECURITY_ATTRIBUTES), None, True)

    owned: list = []   # every handle this function opens; closed exactly once in `finally`
    stuck: list = []   # read ends whose pump thread did not finish: leaked on purpose, never closed under it
    pumps: list = []   # (thread, read handle)
    cap_sid = a.PVOID()
    attr_buf = None
    attr_ready = False
    finished = False
    resumed = False  # True once the child may have executed code

    def own(handle):
        owned.append(handle)
        return handle

    def close(handle) -> None:
        if _valid(handle):
            k32.CloseHandle(handle)
        handle.value = None

    def pipe():
        rd, wr = own(HANDLE()), own(HANDLE())
        if not k32.CreatePipe(ctypes.byref(rd), ctypes.byref(wr), ctypes.byref(sa), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        k32.SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0)
        return rd, wr

    proc, thread, job = own(HANDLE()), own(HANDLE()), own(HANDLE())

    def reap() -> None:
        """Close the job (KILL_ON_JOB_CLOSE ends lingering grandchildren, which closes the pipes), then join the pumps."""
        close(job)
        for t, handle in pumps:
            t.join(5)
            if t.is_alive():
                stuck.append(handle)
            else:
                close(handle)

    try:
        out_rd, out_wr = pipe()
        err_rd, err_wr = pipe()
        hin = own(HANDLE(k32.CreateFileW("NUL", GENERIC_READ, FILE_SHARE_READ_WRITE, ctypes.byref(sa),
                                         OPEN_EXISTING, 0, None)))
        if not _valid(hin):
            raise ctypes.WinError(ctypes.get_last_error())

        caps = None
        if network:
            if not a.adv.ConvertStringSidToSidW(INTERNET_CLIENT_SID, ctypes.byref(cap_sid)):
                raise ctypes.WinError(ctypes.get_last_error())
            caps = (a.SID_AND_ATTRIBUTES * 1)(a.SID_AND_ATTRIBUTES(cap_sid, SE_GROUP_ENABLED))
        sc = a.SECURITY_CAPABILITIES(psid, ctypes.cast(caps, a.PVOID) if caps else None, 1 if caps else 0, 0)
        handles = (HANDLE * 3)(hin, out_wr, err_wr)

        size = ctypes.c_size_t()
        k32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        attr_buf = ctypes.create_string_buffer(size.value)
        if not k32.InitializeProcThreadAttributeList(attr_buf, 2, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        attr_ready = True
        if not k32.UpdateProcThreadAttribute(attr_buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                                             ctypes.byref(sc), ctypes.sizeof(sc), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k32.UpdateProcThreadAttribute(attr_buf, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                             ctypes.byref(handles), ctypes.sizeof(handles), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        si = a.STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(si)
        si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = hin, out_wr, err_wr
        si.lpAttributeList = ctypes.cast(attr_buf, a.PVOID)
        block = _env_block(env)
        envbuf = ctypes.create_unicode_buffer(block, len(block))
        cmdline = ctypes.create_unicode_buffer(_cmdline(argv))
        pi = a.PROCESS_INFORMATION()
        flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED | CREATE_NO_WINDOW
        ok = k32.CreateProcessW(None, cmdline, None, None, True, flags, envbuf, str(cwd), ctypes.byref(si), ctypes.byref(pi))
        err = ctypes.get_last_error()
        if not ok:
            raise SandboxUnavailable(f"The sandboxed process could not start (winerror {err}: {ctypes.FormatError(err).strip()}).")
        proc.value, thread.value = pi.hProcess, pi.hThread
        # The child owns its copies now; closing ours lets the pipes reach EOF when it exits.
        for handle in (out_wr, err_wr, hin):
            close(handle)

        # The process is still suspended: contain it before it runs a single instruction.
        job.value = k32.CreateJobObjectW(None, None)
        if not _valid(job):
            raise ctypes.WinError(ctypes.get_last_error())
        ext = a.EXTENDED_LIMIT()
        ext.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(ext), ctypes.sizeof(ext)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k32.AssignProcessToJobObject(job, proc):
            raise ctypes.WinError(ctypes.get_last_error())
        if k32.ResumeThread(thread) == WAIT_FAILED:
            raise ctypes.WinError(ctypes.get_last_error())
        resumed = True

        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []

        def pump(handle, sink):
            chunk = ctypes.create_string_buffer(4096)
            n = wt.DWORD()
            while k32.ReadFile(handle, chunk, 4096, ctypes.byref(n), None) and n.value:
                sink.append(chunk.raw[: n.value])

        for handle, sink in ((out_rd, out_chunks), (err_rd, err_chunks)):
            t = threading.Thread(target=pump, args=(handle, sink), daemon=True)
            try:
                t.start()
            except RuntimeError as exc:
                raise SandboxRunError(f"The sandboxed process started but its output could not be read ({exc}).") from exc
            pumps.append((t, handle))
        waited = k32.WaitForSingleObject(proc, int(timeout * 1000))
        if waited == WAIT_FAILED:
            raise _run_error(resumed, f"Waiting for the sandboxed process failed (winerror {ctypes.get_last_error()}).")
        timed_out = waited == WAIT_TIMEOUT
        if timed_out:
            k32.TerminateJobObject(job, 1)
            k32.WaitForSingleObject(proc, 5000)
        code = wt.DWORD()
        k32.GetExitCodeProcess(proc, ctypes.byref(code))
        reap()
        finished = True
        return SandboxResult(
            returncode=-1 if timed_out else int(code.value),
            stdout=b"".join(out_chunks).decode("utf-8", "replace"),
            stderr=b"".join(err_chunks).decode("utf-8", "replace"),
            timed_out=timed_out,
        )
    except OSError as exc:
        raise _run_error(resumed, f"The sandbox could not start the process ({exc}).") from exc
    finally:
        if not finished:
            if _valid(proc):
                k32.TerminateProcess(proc, 1)
            if _valid(job):
                k32.TerminateJobObject(job, 1)
            reap()
        if attr_ready:
            k32.DeleteProcThreadAttributeList(attr_buf)
        for handle in owned:
            if not any(handle is s for s in stuck):
                close(handle)
        if cap_sid.value:
            k32.LocalFree(cap_sid)


def probe() -> str | None:
    try:
        psid, _sid = ensure_profile(PROFILE_NAME)
    except OSError as exc:
        return f"Windows could not create the AppContainer sandbox profile ({exc})."
    _api().adv.FreeSid(psid)
    return None


def _same_path(a: Path, b: str) -> bool:
    return _covered_by(a, [b]) and _covered_by(Path(b), [str(a)])


def launch(req: SandboxRequest) -> SandboxResult:
    with _RUN_LOCK:
        runtime, per_run = acl_grants(req)
        runtime_dirs = [str(path) for path, _perm in runtime]
        for path, perm in runtime + per_run + ([(Path(req.scratch_path), "M")] if req.scratch_path else []):
            try:
                _check_icacls_path(str(path))
            except ValueError as exc:
                raise SandboxUnavailable(str(exc)) from exc
        for path, perm in per_run:
            if perm != "RX" and any(_same_path(path, d) for d in runtime_dirs):
                # Revoking the per-run ACE would also delete the persistent runtime ACE on the same directory.
                raise SandboxUnavailable(f"{path} is a runtime directory and cannot also be a writable path.")
        # A failed revoke leaves a live ACE for the shared SID that every later run would inherit.
        _cleared, remaining = _sweep_locked()
        if remaining:
            raise SandboxUnavailable(
                "Access granted to an earlier sandboxed run could not be removed, so the sandbox is paused "
                "until it can be. Check that the folders named in the sandbox ledger are still accessible."
            )
        try:
            psid, sid = ensure_profile(PROFILE_NAME + SHELL_PROFILE_SUFFIX if req.scratch_path else PROFILE_NAME)
        except OSError as exc:
            raise SandboxUnavailable(f"Windows could not create the AppContainer sandbox profile ({exc}).") from exc
        try:
            _ensure_runtime_grants(sid, [path for path, _perm in runtime])
            # Read access inside a persistently granted runtime directory already exists; granting and
            # then revoking it per run would remove the persistent ACE.
            granted = _ledger_load()["runtime"].get(sid, [])
            per_run = [(p, perm) for p, perm in per_run if not (perm == "RX" and _covered_by(p, granted))]
            if req.scratch_path is not None and _ensure_scratch_grant(sid, Path(req.scratch_path)):
                per_run = [(p, perm) for p, perm in per_run if not _covered_by(p, [str(req.scratch_path)])]
            _scrub_container(sid)
            attempted: list[Path] = []
            try:
                for path, perm in per_run:
                    _ledger_add_per_run(sid, path)
                    attempted.append(path)
                    rc, out = _grant(path, sid, perm)
                    if rc != 0:
                        raise SandboxUnavailable(f"The sandbox could not be given access to {path} ({out}).")
                return _run_contained(req.argv, req.cwd, req.env, psid, req.timeout, req.network)
            finally:
                for path in attempted:
                    # A failed revoke keeps its ledger entry so the startup sweep retries it.
                    try:
                        if _revoke_ok(sid, path):
                            _ledger_remove_per_run(sid, path)
                    except Exception as exc:  # one failure must not skip the other revokes or the scrub
                        _log.warning("sandbox: could not update the grant ledger (%s)", type(exc).__name__)
                _scrub_container(sid)
        finally:
            _api().adv.FreeSid(psid)
