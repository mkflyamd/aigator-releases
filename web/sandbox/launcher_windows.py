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
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

from . import SandboxRequest, SandboxResult, SandboxUnavailable

_log = logging.getLogger(__name__)

PROFILE_NAME = "AIGator.CodeRunner"
INTERNET_CLIENT_SID = "S-1-15-3-1"

PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
EXTENDED_STARTUPINFO_PRESENT = 0x80000
CREATE_UNICODE_ENVIRONMENT = 0x400
CREATE_SUSPENDED = 0x4
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x100
HANDLE_FLAG_INHERIT = 0x1
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
WAIT_TIMEOUT = 258
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


# ── Win32 API (loaded lazily so this module imports on every OS) ────────────

def _api() -> SimpleNamespace:
    global _API
    if _API is not None:
        return _API
    import ctypes.wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
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
    adv.ConvertSidToStringSidW.argtypes = [PVOID, ctypes.POINTER(wt.LPWSTR)]
    adv.ConvertStringSidToSidW.argtypes = [wt.LPCWSTR, ctypes.POINTER(PVOID)]
    adv.FreeSid.argtypes = [PVOID]

    _API = SimpleNamespace(
        wt=wt, k32=k32, adv=adv, userenv=userenv, HANDLE=HANDLE, PVOID=PVOID,
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


# ── icacls and the grant ledger ─────────────────────────────────────────────

def _icacls(path: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(
        ["icacls", str(path), *args], capture_output=True, text=True, errors="replace",
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
    return {"runtime": runtime, "per_run": per_run}


def _ledger_save(data: dict) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _ledger_add_per_run(sid: str, path: Path) -> None:
    with _LEDGER_LOCK:
        data = _ledger_load()
        data["per_run"].append([sid, str(path)])
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


def sweep_stale_grants() -> int:
    """Revoke per-run grants left by a crashed run. Returns the number of entries cleared."""
    with _RUN_LOCK, _LEDGER_LOCK:
        data = _ledger_load()
        entries = list(data["per_run"])
        for sid, path in entries:
            if Path(path).exists():
                _revoke(Path(path), sid)
        if entries:
            data["per_run"] = []
            _ledger_save(data)
        return len(entries)


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
        _ledger_save(data)
        return count


# ── Process launch ──────────────────────────────────────────────────────────

def _run_contained(argv: list[str], cwd: Path, env: dict[str, str], psid, timeout: int, network: bool) -> SandboxResult:
    a = _api()
    k32, wt, HANDLE = a.k32, a.wt, a.HANDLE
    sa = a.SECURITY_ATTRIBUTES(ctypes.sizeof(a.SECURITY_ATTRIBUTES), None, True)

    def pipe():
        rd, wr = HANDLE(), HANDLE()
        if not k32.CreatePipe(ctypes.byref(rd), ctypes.byref(wr), ctypes.byref(sa), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        k32.SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0)
        return rd, wr

    out_rd, out_wr = pipe()
    err_rd, err_wr = pipe()
    hin = k32.CreateFileW("NUL", GENERIC_READ, FILE_SHARE_READ_WRITE, ctypes.byref(sa), OPEN_EXISTING, 0, None)

    cap_sid = a.PVOID()
    caps = None
    if network:
        if not a.adv.ConvertStringSidToSidW(INTERNET_CLIENT_SID, ctypes.byref(cap_sid)):
            raise ctypes.WinError(ctypes.get_last_error())
        caps = (a.SID_AND_ATTRIBUTES * 1)(a.SID_AND_ATTRIBUTES(cap_sid, SE_GROUP_ENABLED))
    sc = a.SECURITY_CAPABILITIES(psid, ctypes.cast(caps, a.PVOID) if caps else None, 1 if caps else 0, 0)
    handles = (HANDLE * 3)(hin, out_wr, err_wr)

    size = ctypes.c_size_t()
    k32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not k32.InitializeProcThreadAttributeList(buf, 2, 0, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    pi = a.PROCESS_INFORMATION()
    try:
        if not k32.UpdateProcThreadAttribute(buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                                             ctypes.byref(sc), ctypes.sizeof(sc), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k32.UpdateProcThreadAttribute(buf, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                             ctypes.byref(handles), ctypes.sizeof(handles), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        si = a.STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(si)
        si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = hin, out_wr, err_wr
        si.lpAttributeList = ctypes.cast(buf, a.PVOID)
        block = "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) or "\0"
        envbuf = ctypes.create_unicode_buffer(block, len(block) + 1)
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED | CREATE_NO_WINDOW
        ok = k32.CreateProcessW(None, cmdline, None, None, True, flags, envbuf, str(cwd), ctypes.byref(si), ctypes.byref(pi))
        err = ctypes.get_last_error()
    finally:
        k32.DeleteProcThreadAttributeList(buf)
        for h in (out_wr, err_wr, hin):
            k32.CloseHandle(h)
        if cap_sid:
            k32.LocalFree(cap_sid)
    if not ok:
        k32.CloseHandle(out_rd)
        k32.CloseHandle(err_rd)
        raise SandboxUnavailable(f"The sandboxed process could not start (winerror {err}: {ctypes.FormatError(err).strip()}).")

    job = k32.CreateJobObjectW(None, None)
    ext = a.EXTENDED_LIMIT()
    ext.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if job:
        k32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(ext), ctypes.sizeof(ext))
    if not job or not k32.AssignProcessToJobObject(job, pi.hProcess):
        err = ctypes.get_last_error()
        k32.TerminateProcess(pi.hProcess, 1)
        for h in (out_rd, err_rd, pi.hProcess, pi.hThread):
            k32.CloseHandle(h)
        if job:
            k32.CloseHandle(job)
        raise SandboxUnavailable(f"The sandboxed process could not be placed in a job object (winerror {err}).")
    k32.ResumeThread(pi.hThread)

    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []

    def pump(handle, sink):
        chunk = ctypes.create_string_buffer(4096)
        n = wt.DWORD()
        while k32.ReadFile(handle, chunk, 4096, ctypes.byref(n), None) and n.value:
            sink.append(chunk.raw[: n.value])

    threads = [threading.Thread(target=pump, args=(out_rd, out_chunks), daemon=True),
               threading.Thread(target=pump, args=(err_rd, err_chunks), daemon=True)]
    for t in threads:
        t.start()
    timed_out = k32.WaitForSingleObject(pi.hProcess, int(timeout * 1000)) == WAIT_TIMEOUT
    if timed_out:
        k32.TerminateJobObject(job, 1)
        k32.WaitForSingleObject(pi.hProcess, 5000)
    code = wt.DWORD()
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    k32.CloseHandle(job)  # KILL_ON_JOB_CLOSE: grandchildren still running die here, closing the pipes
    for t in threads:
        t.join(5)
    for h in (out_rd, err_rd, pi.hProcess, pi.hThread):
        k32.CloseHandle(h)
    return SandboxResult(
        returncode=-1 if timed_out else int(code.value),
        stdout=b"".join(out_chunks).decode("utf-8", "replace"),
        stderr=b"".join(err_chunks).decode("utf-8", "replace"),
        timed_out=timed_out,
    )


def probe() -> str | None:
    try:
        psid, _sid = ensure_profile(PROFILE_NAME)
    except OSError as exc:
        return f"Windows could not create the AppContainer sandbox profile ({exc})."
    _api().adv.FreeSid(psid)
    return None


def launch(req: SandboxRequest) -> SandboxResult:
    with _RUN_LOCK:
        try:
            psid, sid = ensure_profile(PROFILE_NAME)
        except OSError as exc:
            raise SandboxUnavailable(f"Windows could not create the AppContainer sandbox profile ({exc}).") from exc
        try:
            runtime, per_run = acl_grants(req)
            _ensure_runtime_grants(sid, [path for path, _perm in runtime])
            try:
                for path, perm in per_run:
                    _ledger_add_per_run(sid, path)
                    rc, out = _grant(path, sid, perm)
                    if rc != 0:
                        raise SandboxUnavailable(f"The sandbox could not be given access to {path} ({out}).")
                return _run_contained(req.argv, req.cwd, req.env, psid, req.timeout, req.network)
            finally:
                for path, _perm in per_run:
                    _revoke(path, sid)
                    _ledger_remove_per_run(sid, path)
        finally:
            _api().adv.FreeSid(psid)
