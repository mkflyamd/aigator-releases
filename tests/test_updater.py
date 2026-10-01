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


@pytest.mark.asyncio
async def test_check_for_update_returns_info_when_newer(tmp_path):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text("1.0.0")

    manifest_response = MagicMock()
    manifest_response.raise_for_status = MagicMock()
    manifest_response.json.return_value = {
        "version": "1.1.0",
        "url": "https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        "sha256": "a" * 64,
        "notes": "Bug fixes",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=manifest_response)

    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "MANIFEST_URL", "https://example.com/latest.json"),
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
    ):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is not None
    assert result.version == "1.1.0"
    assert result.sha256 == "a" * 64
    assert updater._state.state == "available"


@pytest.mark.asyncio
async def test_check_for_update_returns_none_when_current(tmp_path):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text("1.1.0")

    manifest_response = MagicMock()
    manifest_response.raise_for_status = MagicMock()
    manifest_response.json.return_value = {
        "version": "1.1.0",
        "url": "https://example.com/AIGatorInstaller.exe",
        "notes": "",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=manifest_response)

    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "MANIFEST_URL", "https://example.com/latest.json"),
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
    ):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is None
    assert updater._state.state == "up_to_date"


@pytest.mark.asyncio
async def test_check_for_update_silent_on_network_error(tmp_path):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text("1.0.0")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "MANIFEST_URL", "https://example.com/latest.json"),
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
    ):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is None
    assert updater._state.state == "idle"


@pytest.mark.asyncio
async def test_check_for_update_skipped_when_no_url(tmp_path):
    import web.updater as updater

    with patch.object(updater, "MANIFEST_URL", ""):
        updater._state.state = "idle"
        result = await updater.check_for_update()
    assert result is None
    assert updater._state.state == "idle"


@pytest.mark.asyncio
async def test_check_for_update_rejects_untrusted_url(tmp_path):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text("1.0.0")

    manifest_response = MagicMock()
    manifest_response.raise_for_status = MagicMock()
    manifest_response.json.return_value = {
        "version": "1.1.0",
        "url": "https://evil.example.com/AIGatorInstaller.exe",
        "sha256": "a" * 64,
        "notes": "",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=manifest_response)

    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "MANIFEST_URL", "https://example.com/latest.json"),
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
    ):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is None
    assert updater._state.state == "idle"


@pytest.mark.asyncio
async def test_check_for_update_rejects_url_version_mismatch(tmp_path):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text("1.0.0")

    manifest_response = MagicMock()
    manifest_response.raise_for_status = MagicMock()
    manifest_response.json.return_value = {
        "version": "99.0.0",
        "url": "https://github.com/mkflyamd/aigator-releases/releases/download/v1.0.5/AIGatorInstaller.exe",
        "sha256": "a" * 64,
        "notes": "",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=manifest_response)

    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "MANIFEST_URL", "https://example.com/latest.json"),
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
    ):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is None
    assert updater._state.state == "idle"


@pytest.mark.asyncio
async def test_download_update_wrong_signer_sets_error_and_removes_file(tmp_path):
    import hashlib
    import web.updater as updater

    content = b"fake-installer-bytes"
    expected_sha = hashlib.sha256(content).hexdigest()

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        sha256=expected_sha,
        notes="",
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
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        sha256=expected_sha,
        notes="",
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
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        sha256=expected_sha,
        notes="",
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


@pytest.mark.asyncio
async def test_download_update_checksum_mismatch_sets_error_and_removes_file(tmp_path):
    import web.updater as updater

    updater._state = updater._UpdateState()
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        sha256="0" * 64,
        notes="",
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


@pytest.mark.asyncio
async def test_check_for_update_rejects_malformed_sha256(tmp_path):
    import web.updater as updater

    vf = tmp_path / "version.txt"
    vf.write_text("1.0.0")

    manifest_response = MagicMock()
    manifest_response.raise_for_status = MagicMock()
    manifest_response.json.return_value = {
        "version": "1.1.0",
        "url": "https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AIGatorInstaller.exe",
        "sha256": "not-a-real-hash",
        "notes": "",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=manifest_response)

    with (
        patch.object(updater, "VERSION_FILE", vf),
        patch.object(updater, "MANIFEST_URL", "https://example.com/latest.json"),
        patch("web.updater.httpx.AsyncClient", return_value=mock_client),
    ):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is None
    assert updater._state.state == "idle"
