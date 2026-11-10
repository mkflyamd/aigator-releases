"""Unit tests for web/updater.py — version comparison, manifest parsing, state machine."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def test_get_current_version_reads_file(tmp_path):
    vf = tmp_path / "version.txt"
    vf.write_text("1.2.3")
    import web.updater as updater

    with patch.object(updater, "VERSION_FILE", vf):
        assert updater.get_current_version() == "1.2.3"


def test_get_current_version_missing_returns_000(tmp_path):
    import web.updater as updater

    with patch.object(updater, "VERSION_FILE", tmp_path / "nonexistent.txt"):
        assert updater.get_current_version() == "0.0.0"


def test_version_comparison_newer_triggers_update():
    from packaging.version import Version

    assert Version("1.1.0") > Version("1.0.0")
    assert Version("1.0.10") > Version("1.0.9")
    assert not Version("1.0.0") > Version("1.0.0")


SHA_A = "a" * 64
SHA_B = "b" * 64
CHECKSUMS = (
    f"{SHA_A}  AI-Gator-1.1.0-Linux-x64.AppImage\n"
    f"{SHA_B}  AI-Gator-1.1.0-Windows-x64.exe\n"
    f"{SHA_A}  AI-Gator-1.1.0-macOS-arm64.dmg\n"
)
WINDOWS_URL = "https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AI-Gator-1.1.0-Windows-x64.exe"


def _mock_checksums_client(text=None, error=None):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.text = text
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=response, side_effect=error)
    return mock_client


async def _run_check(tmp_path, current, client, first_signed=None, platform="win32"):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text(current)
    updater._state = updater._UpdateState()
    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "FIRST_SIGNED_VERSION", first_signed),
        patch.object(updater.sys, "platform", platform),
        patch("web.updater.httpx.AsyncClient", return_value=client),
    ):
        return await updater.check_for_update()


def test_parse_checksums_finds_windows_installer():
    import web.updater as updater

    assert updater.parse_checksums(CHECKSUMS) == ("1.1.0", "AI-Gator-1.1.0-Windows-x64.exe", SHA_B)


def test_parse_checksums_accepts_binary_mode_marker():
    import web.updater as updater

    text = f"{SHA_B} *AI-Gator-1.1.0-Windows-x64.exe\n"
    assert updater.parse_checksums(text) == ("1.1.0", "AI-Gator-1.1.0-Windows-x64.exe", SHA_B)


@pytest.mark.parametrize(
    "text",
    [
        "",
        f"{SHA_A}  AI-Gator-1.1.0-macOS-arm64.dmg\n",
        "not-a-hash  AI-Gator-1.1.0-Windows-x64.exe\n",
        f"{SHA_A}  evil/AI-Gator-1.1.0-Windows-x64.exe\n",
        f"{SHA_A}  AI-Gator-1.1.0-Windows-x64.exe.sig\n",
    ],
)
def test_parse_checksums_rejects_invalid(text):
    import web.updater as updater

    assert updater.parse_checksums(text) is None


@pytest.mark.asyncio
async def test_check_for_update_returns_info_when_newer(tmp_path):
    import web.updater as updater

    result = await _run_check(tmp_path, "1.0.9", _mock_checksums_client(CHECKSUMS))

    assert result is not None
    assert result.version == "1.1.0"
    assert result.sha256 == SHA_B
    assert result.url == WINDOWS_URL
    assert updater._state.state == "available"


@pytest.mark.asyncio
async def test_check_for_update_detects_double_digit_patch_release(tmp_path):
    text = f"{SHA_B}  AI-Gator-1.0.10-Windows-x64.exe\n"

    result = await _run_check(tmp_path, "1.0.9", _mock_checksums_client(text))

    assert result is not None and result.version == "1.0.10"


@pytest.mark.asyncio
async def test_check_for_update_install_unsupported_until_signed_version(tmp_path):
    result = await _run_check(tmp_path, "1.0.9", _mock_checksums_client(CHECKSUMS))
    assert result.install_supported is False


@pytest.mark.asyncio
async def test_check_for_update_install_supported_from_first_signed_version(tmp_path):
    result = await _run_check(tmp_path, "1.0.9", _mock_checksums_client(CHECKSUMS), first_signed="1.1.0")
    assert result.install_supported is True


@pytest.mark.asyncio
async def test_check_for_update_install_unsupported_below_first_signed_version(tmp_path):
    result = await _run_check(tmp_path, "1.0.9", _mock_checksums_client(CHECKSUMS), first_signed="1.2.0")
    assert result.install_supported is False


@pytest.mark.asyncio
async def test_check_for_update_returns_none_when_current(tmp_path):
    import web.updater as updater

    result = await _run_check(tmp_path, "1.1.0", _mock_checksums_client(CHECKSUMS))

    assert result is None
    assert updater._state.state == "up_to_date"


@pytest.mark.asyncio
async def test_check_for_update_logs_and_stays_idle_on_network_error(tmp_path, caplog):
    import web.updater as updater

    client = _mock_checksums_client(error=Exception("connection refused"))
    with caplog.at_level("WARNING"):
        result = await _run_check(tmp_path, "1.0.9", client)

    assert result is None
    assert updater._state.state == "idle"
    assert "Update check failed" in caplog.text


@pytest.mark.asyncio
async def test_check_for_update_idle_when_release_has_no_windows_installer(tmp_path):
    import web.updater as updater

    text = f"{SHA_A}  AI-Gator-1.1.0-macOS-arm64.dmg\n"
    result = await _run_check(tmp_path, "1.0.9", _mock_checksums_client(text))

    assert result is None
    assert updater._state.state == "idle"


@pytest.mark.asyncio
async def test_check_for_update_skipped_when_no_url():
    import web.updater as updater

    with patch.object(updater, "CHECKSUMS_URL", ""):
        updater._state.state = "idle"
        result = await updater.check_for_update()
    assert result is None
    assert updater._state.state == "idle"


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.asyncio
async def test_check_for_update_off_windows_reports_release_without_install(tmp_path, platform):
    import web.updater as updater

    text = f"{SHA_A}  AI-Gator-1.1.0-macOS-arm64.dmg\n"
    result = await _run_check(tmp_path, "1.0.9", _mock_checksums_client(text), first_signed="1.0.0", platform=platform)

    assert result is not None
    assert result.version == "1.1.0"
    assert result.install_supported is False
    assert updater._state.state == "available"


@pytest.mark.asyncio
async def test_check_for_update_off_windows_idle_when_no_assets(tmp_path):
    import web.updater as updater

    result = await _run_check(tmp_path, "1.0.9", _mock_checksums_client("junk\n"), platform="darwin")

    assert result is None
    assert updater._state.state == "idle"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"{SHA_A}  AI-Gator-1.1.0-macOS-arm64.dmg\n", "1.1.0"),
        (f"{SHA_A} *AI-Gator-2.0.1-Linux-x64.AppImage\n", "2.0.1"),
        ("", None),
        (f"{SHA_A}  other-1.1.0.dmg\n", None),
    ],
)
def test_parse_release_version(text, expected):
    import web.updater as updater

    assert updater.parse_release_version(text) == expected


@pytest.mark.asyncio
async def test_download_update_refused_when_install_unsupported():
    import web.updater as updater

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(version="1.1.0", url=WINDOWS_URL, sha256=SHA_B, notes="")

    await updater.download_update()

    assert updater._state.state == "error"
    assert "not available" in updater._state.error


def test_install_script_stops_app_then_runs_installer_silently():
    import web.updater as updater

    script = updater._INSTALL_SCRIPT

    assert "$env:AIGATOR_INSTALLER" in script
    assert "'/S','--updated','--force-run'" in script
    assert script.index("Stop-Process") < script.index("Start-Process")


def test_install_script_relaunches_app_and_logs_when_installer_fails():
    import web.updater as updater

    script = updater._INSTALL_SCRIPT
    failure = script[script.index("if (-not $ok)") :]

    assert "$env:AIGATOR_UPDATE_LOG" in failure
    assert "$env:AIGATOR_APP_EXE" in failure
    assert "Start-Process" in failure


def test_install_script_process_filter_is_anchored_to_the_app_directory():
    import web.updater as updater

    assert "TrimEnd('\\') + '\\'" in updater._INSTALL_SCRIPT


def test_launch_installer_passes_paths_in_environment_not_script(tmp_path):
    import web.updater as updater

    installer = tmp_path / "O'Brien ’s" / "AIGatorInstaller.exe"
    installer.parent.mkdir()
    installer.write_bytes(b"x")
    updater._state = updater._UpdateState()
    updater._state._installer_path = str(installer)

    with (
        patch.object(updater.sys, "frozen", True, create=True),
        patch.object(updater.sys, "executable", str(tmp_path / "app" / "resources" / "backend" / "aigator-backend.exe")),
        patch.object(updater.subprocess, "DETACHED_PROCESS", 0x8, create=True),
        patch.object(updater.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True),
        patch.object(updater.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x1000000, create=True),
        patch("web.updater.subprocess.Popen") as popen,
    ):
        updater.launch_installer()

    args, kwargs = popen.call_args
    assert str(installer) not in args[0][-1]
    assert kwargs["env"]["AIGATOR_INSTALLER"] == str(installer)
    assert kwargs["env"]["AIGATOR_APP_DIR"] == str((tmp_path / "app").resolve())
    assert kwargs["env"]["AIGATOR_UPDATE_LOG"] == str(installer.with_suffix(".log"))


def test_launch_installer_refuses_when_not_packaged(tmp_path, caplog):
    import web.updater as updater

    installer = tmp_path / "AIGatorInstaller.exe"
    installer.write_bytes(b"x")
    updater._state = updater._UpdateState()
    updater._state._installer_path = str(installer)

    with caplog.at_level("WARNING"), patch("web.updater.subprocess.Popen") as popen:
        updater.launch_installer()

    popen.assert_not_called()
    assert updater._state.state == "error"
    assert "outside the packaged app" in caplog.text


@pytest.mark.asyncio
async def test_download_update_wrong_signer_sets_error_and_removes_file(tmp_path):
    import hashlib
    import web.updater as updater

    content = b"fake-installer-bytes"
    expected_sha = hashlib.sha256(content).hexdigest()

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AI-Gator-1.1.0-Windows-x64.exe",
        sha256=expected_sha,
        notes="",
        install_supported=True,
    )

    async def fake_aiter_bytes(chunk_size=65536):
        yield content

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.aiter_bytes = fake_aiter_bytes

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_sig_result = MagicMock()
    mock_sig_result.returncode = 0
    mock_sig_result.stdout = "Valid|DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF\n"

    with (
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
        patch("web.updater.tempfile.gettempdir", return_value=str(tmp_path)),
        patch("web.updater.subprocess.run", return_value=mock_sig_result),
    ):
        await updater.download_update()

    assert updater._state.state == "error"
    assert updater._state.error == "untrusted signer"
    assert not (tmp_path / "AIGatorInstaller.exe").exists()


@pytest.mark.asyncio
async def test_download_update_invalid_signature_status_sets_error(tmp_path):
    import hashlib
    import web.updater as updater

    content = b"fake-installer-bytes"
    expected_sha = hashlib.sha256(content).hexdigest()

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AI-Gator-1.1.0-Windows-x64.exe",
        sha256=expected_sha,
        notes="",
        install_supported=True,
    )

    async def fake_aiter_bytes(chunk_size=65536):
        yield content

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.aiter_bytes = fake_aiter_bytes

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_sig_result = MagicMock()
    mock_sig_result.returncode = 0
    mock_sig_result.stdout = "NotSigned|\n"

    with (
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
        patch("web.updater.tempfile.gettempdir", return_value=str(tmp_path)),
        patch("web.updater.subprocess.run", return_value=mock_sig_result),
    ):
        await updater.download_update()

    assert updater._state.state == "error"
    assert updater._state.error == "invalid signature"
    assert not (tmp_path / "AIGatorInstaller.exe").exists()


@pytest.mark.asyncio
async def test_download_update_valid_checksum_and_signature_sets_ready(tmp_path):
    import hashlib
    import web.updater as updater

    content = b"fake-installer-bytes"
    expected_sha = hashlib.sha256(content).hexdigest()

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AI-Gator-1.1.0-Windows-x64.exe",
        sha256=expected_sha,
        notes="",
        install_supported=True,
    )

    async def fake_aiter_bytes(chunk_size=65536):
        yield content

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.aiter_bytes = fake_aiter_bytes

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_sig_result = MagicMock()
    mock_sig_result.returncode = 0
    mock_sig_result.stdout = f"Valid|{updater.EXPECTED_SIGNING_THUMBPRINT}\n"

    with (
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
        patch("web.updater.tempfile.gettempdir", return_value=str(tmp_path)),
        patch("web.updater.subprocess.run", return_value=mock_sig_result),
    ):
        await updater.download_update()

    assert updater._state.state == "ready"
    assert updater._state._installer_path == str(tmp_path / "AIGatorInstaller.exe")


def _sig_run_result(stdout):
    result = MagicMock()
    result.returncode = 0
    result.stdout = stdout
    return result


def test_verify_signature_accepts_untrusted_root_with_pinned_thumbprint(tmp_path):
    import web.updater as updater

    out = f"UnknownError|{updater.EXPECTED_SIGNING_THUMBPRINT}\n"
    with patch("web.updater.subprocess.run", return_value=_sig_run_result(out)):
        assert updater._verify_authenticode_signature(tmp_path / "x.exe") == (True, "")


def test_verify_signature_rejects_untrusted_root_with_other_thumbprint(tmp_path):
    import web.updater as updater

    out = "UnknownError|311920B31500EFAA691D43B0538F536B4E0261BA\n"
    with patch("web.updater.subprocess.run", return_value=_sig_run_result(out)):
        assert updater._verify_authenticode_signature(tmp_path / "x.exe") == (False, "untrusted signer")


def test_verify_signature_rejects_hash_mismatch_even_with_pinned_thumbprint(tmp_path):
    import web.updater as updater

    out = f"HashMismatch|{updater.EXPECTED_SIGNING_THUMBPRINT}\n"
    with patch("web.updater.subprocess.run", return_value=_sig_run_result(out)):
        assert updater._verify_authenticode_signature(tmp_path / "x.exe") == (False, "invalid signature")


@pytest.mark.asyncio
async def test_download_update_checksum_mismatch_sets_error_and_removes_file(tmp_path):
    import web.updater as updater

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AI-Gator-1.1.0-Windows-x64.exe",
        sha256="0" * 64,
        notes="",
        install_supported=True,
    )

    async def fake_aiter_bytes(chunk_size=65536):
        yield b"not-the-real-installer-bytes"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {}
    mock_resp.aiter_bytes = fake_aiter_bytes

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with (
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
        patch("web.updater.tempfile.gettempdir", return_value=str(tmp_path)),
    ):
        await updater.download_update()

    assert updater._state.state == "error"
    assert updater._state.error == "checksum mismatch"
    assert not (tmp_path / "AIGatorInstaller.exe").exists()
