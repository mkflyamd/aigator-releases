"""Unit tests for web/updater.py — version comparison, manifest parsing, state machine."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def test_get_current_version_reads_file(tmp_path):
    vf = tmp_path / "version.txt"
    vf.write_text("1.2.3")
    import web.updater as updater
    with patch.object(updater, 'VERSION_FILE', vf):
        assert updater.get_current_version() == "1.2.3"


def test_get_current_version_missing_returns_000(tmp_path):
    import web.updater as updater
    with patch.object(updater, 'VERSION_FILE', tmp_path / "nonexistent.txt"):
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
        "url": "https://example.com/AIGatorInstaller.exe",
        "notes": "Bug fixes",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=manifest_response)

    with patch.object(updater, 'VERSION_FILE', vf), \
         patch.object(updater, 'MANIFEST_URL', "https://example.com/latest.json"), \
         patch("web.updater.httpx.AsyncClient", return_value=mock_client):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is not None
    assert result.version == "1.1.0"
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

    with patch.object(updater, 'VERSION_FILE', vf), \
         patch.object(updater, 'MANIFEST_URL', "https://example.com/latest.json"), \
         patch("web.updater.httpx.AsyncClient", return_value=mock_client):
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

    with patch.object(updater, 'VERSION_FILE', vf), \
         patch.object(updater, 'MANIFEST_URL', "https://example.com/latest.json"), \
         patch("web.updater.httpx.AsyncClient", return_value=mock_client):
        updater._state.state = "idle"
        result = await updater.check_for_update()

    assert result is None
    assert updater._state.state == "idle"


@pytest.mark.asyncio
async def test_check_for_update_skipped_when_no_url(tmp_path):
    import web.updater as updater
    with patch.object(updater, 'MANIFEST_URL', ""):
        updater._state.state = "idle"
        result = await updater.check_for_update()
    assert result is None
    assert updater._state.state == "idle"
