import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'web'))

import json
import time
from unittest.mock import patch
from marketplace.registry import (
    merge_catalogs, normalize_entry, _fetch_json_url,
    fetch_anthropic_skills, _fetch_anthropic_skill_ids,
    _load_anthropic_dir_cache, _save_anthropic_dir_cache,
    _ANTHROPIC_DIR_CACHE_TTL,
)

SAMPLE_ENTRY = {
    "id": "powerbi", "name": "Power BI", "description": "Read Power BI reports",
    "version": "1.0.0", "tier": "Verified", "install_url": "https://example.com/powerbi.gator",
    "install_count": 100, "category": "Productivity", "license": "MIT", "has_tools": False
}

def test_merge_dedup():
    a = [dict(SAMPLE_ENTRY)]
    b = [dict(SAMPLE_ENTRY, name="Power BI duplicate")]
    result = merge_catalogs([a, b])
    assert len(result) == 1
    assert result[0]["name"] == "Power BI"  # first source wins

def test_merge_unique():
    a = [dict(SAMPLE_ENTRY)]
    b = [dict(SAMPLE_ENTRY, id="gmail", name="Gmail")]
    result = merge_catalogs([a, b])
    assert len(result) == 2

def test_normalize_defaults():
    minimal = {"id": "test", "name": "Test", "description": "desc"}
    result = normalize_entry(minimal)
    assert result["tier"] == "Community"
    assert result["has_tools"] is False
    assert result["install_count"] == 0
    assert result["category"] == ""

def test_fetch_error_handling():
    with patch("urllib.request.urlopen", side_effect=Exception("network error")):
        result = _fetch_json_url("https://example.com/bad.json")
    assert result == []


# ── Anthropic skills directory-listing cache ─────────────────────────────────
# The api.github.com call to list skill directories is unauthenticated (60
# req/hour) and ran at every refresh + restart, 403ing constantly. The cache
# skips the API call for 24h; on a 403 it falls back to the stale cache so the
# Anthropic source degrades gracefully instead of disappearing.

def test_dir_cache_skip_api_call_when_fresh(tmp_path, monkeypatch):
    """A fresh cache means no api.github.com call is made."""
    cache_file = tmp_path / "anthropic_dir_cache.json"
    cache_file.write_text(json.dumps({
        "fetched_at": time.time(),
        "skill_ids": ["skill-a", "skill-b"],
    }), encoding="utf-8")
    monkeypatch.setattr("marketplace.registry._ANTHROPIC_DIR_CACHE_FILE", cache_file)

    # urlopen must NOT be called — if it is, the test fails loudly.
    with patch("urllib.request.urlopen", side_effect=AssertionError("API call should be skipped when cache is fresh")):
        ids, from_cache = _fetch_anthropic_skill_ids()
    assert ids == ["skill-a", "skill-b"]
    assert from_cache is True


def test_dir_cache_fetches_api_when_stale(tmp_path, monkeypatch):
    """An expired cache triggers a fresh api.github.com call and updates the cache."""
    cache_file = tmp_path / "anthropic_dir_cache.json"
    cache_file.write_text(json.dumps({
        "fetched_at": time.time() - _ANTHROPIC_DIR_CACHE_TTL - 1,  # stale
        "skill_ids": ["old-skill"],
    }), encoding="utf-8")
    monkeypatch.setattr("marketplace.registry._ANTHROPIC_DIR_CACHE_FILE", cache_file)

    fake_response = [{"type": "dir", "name": "new-skill-1"}, {"type": "file", "name": "README.md"}, {"type": "dir", "name": "new-skill-2"}]
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(fake_response).encode()
        ids, from_cache = _fetch_anthropic_skill_ids()
    assert ids == ["new-skill-1", "new-skill-2"]
    assert from_cache is False
    # cache was updated with the fresh ids
    saved = json.loads(cache_file.read_text(encoding="utf-8"))
    assert saved["skill_ids"] == ["new-skill-1", "new-skill-2"]


def test_dir_cache_falls_back_to_stale_on_403(tmp_path, monkeypatch):
    """On a 403 (rate limit), the stale cache is used instead of returning empty."""
    cache_file = tmp_path / "anthropic_dir_cache.json"
    cache_file.write_text(json.dumps({
        "fetched_at": time.time() - _ANTHROPIC_DIR_CACHE_TTL - 1,  # stale
        "skill_ids": ["stale-but-usable"],
    }), encoding="utf-8")
    monkeypatch.setattr("marketplace.registry._ANTHROPIC_DIR_CACHE_FILE", cache_file)

    with patch("urllib.request.urlopen", side_effect=Exception("HTTP Error 403: rate limit exceeded")):
        ids, from_cache = _fetch_anthropic_skill_ids()
    assert ids == ["stale-but-usable"]
    assert from_cache is True  # fell back to cache


def test_dir_cache_no_cache_and_403_returns_empty(tmp_path, monkeypatch):
    """No cache + 403 = empty list (can't do better), but no exception raised."""
    monkeypatch.setattr("marketplace.registry._ANTHROPIC_DIR_CACHE_FILE", tmp_path / "nonexistent.json")
    with patch("urllib.request.urlopen", side_effect=Exception("HTTP Error 403: rate limit exceeded")):
        ids, from_cache = _fetch_anthropic_skill_ids()
    assert ids == []
    assert from_cache is False


def test_fetch_anthropic_skills_uses_cached_ids(monkeypatch, tmp_path):
    """fetch_anthropic_skills skips the API call when the cache is fresh and
    fetches SKILL.md for the cached IDs (not the API)."""
    cache_file = tmp_path / "anthropic_dir_cache.json"
    cache_file.write_text(json.dumps({
        "fetched_at": time.time(),
        "skill_ids": ["cached-skill"],
    }), encoding="utf-8")
    monkeypatch.setattr("marketplace.registry._ANTHROPIC_DIR_CACHE_FILE", cache_file)

    # _fetch_skill_md is what fetches SKILL.md — patch it to avoid real network
    def fake_fetch_md(skill_id):
        return {"id": skill_id, "name": skill_id, "tier": "Community", "source": "anthropic"}
    monkeypatch.setattr("marketplace.registry._fetch_skill_md", fake_fetch_md)

    with patch("urllib.request.urlopen", side_effect=AssertionError("API call should be skipped")):
        skills = fetch_anthropic_skills()
    assert len(skills) == 1
    assert skills[0]["id"] == "cached-skill"
